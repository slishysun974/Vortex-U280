"""Preprocess the pinned U280 RTL in isolated Linux builds; no FPGA tools or devices."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import time

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "configs/candidates/u280-hbm32-v1"
SOURCE = Path("/opt/vortex-ab/sources/vortex-7fe19369587c-v1")
TOOLS = Path("/opt/vortex-ab/toolchains/8c64cf921d3c6c456e80f00d24482d0aa2153a82-rtlsim-d3-v1")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ports(text):
    # Only the top declaration, before instances can repeat the same names.
    declaration = text.split(");", 1)[0]
    return sorted(set(re.findall(r"\bm_axi_mem_(\d+)_awvalid\b", declaration)), key=int)


def connectivity_ports(text):
    return sorted(set(re.findall(r"vortex_afu_1\.m_axi_mem_(\d+):", text)), key=int)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", args.run_id):
        parser.error("unsafe run id")
    output = ROOT / "results" / args.run_id
    output.mkdir(exist_ok=False)
    (output / "logs").mkdir()
    result = dict(schema_version="u280-source-preflight-v1", argv=sys.argv,
        started_at=datetime.now(timezone.utc).isoformat(), status="RUNNING", commands=[], checks=[],
        scope="pinned-source identity, actual Verilator preprocessing and connectivity consistency only",
        synthesis="NOT_RUN", vivado_elaboration="NOT_RUN", implementation="NOT_RUN",
        board_execution="NOT_RUN", host_memory="NOT_RUN", independent_reproduction="NOT_RUN")
    protected = [ROOT / "configs" / n for n in ("target_lock.json", "target_caps.json", "native_smoke.json")]
    protected += list(PROFILE.glob("*.json"))
    result["config_hashes_before"] = {str(p.relative_to(ROOT)): digest(p) for p in protected}
    cpus = sorted(os.sched_getaffinity(0))[:2]

    def check(name, ok):
        result["checks"].append(dict(name=name, status="PASS" if ok else "FAIL"))
        if not ok:
            raise ValueError(name)

    def command(label, argv, cwd, env=None, timeout=180):
        record = dict(label=label, argv=[str(a) for a in argv], cwd=str(cwd),
            timeout_seconds=timeout, cpu_affinity=cpus, timed_out=False)
        if env is not None:
            record["CONFIGS"] = env.get("CONFIGS", "")
        start = time.monotonic()
        def limits():
            os.sched_setaffinity(0, cpus)
            os.nice(10)
        with (output / "logs" / (label + ".stdout")).open("xb") as out, (output / "logs" / (label + ".stderr")).open("xb") as err:
            process = subprocess.Popen(record["argv"], cwd=cwd, env=env, stdout=out, stderr=err,
                start_new_session=True, preexec_fn=limits)
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                record["timed_out"] = True
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
        record.update(exit_code=process.returncode, elapsed_seconds=round(time.monotonic() - start, 3))
        for stream in ("stdout", "stderr"):
            path = output / "logs" / (label + "." + stream)
            record[stream] = str(path.relative_to(output))
            record[stream + "_sha256"] = digest(path)
        result["commands"].append(record)
        check(label + " exit", process.returncode == 0 and not record["timed_out"])
        return (output / record["stdout"]).read_text()

    try:
        cfg = json.loads((PROFILE / "fpga.json").read_text())
        lock = json.loads((PROFILE / "target_lock.json").read_text())
        check("candidate config identity", digest(PROFILE / "fpga.json") == lock["hardware_config_sha256"])
        check("candidate lock identity", digest(PROFILE / "target_lock.json") == (PROFILE / "target_lock.sha256").read_text().strip())
        manifest = ROOT / lock["evidence"] / "source_manifest.json"
        check("frozen manifest identity", digest(manifest) == lock["source_manifest_sha256"])
        entries = json.loads(manifest.read_text())
        mismatches = [item["path"] for item in entries if digest(SOURCE / item["path"]) != item["sha256"]]
        result["source_identity"] = dict(files=len(entries), mismatches=mismatches, commit=lock["vortex"]["commit"])
        check("all pinned source hashes", not mismatches)
        check("fixed Verilator binary", digest(TOOLS / "verilator/bin/verilator_bin") == lock["simulators"]["verilator"]["binary_sha256"])
        command("verilator_version", [TOOLS / "verilator/bin/verilator", "--version"], ROOT)
        result["variants"] = {}
        for variant in ("upstream_unmerged", "candidate_merged"):
            build = Path("/opt/vortex-ab/builds") / (args.run_id + "-" + variant)
            build.mkdir(exist_ok=False)
            command(variant + "_configure", ["bash", SOURCE / "configure", "--xlen=64", "--tooldir=" + str(TOOLS)], build)
            flags = ["-D" + k + ("" if v is True else "=" + str(v)) for k, v in cfg["defines"].items()
                     if variant == "candidate_merged" or k != "PLATFORM_MERGED_MEMORY_INTERFACE"]
            env = dict(os.environ, CONFIGS=" ".join(flags), PYTHONDONTWRITEBYTECODE="1")
            # These two values are explicit offline selectors, not a local platforminfo result.
            make = ["make", "-s", "-C", str(build / "hw/syn/xilinx/xrt"),
                "DEV_ARCH=virtexuplus", "CPU_TYPE=x86", "PLATFORM=" + cfg["platform"], "TARGET=hw",
                "PREFIX=prepared", "JOBS=2", "MAX_JOBS=2", "KERNEL_FREQ=200", "FREQ_SCALING=0",
                "IMPL_MAX_THREADS=2", "XILINX_VITIS=/apps/Xilinx2023/Vitis/2023.1",
                "XILINX_VIVADO=/apps/Xilinx2023/Vivado/2023.1"]
            command(variant + "_sources", make + ["gen-sources"], build, env, 300)
            plan = command(variant + "_link_plan", make + ["-n", "gen-bin"], build, env)
            generated = build / "hw/syn/xilinx/xrt" / ("prepared_" + Path(cfg["platform"]).stem + "_hw")
            top = (generated / "src/vortex_afu.v").read_text()
            actual, linked = ports(top), connectivity_ports(plan)
            check(variant + " nonempty top ports", bool(actual))
            contract = dict(status="PASS" if actual == linked else "FAIL", memory_ports=actual,
                explicitly_connected_memory_ports=linked,
                unconnected_memory_ports=sorted(set(actual) - set(linked), key=int),
                host_master_present=bool(re.search(r"\bm_axi_host_awvalid\b", top.split(");", 1)[0])),
                host_connected="vortex_afu_1.m_axi_host:HOST[0]" in plan,
                inference="source/interface mismatch only; no v++ link failure claimed")
            destination = output / variant
            destination.mkdir()
            shutil.copy2(generated / "src/vortex_afu.v", destination / "vortex_afu.v")
            shutil.copy2(generated / "sources.txt", destination / "sources.txt")
            filelist = (generated / "sources.txt").read_text()
            cflags = ["-D" + line[len("+define+"):] for line in filelist.splitlines() if line.startswith("+define+")]
            resolved = command(variant + "_config", ["python3", build / "ci/gen_config.py",
                "--config=" + str(SOURCE / "VX_config.toml"), "--cflags=" + " ".join(cflags), "--format=cflags"], build, env)
            (destination / "resolved_config.cflags").write_text(resolved)
            result["variants"][variant] = dict(build=str(build), generated=str(generated), contract=contract,
                generated_files=[dict(path=str(p.relative_to(generated)), sha256=digest(p), bytes=p.stat().st_size)
                    for p in sorted(generated.rglob("*")) if p.is_file()])
            if variant == "upstream_unmerged":
                check("negative fixture detects 31 unconnected masters", actual == [str(i) for i in range(32)]
                    and linked == ["0"] and contract["status"] == "FAIL")
            else:
                check("candidate memory and HOST connectivity", actual == linked == ["0"]
                    and contract["host_master_present"] and contract["host_connected"])
                # Relocatable RTL handoff: rewrite only generated absolute filelist paths.
                package = output / "package"
                package.mkdir()
                shutil.copytree(generated / "src", package / "src")
                relocated = filelist.replace(str(generated) + "/", "./")
                check("filelist relocation complete", not re.search(r"(?:^|\+incdir\+)/", relocated, re.M))
                (package / "sources.txt").write_text(relocated)
                shutil.copytree(SOURCE / "hw/scripts", package / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
                shutil.copytree(SOURCE / "hw/syn/xilinx/xrt", package / "xrt")
                for name in ("fpga.json", "target_lock.json", "target_lock.sha256"):
                    shutil.copy2(PROFILE / name, package / name)
                package_files = [dict(path=str(p.relative_to(package)), sha256=digest(p), bytes=p.stat().st_size)
                    for p in sorted(package.rglob("*")) if p.is_file()]
                (package / "manifest.json").write_text(json.dumps(package_files, indent=2) + "\n")
                with tarfile.open(output / "u280-rtl-input.tar.gz", "w:gz") as archive:
                    archive.add(package, arcname="u280-rtl-input")
                result["rtl_package"] = dict(path="u280-rtl-input.tar.gz", sha256=digest(output / "u280-rtl-input.tar.gz"),
                    files=len(package_files), scope="preprocessed input only; no xo or xclbin")
        check("source identity unchanged after preparation", all(digest(SOURCE / item["path"]) == item["sha256"] for item in entries))
        result["status"] = "PASS"
    except Exception as exc:
        result.update(status="FAIL", error=repr(exc))
    result["config_hashes_after"] = {str(p.relative_to(ROOT)): digest(p) for p in protected}
    if result["config_hashes_before"] != result["config_hashes_after"]:
        result.update(status="FAIL", error="configuration changed during run")
    result["finished_at"] = datetime.now(timezone.utc).isoformat()
    result["exit_code"] = 0 if result["status"] == "PASS" else 1
    shutil.copy2(__file__, output / Path(__file__).name)
    (output / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: result[k] for k in ("status", "exit_code")}))
    return result["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
