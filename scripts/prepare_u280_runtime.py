"""Prepare a relocatable, source-bound 200 MHz host runtime package in Linux."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import time

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path("/opt/vortex-ab/sources/vortex-7fe19369587c-v1")
D8 = ROOT / "results/ab-d8-u280-source-20261109-v1"
D10 = ROOT / "results/u280-link-20261109-155638-456/returned/build/result.json"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def flag_map(text):
    values = {}
    for flag in shlex.split(text):
        if not flag.startswith("-D"):
            raise ValueError("unexpected non-define compiler flag")
        key, _, value = flag[2:].partition("=")
        if key in values and values[key] != value:
            raise ValueError("conflicting definition: " + key)
        values[key] = value
    return values


def check_binding(before, after):
    old, new = flag_map(before), flag_map(after)
    changed = {k: [old.get(k), new.get(k)] for k in set(old) | set(new) if old.get(k) != new.get(k)}
    if changed != {"VX_CFG_PLATFORM_CLOCK_RATE": ["400", "200"]}:
        raise ValueError("runtime binding must change only platform clock metadata")
    expected = dict(VX_CFG_XLEN="64", VX_CFG_NUM_CLUSTERS="1", VX_CFG_NUM_CORES="1",
                    VX_CFG_NUM_WARPS="8", VX_CFG_NUM_THREADS="4", VX_CFG_PLATFORM_MEMORY_NUM_BANKS="32",
                    VX_CFG_PLATFORM_MEMORY_ADDR_WIDTH="33")
    if any(new.get(k) != v for k, v in expected.items()):
        raise ValueError("runtime hardware configuration mismatch")
    return changed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", args.run_id):
        parser.error("unsafe run id")
    output = ROOT / "results" / args.run_id
    output.mkdir(exist_ok=False)
    work = Path("/opt/vortex-ab/builds") / args.run_id
    work.mkdir(exist_ok=False)
    package = work / "package"
    package.mkdir()
    build = package / "build"
    build.mkdir()
    result = dict(schema_version="u280-runtime-preparation-v1", argv=sys.argv, status="RUNNING", commands=[],
                  scope="source identity, host-runtime packaging and Ubuntu stub compilation only",
                  server_runtime="NOT_RUN", xrt_backend="NOT_RUN", board_execution="NOT_RUN", ptx_device="NOT_RUN")

    def command(label, argv, cwd):
        argv = [str(v) for v in argv]
        begin = time.monotonic()
        with (output / (label + ".stdout")).open("xb") as out, (output / (label + ".stderr")).open("xb") as err:
            p = subprocess.run(argv, cwd=str(cwd), stdout=out, stderr=err, timeout=180,
                               env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        result["commands"].append(dict(label=label, argv=argv, cwd=str(cwd), exit_code=p.returncode,
            elapsed_seconds=round(time.monotonic() - begin, 3),
            stdout_sha256=sha(output / (label + ".stdout")), stderr_sha256=sha(output / (label + ".stderr"))))
        if p.returncode:
            raise ValueError(label + " failed")
        return (output / (label + ".stdout")).read_text()

    try:
        lock_path = ROOT / "configs/candidates/u280-hbm32-v1/target_lock.json"
        lock = json.loads(lock_path.read_text())
        inventory = ROOT / lock["evidence"] / "source_manifest.json"
        if sha(inventory) != lock["source_manifest_sha256"]:
            raise ValueError("source inventory changed")
        entries = json.loads(inventory.read_text())
        for item in entries:
            if sha(SOURCE / item["path"]) != item["sha256"]:
                raise ValueError("fixed source changed: " + item["path"])
        result["source_files_verified"] = len(entries)
        command("configure", ["bash", SOURCE / "configure", "--xlen=64", "--osversion=centos/7"], build)
        source_flags = ["-D" + line[len("+define+"):] for line in
                        (D8 / "candidate_merged/sources.txt").read_text().splitlines() if line.startswith("+define+")]
        flags = command("resolve", [sys.executable, "-B", SOURCE / "ci/gen_config.py",
            "--config=" + str(SOURCE / "VX_config.toml"), "--format=cflags",
            "--cflags=" + " ".join(source_flags + ["-DVX_CFG_PLATFORM_CLOCK_RATE=200"])], build).strip()
        changed = check_binding((D8 / "candidate_merged/resolved_config.cflags").read_text(), flags)
        source_dir = package / "source"
        selected = []
        for item in entries:
            name = item["path"]
            if (name.startswith(("sw/common/", "sw/runtime/", "sw/kernel/include/")) or
                    name in ("VX_config.toml", "VX_types.toml", "VERSION", "config.mk.in", "configure", "ci/gen_config.py")):
                path = source_dir / name
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(SOURCE / name, path)
                selected.append(item)
        # Only the generated make scaffolding and headers required by host runtime travel.
        handoff = work / "handoff"
        handoff.mkdir()
        shutil.copytree(source_dir, handoff / "source")
        for name in ("config.mk", "sw/runtime/common.mk", "sw/runtime/stub/Makefile", "sw/runtime/xrt/Makefile"):
            dst = handoff / "build" / name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(build / name, dst)
        for path in (build / "sw").glob("*.h"):
            shutil.copy2(path, handoff / "build/sw" / path.name)
        (handoff / "resolved.cflags").write_text(flags + "\n")
        shutil.copy2(lock_path, handoff / "target_lock.json")
        shutil.copy2(D10, handoff / "fpga_build_result.json")
        shutil.copy2(ROOT / "environment/u280-fpga/build_runtime.py", handoff / "build_runtime.py")
        binding = dict(schema_version="u280-runtime200-binding-v1", frozen=False,
            source_commit=lock["vortex"]["commit"], target_lock_sha256=sha(lock_path),
            fpga_build_result_sha256=sha(D10), xclbin=json.loads(D10.read_text())["artifact"],
            resolved_cflags_sha256=sha(handoff / "resolved.cflags"), changed_definitions=changed,
            note="Runtime clock metadata binding only; no RTL, ABI, PTX profile, or existing target lock changes.",
            source_files=selected)
        (handoff / "binding.json").write_text(json.dumps(binding, indent=2) + "\n")
        manifest = [dict(path=p.relative_to(handoff).as_posix(), bytes=p.stat().st_size, sha256=sha(p))
                    for p in sorted(handoff.rglob("*")) if p.is_file()]
        (handoff / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        archive = output / "u280-runtime200-input.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            for path in sorted(handoff.rglob("*")):
                if path.is_file():
                    tar.add(path, arcname="u280-runtime200-input/" + path.relative_to(handoff).as_posix(), recursive=False)
        result.update(package=dict(path=archive.name, sha256=sha(archive), bytes=archive.stat().st_size),
                      binding=binding, package_files=len(manifest), source_files_packaged=len(selected))
        command("local_stub", [sys.executable, "-B", handoff / "build_runtime.py", "--input", handoff,
            "--output", work / "local-check", "--cxx", "/usr/bin/g++", "--stub-only"], work)
        shutil.copytree(work / "local-check", output / "local-check")
        for name in ("binding.json", "manifest.json", "resolved.cflags"):
            shutil.copy2(handoff / name, output / name)
        result.update(status="PASS", ubuntu_stub="PASS", server_runtime="NOT_RUN")
    except Exception as exc:
        result.update(status="FAIL", error=repr(exc))
    result["exit_code"] = 0 if result["status"] == "PASS" else 1
    shutil.copy2(__file__, output / Path(__file__).name)
    (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(dict(status=result["status"], error=result.get("error"), result=str(output / "result.json"))))
    return result["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
