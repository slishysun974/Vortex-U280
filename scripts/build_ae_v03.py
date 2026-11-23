"""Build both V03 source files from the sealed A/E corpus under both target locks."""

import argparse
import os
from pathlib import Path
import re
import sys

from check_c_v03_receipt import FORMS, TOOLCHAIN, WIDE
from ptx_module import validate
from run_native_smoke import PROJECT, Recorder, sha256, utc_now
from run_ptx_copy import BOARD_LOCK, SIM_LOCK, VORTEX, read_json, require, run_stage

CORPUS_SHA = "6a6331574453bbdd4118ab60fdb4f4b837527f28a7fed127aa8c8e8faeaaaa07"
SCHEMA = "ae-v03-execution-v1"


def frozen_manifest(path):
    require(sha256(path / "manifest.json") == CORPUS_SHA, "A/E frozen manifest changed")
    value = read_json(path / "manifest.json")
    for name, expected in value["files"].items():
        require(sha256(path / name) == expected, "frozen member differs: " + name)
    return value


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--frozen", type=Path, required=True)
    cli.add_argument("--run-id", required=True)
    args = cli.parse_args()
    require(re.fullmatch(r"ae-v03-build-[A-Za-z0-9_-]{1,48}", args.run_id), "use a fresh ae-v03-build-* ID")
    run = PROJECT / "results" / args.run_id
    run.mkdir()
    report = dict(schema=SCHEMA, status="RUNNING", argv=[sys.executable, "-B", *sys.argv],
                  started_at=utc_now(), commands=[], modules={}, corpus_sha256=CORPUS_SHA, device_execution="NOT_RUN")
    rec = Recorder(run, report, dict(os.environ))
    try:
        manifest = frozen_manifest(args.frozen.resolve())
        freeze = read_json(args.frozen / "freeze.json")
        require(freeze["status"] == "PASS" and freeze["exit_code"] == 0 and freeze["manifest_sha256"] == CORPUS_SHA,
                "missing freeze receipt")
        report["freeze_receipt_sha256"] = sha256(args.frozen / "freeze.json")
        run_stage(rec, "python_version", [sys.executable, "--version"], run)
        exe = [sys.executable, "-B", PROJECT / "scripts/ptx_module.py"]
        for target, lock, hardware in (("sim", SIM_LOCK, SIM_LOCK.with_name("native_smoke.json")),
                                       ("board", BOARD_LOCK, BOARD_LOCK.with_name("fpga.json"))):
            report["modules"][target] = {}
            for entry in (FORMS, WIDE):
                source = args.frozen.resolve() / "sources" / (entry + ".ptx")
                module = run / "modules" / target / entry
                label = target + "_" + entry
                for action, extra in (("prepare", [source, "--output", module, "--hardware", hardware]),
                        ("build", [module, "--vortex-source", VORTEX, "--tooldir", TOOLCHAIN,
                                   "--build-root", PROJECT / "build" / run.name / target / entry]),
                        ("validate", [module])):
                    run_stage(rec, action + "_" + label, exe + [action, *extra, "--target-lock", lock], run, 360)
                descriptor, _ = validate(module, lock.read_bytes())
                require(descriptor["source_sha256"] == manifest["files"]["sources/" + source.name], "module source differs")
                report["modules"][target][entry] = dict(image_sha256=descriptor["image_sha256"],
                                                        manifest_sha256=sha256(module / "manifest.json"))
        for entry in (FORMS, WIDE):
            require(report["modules"]["sim"][entry]["image_sha256"] == report["modules"]["board"][entry]["image_sha256"],
                    "simulation and physical images differ")
        report.update(status="PASS", exit_code=0)
    except Exception as error:
        report.update(status="FAIL", exit_code=1, error=str(error))
    report["finished_at"] = utc_now()
    rec.save()
    print(report["status"], run, report.get("error", ""))
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
