"""Compile equivalent native and PTX integer images with the same pinned device rules."""

import argparse
import os
from pathlib import Path
import re
import shutil
import sys

from check_c_v03_receipt import TOOLCHAIN
from ptx_module import inspect_vxbin, makefile, target, validate
from run_native_smoke import PROJECT, Recorder, sha256, utc_now
from run_ptx_copy import BOARD_LOCK, SIM_LOCK, VORTEX, require, run_stage
from u280_perf_pair import ABI, validate_ptx_layout


def build_pair(run, label, lock, hardware, recorder, operation="vadd", suite=False):
    subdir = Path(label) / operation if suite else Path(label)
    root = PROJECT / "build" / run.name / subdir
    portable = run / subdir / "ptx"
    native = run / subdir / "native"
    log = label + "_" + operation if suite else label
    compiler = [sys.executable, "-B", PROJECT / "scripts/ptx_module.py"]
    run_stage(recorder, log + "_ptx_frontend", compiler + ["prepare", PROJECT / "ptx/samples" / (operation + "_u32.ptx"),
              "--output", portable, "--hardware", hardware, "--target-lock", lock], run, 60)
    run_stage(recorder, log + "_ptx_device_build", compiler + ["build", portable, "--vortex-source", VORTEX,
              "--build-root", root, "--tooldir", TOOLCHAIN, "--target-lock", lock], run, 360)
    ptx, _ = validate(portable, lock.read_bytes())
    validate_ptx_layout(ptx, operation)

    native.mkdir()
    shutil.copyfile(PROJECT / "native" / ("perf_" + operation) / "kernel.cpp", native / "kernel.cpp")
    (native / "Makefile").write_bytes(makefile().replace("VX_HDRS := kernel_body.hpp", "VX_HDRS :=").encode())
    (native / ".depend").write_text("# Device-only build.\n", encoding="utf-8")
    _, defines, _ = target(lock.read_bytes(), hardware.read_bytes())
    config = "CONFIGS=" + " ".join("-D%s=%d" % item for item in sorted(defines.items()))
    run_stage(recorder, log + "_native_device_build", ["make", "-C", native, "ROOT_DIR=" + str(root),
              "VORTEX_HOME=" + str(VORTEX), "XLEN=64", "KERNEL_LIB=vortex2", config, "kernel.vxbin", "kernel.dump"], run, 180)
    inspect_vxbin((native / "kernel.vxbin").read_bytes())
    return dict(lock_sha256=sha256(lock), hardware_sha256=sha256(hardware), modules={
        name: dict(image_sha256=sha256(path / "kernel.vxbin"), source_sha256=sha256(path / source))
        for name, path, source in (("ptx", portable, "source.ptx"), ("native", native, "kernel.cpp"))})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--operators", choices=tuple(ABI), nargs="+", default=["vadd"])
    args = parser.parse_args()
    require(re.fullmatch(r"u280-perf-build-[A-Za-z0-9_-]{1,48}", args.run_id), "invalid build run ID")
    require(len(set(args.operators)) == len(args.operators), "duplicate operator")
    suite = args.operators != ["vadd"]
    run = PROJECT / "results" / args.run_id
    run.mkdir()
    report = dict(status="RUNNING", commands=[], targets={}, scope="paired device compilation", board_execution="NOT_RUN",
                  argv=[sys.executable, "-B", *sys.argv], started_at=utc_now())
    recorder = Recorder(run, report, dict(os.environ))
    try:
        for label, lock, hardware in (("sim", SIM_LOCK, SIM_LOCK.with_name("native_smoke.json")),
                                       ("board", BOARD_LOCK, BOARD_LOCK.with_name("fpga.json"))):
            if suite:
                report["operators"] = args.operators
                report["targets"][label] = dict(workloads={})
                for op in args.operators:
                    report["targets"][label]["workloads"][op] = build_pair(run, label, lock, hardware, recorder, op, True)
            else:
                report["targets"][label] = build_pair(run, label, lock, hardware, recorder)
        for op in args.operators:
            targets = [t["workloads"][op] if suite else t for t in report["targets"].values()]
            require(targets[0]["modules"] == targets[1]["modules"], "model/board images differ: " + op)
        report.update(status="PASS", exit_code=0)
    except Exception as error:
        report.update(status="FAIL", exit_code=1, error=str(error))
    report["finished_at"] = utc_now()
    recorder.save()
    print(report["status"], run, report.get("error", ""))
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
