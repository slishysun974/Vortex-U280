"""Build the formal same-predicate modules for local D5 regression."""

import argparse
import os
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(PROJECT / name) for name in (
    "scripts", "experiments/ptx-aligned-production")]

from build_ae_v03 import frozen_manifest
from check_c_v03_receipt import FORMS, TOOLCHAIN, WIDE
from ptx_module import ALIGNED_PARAMETER_ACCESS, SAME_PREDICATE_LOWERING, validate
from run_native_smoke import Recorder, sha256, utc_now
from run_ptx_copy import SIM_LOCK, VORTEX, read_json, require, run_stage
from validate import FROZEN, OPS, performance_bundles


FORMAL = PROJECT / "results/local-ptx-aligned-production-build-20261121-v1"
ISOLATED = PROJECT / "results/local-ptx-same-predicate-build-20261121-v1"
PREPARE_FLAGS = ("--device-parameter-access", ALIGNED_PARAMETER_ACCESS, "--predicate-lowering", SAME_PREDICATE_LOWERING)


def build(out, rec):
    frozen_manifest(FROZEN)
    for _ in performance_bundles():
        pass  # Verify all kit bytes and their build receipts before using the baselines.
    formal = read_json(FORMAL / "summary.json")
    isolated = read_json(ISOLATED / "summary.json")
    require(all(r["status"] == "PASS" and r["exit_code"] == 0 for r in (formal, isolated)),
            "prior aligned and isolated builds must have passed")
    rec.summary.update(lock_sha256=sha256(SIM_LOCK), formal_sha256=sha256(FORMAL / "summary.json"),
                       isolated_sha256=sha256(ISOLATED / "summary.json"), modules={})
    cli = [sys.executable, "-B", PROJECT / "scripts/ptx_module.py"]
    for name in (*OPS, FORMS, WIDE):
        origin = FORMAL / "modules" / name
        source = origin / "source.ptx" if name in OPS else FROZEN / "sources" / (name + ".ptx")
        path = out / "modules" / name
        base, _ = validate(origin, SIM_LOCK.read_bytes())
        require(base["image_sha256"] == formal["modules"][name]["image"] and
                base["source_sha256"] == sha256(source), "formal input identity differs")
        for action, args in (
                ("prepare", [source, "--output", path, "--hardware", SIM_LOCK.with_name("native_smoke.json"), *PREPARE_FLAGS]),
                ("build", [path, "--vortex-source", VORTEX, "--tooldir", TOOLCHAIN,
                           "--build-root", PROJECT / "build" / out.name / name]),
                ("validate", [path])):
            run_stage(rec, f"{action}_{name}", cli + [action, *args, "--target-lock", SIM_LOCK], out, 420)
        merged, _ = validate(path, SIM_LOCK.read_bytes())
        require(merged["predicate_lowering"] == SAME_PREDICATE_LOWERING and
                all((path / artifact).read_bytes() == (origin / artifact).read_bytes() for artifact in
                    ("source.ptx", "ir.json", "kernel.cpp", "Makefile", "abi.json", "profile.json")),
                "source, IR, ABI or wrapper differed from the aligned baseline")
        if name in OPS:
            experiment = isolated["operators"][name]
            require(base["image_sha256"] == experiment["aligned_image"] and
                    merged["image_sha256"] == experiment["merged_image"] and
                    (path / "kernel_body.hpp").read_bytes() ==
                    (ISOLATED / name / "merged/kernel_body.hpp").read_bytes(),
                    "formal lowering differs from the isolated control experiment: " + name)
        rec.summary["modules"][name] = dict(aligned_image=base["image_sha256"], merged_image=merged["image_sha256"],
            source_sha256=sha256(source), manifest_sha256=sha256(path / "manifest.json"),
            source_map_sha256=sha256(path / "source_map.json"), frontend=read_json(path / "frontend_manifest.json")["compiler_id"])
        rec.save()


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()
    out = args.output.resolve()
    require(out.parent == PROJECT / "results" and out.name.startswith("local-ptx-same-predicate-production-build-"),
            "choose a fresh formal build run")
    out.mkdir()
    report = dict(status="RUNNING", commands=[], argv=[sys.executable, "-B", *sys.argv],
                  started_at=utc_now(), board_execution="NOT_RUN", afu_execution="NOT_RUN")
    rec = Recorder(out, report, dict(os.environ))
    try:
        build(out, rec)
        report.update(status="PASS", exit_code=0)
    except Exception as error:
        report.update(status="FAIL", exit_code=1, error=str(error))
    report["finished_at"] = utc_now()
    rec.save()
    print(report["status"], out, report.get("error", ""))
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
