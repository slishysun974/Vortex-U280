"""Validate a prepared RTL input, or explicitly run a bounded XO/link stage on the server."""
import argparse
import datetime
import difflib
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def validate_input(source, exact=True):
    """Bind the entire prepared input; manifest is an inventory, not a subset."""
    source = source.resolve()
    manifest = json.loads((source / "manifest.json").read_text())
    if not isinstance(manifest, list) or not manifest:
        raise ValueError("empty/invalid input manifest")
    names = set()
    for item in manifest:
        name = item["path"]
        path = PurePosixPath(name)
        if (not name or path.is_absolute() or path.as_posix() != name or
                ".." in path.parts or "\\" in name or ":" in name or
                name == "manifest.json" or name in names):
            raise ValueError("unsafe/duplicate input path: " + name)
        names.add(name)
        target = source.joinpath(*path.parts)
        if any(p.is_symlink() for p in (target,) + tuple(target.parents) if p != source):
            raise ValueError("symlink input: " + name)
        target.resolve().relative_to(source)
        if (not target.is_file() or digest(target) != item["sha256"] or
                target.stat().st_size != item["bytes"]):
            raise ValueError("input identity mismatch: " + name)
    required = {"fpga.json", "target_lock.json", "target_lock.sha256", "sources.txt",
                "xrt/gen_xo.tcl", "xrt/package_kernel.tcl", "scripts/xilinx_elab_check.tcl"}
    if not required <= names:
        raise ValueError("manifest omits required input")
    if exact:
        actual = set()
        for path in source.rglob("*"):
            if path.is_symlink():
                raise ValueError("symlink in package")
            if path.is_file():
                actual.add(path.relative_to(source).as_posix())
            elif not path.is_dir():
                raise ValueError("non-regular package member")
        if actual != names | {"manifest.json"}:
            raise ValueError("package file inventory differs from manifest")
    cfg = json.loads((source / "fpga.json").read_text())
    lock = json.loads((source / "target_lock.json").read_text())
    lock_hash = digest(source / "target_lock.json")
    if (digest(source / "fpga.json") != lock["hardware_config_sha256"] or
            lock_hash != (source / "target_lock.sha256").read_text().strip()):
        raise ValueError("candidate identity mismatch")
    return cfg, dict(target_lock_sha256=lock_hash,
                     input_manifest_sha256=digest(source / "manifest.json"), input_files=len(names))


def validate_xo(previous_run, identity):
    previous = json.loads((previous_run / "result.json").read_text())
    if (previous.get("status") != "PASS" or previous.get("exit_code") != 0 or
            previous.get("stage") != "xo" or
            any(previous.get(k) != identity[k] for k in ("target_lock_sha256", "input_manifest_sha256", "build_flow", "flow_sha256") if k in identity)):
        raise ValueError("XO input does not match this complete input package")
    artifact = previous.get("artifact", {})
    path = previous_run / "out/vortex_afu.xo"
    if (artifact.get("path") != "out/vortex_afu.xo" or path.is_symlink() or not path.is_file() or
            path.stat().st_size == 0 or path.stat().st_size != artifact.get("bytes") or
            digest(path) != artifact.get("sha256")):
        raise ValueError("XO artifact identity mismatch")
    return path


def prepare_flow(source, work, flow):
    """Record build-only patches in a separate copy; RTL input remains immutable."""
    if flow == "pinned":
        return work / "input", dict(build_flow=flow, flow_sha256=None)
    if flow != "ip-ooc-v1":
        raise ValueError("unknown build flow")
    folder = work / "flow"
    for name in ("scripts", "xrt"):
        shutil.copytree(source / name, folder / name)
    changes = [
        ("xrt/gen_xo.tcl", "set argv [list ${build_dir}/ip]\nset argc 1",
         "set argv [list ${build_dir}/ip $::env(VORTEX_DEVICE_PART)]\nset argc 2"),
        ("scripts/xilinx_ip_gen.tcl", "generate_target all [get_ips]\n\nclose_project -delete",
         """generate_target all [get_ips]
foreach generated_ip [lsort [get_ips]] {
    set ip_name [get_property NAME $generated_ip]
    set_property GENERATE_SYNTH_CHECKPOINT true [get_files "${ip_dir}/${ip_name}/${ip_name}.xci"]
    synth_ip $generated_ip
    set stub_path "${ip_dir}/${ip_name}/${ip_name}_stub.v"
    if {![file isfile $stub_path]} { error "Missing generated IP stub: $stub_path" }
    puts "U280-IP-OOC-PASS: $ip_name $stub_path"
}

close_project -delete"""),
        ("scripts/xilinx_elab_check.tcl", "    create_project -in_memory\n",
         "    create_project -in_memory -part $::env(VORTEX_DEVICE_PART)\n"),
        ("xrt/package_kernel.tcl", "create_project -force kernel_pack $path_to_tmp_project",
         "create_project -force kernel_pack $path_to_tmp_project -part $::env(VORTEX_DEVICE_PART)")]
    records, diffs = [], []
    for name, old, new in changes:
        path = folder / name
        original = path.read_text(encoding="utf-8")
        if original.count(old) != 1:
            raise ValueError("build patch anchor mismatch: " + name)
        before = digest(path)
        updated = original.replace(old, new)
        path.write_bytes(updated.encode("utf-8"))
        records.append(dict(path=name, before_sha256=before, after_sha256=digest(path)))
        diffs.extend(difflib.unified_diff(original.splitlines(True), updated.splitlines(True),
                                        fromfile="pinned/" + name, tofile=flow + "/" + name))
    data = json.dumps(dict(build_flow=flow, patches=records), sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
    (work / "flow_patch.json").write_bytes(data)
    (work / "flow.patch").write_bytes("".join(diffs).encode("utf-8"))
    return folder, dict(build_flow=flow, flow_sha256=hashlib.sha256(data).hexdigest())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="extracted u280-rtl-input directory")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--stage", choices=("inspect", "xo", "link"), default="inspect")
    parser.add_argument("--build-flow", choices=("pinned", "ip-ooc-v1"), default="pinned")
    parser.add_argument("--xo-run", type=Path, help="successful XO run to use for link")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", args.run_id):
        parser.error("unsafe run id")
    if args.stage == "link" and args.xo_run is None:
        parser.error("link requires --xo-run")
    import pwd  # Linux execution only; input/lineage validators are portable.
    source = args.input.resolve()
    account_home = Path(pwd.getpwuid(os.getuid()).pw_dir).resolve()
    root = account_home / "vortex-u280-builds"
    if root.is_symlink():
        raise ValueError("build root cannot be a symlink")
    root.mkdir(mode=0o700, exist_ok=True)
    work = root / args.run_id
    work.mkdir(mode=0o700, exist_ok=False)
    result = dict(schema_version="u280-prepared-build-v2", argv=sys.argv,
        started_at=datetime.datetime.now(datetime.timezone.utc).isoformat(), stage=args.stage,
        status="RUNNING", commands=[], board_load="NOT_RUN", host_configuration="NOT_RUN",
        limits=dict(cpu_affinity=sorted(os.sched_getaffinity(0))[:2], nice_increment=10,
                    vivado_max_threads=2, wall_seconds=900 if args.stage == "xo" else 21600,
                    ram_hard_limit="NOT_ENFORCED; confirm shared-host resource rules before link"))
    shutil.copy2(__file__, work / "build_prepared.py")

    def command(label, argv, cwd, timeout):
        start = time.monotonic()
        rec = dict(label=label, argv=argv, cwd=str(cwd), timeout_seconds=timeout, timed_out=False)
        env = dict(os.environ, OMP_NUM_THREADS="2", OPENBLAS_NUM_THREADS="2", MKL_NUM_THREADS="2",
                   TOOL_DIR=str(flow_root / "scripts"), KERNEL_FREQ=str(cfg["kernel_frequency_mhz"]),
                   VORTEX_DEVICE_PART=cfg["device_part"],
                   IMPL_MAX_THREADS="2", MODULE_INTERFACE_CHECK="error", TMPDIR=str(work / "tmp"))
        def limits():
            os.nice(10)
            os.sched_setaffinity(0, result["limits"]["cpu_affinity"])
        rec["exit_code"] = None
        with (work / (label + ".stdout")).open("xb") as out, (work / (label + ".stderr")).open("xb") as err:
            try:
                process = subprocess.Popen(argv, cwd=str(cwd), env=env, stdout=out, stderr=err,
                    preexec_fn=limits, start_new_session=True)
                try:
                    process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    rec["timed_out"] = True
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                rec["exit_code"] = process.returncode
            except OSError as exc:
                rec["launch_error"] = repr(exc)
        rec.update(elapsed_seconds=round(time.monotonic() - start, 3))
        for stream in ("stdout", "stderr"):
            rec[stream + "_sha256"] = digest(work / (label + "." + stream))
        result["commands"].append(rec)
        (work / "result.json").write_text(json.dumps(result, indent=2) + "\n")
        if rec["exit_code"] != 0 or rec["timed_out"]:
            raise RuntimeError(label + " failed; see raw logs")

    setup = ". /apps/Xilinx2023/Vitis/2023.1/settings64.sh >/dev/null && . /opt/xilinx/xrt/setup.sh >/dev/null && exec "
    def vendor(argv):
        return ["bash", "-c", setup + " ".join(shlex.quote(str(arg)) for arg in argv)]

    try:
        cfg, identity = validate_input(source)
        flow_root, flow_identity = prepare_flow(source, work, args.build_flow)
        identity.update(flow_identity)
        result.update(identity)
        (work / "input_manifest.json").write_bytes((source / "manifest.json").read_bytes())
        (work / "result.json").write_text(json.dumps(result, indent=2) + "\n")
        if args.stage != "inspect":
            previous_xo = validate_xo(args.xo_run, identity) if args.stage == "link" else None
            shutil.copytree(source, work / "input")
            if any(identity[k] != v for k, v in validate_input(work / "input")[1].items()):
                raise ValueError("input changed while copying")
            (work / "out").mkdir()
            (work / "tmp").mkdir()
            command("platform", vendor(["platforminfo", "-p", cfg["platform"]]), work, 60)
            if args.stage == "xo":
                # Brace-quoted Tcl paths cannot contain these metacharacters.
                if any(ch in str(work) for ch in "{}\\\n\r"):
                    raise ValueError("unsupported Tcl work path")
                tcl = "set_param general.maxThreads 2\nset argc 4\nset argv [list {%s} vortex_afu {%s} {%s}]\nsource {%s}\n" % (
                    work / "out/vortex_afu.xo", work / "input/sources.txt", work / "out", flow_root / "xrt/gen_xo.tcl")
                (work / "bounded_xo.tcl").write_text(tcl)
                command("xo", vendor(["vivado", "-mode", "batch", "-notrace", "-source", work / "bounded_xo.tcl",
                    "-log", work / "vivado.log", "-journal", work / "vivado.jou"]), work / "input", 900)
                artifact = work / "out/vortex_afu.xo"
            else:
                shutil.copy2(previous_xo, work / "out/vortex_afu.xo")
                if digest(work / "out/vortex_afu.xo") != digest(previous_xo):
                    raise ValueError("XO changed while copying")
                flags = ["v++", "--link", "--target", "hw", "--platform", cfg["platform"], "--save-temps", "--no_ip_cache",
                    "--vivado.synth.jobs", "2", "--vivado.impl.jobs", "2", "--kernel_frequency", str(cfg["kernel_frequency_mhz"]),
                    "--xp", "vivado_prop:run.impl_1.STEPS.OPT_DESIGN.TCL.PRE=" + str(flow_root / "xrt/pre_opt_hook.tcl"),
                    "--report_level", "2", "--config", str(flow_root / "xrt/vitis.ini"), "--optimize", "3"]
                for connection in cfg["connectivity"]:
                    flags += ["--connectivity.sp", connection]
                flags += ["-o", str(work / "out/vortex_afu.xclbin"), str(work / "out/vortex_afu.xo")]
                command("link", vendor(flags), work / "out", 21600)
                command("clock_check", ["python3", str(work / "input/scripts/xilinx_check_kernel_clock.py"),
                    "--freq", str(cfg["kernel_frequency_mhz"]), "--no-scaling",
                    "--report", str(work / "out/_x/reports/link/imp/impl_1_hw_bb_locked_timing_summary_routed.rpt"),
                    "--new-clk-freq", str(work / "out/_x/link/int/_new_clk_freq")], work, 60)
                artifact = work / "out/vortex_afu.xclbin"
            if not artifact.is_file() or artifact.stat().st_size == 0:
                raise ValueError("missing build artifact")
            if any(identity[k] != v for k, v in validate_input(work / "input", exact=False)[1].items()):
                raise ValueError("packaged source changed during build")
            result["artifact"] = dict(path=str(artifact.relative_to(work)), sha256=digest(artifact), bytes=artifact.stat().st_size)
        result["status"] = "PASS"
    except Exception as exc:
        result.update(status="FAIL", error=repr(exc))
    result.update(exit_code=0 if result["status"] == "PASS" else 1,
                  finished_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
    (work / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(dict(status=result["status"], result=str(work / "result.json"))))
    return result["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
