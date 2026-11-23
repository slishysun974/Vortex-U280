"""Rebuild the two accepted V03 probe sources for the fixed U280 target."""

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import sys

from check_c_v03_receipt import CORPUS_SHA, DEFAULT_CORPUS, DELIVERIES, TOOLCHAIN, corpus
from ptx_module import BOARD_LOCK_SHA, validate
from run_native_smoke import PROJECT, Recorder, sha256, utc_now
from run_ptx_copy import BOARD_LOCK, SIM_LOCK, VORTEX, read_json, require, run_stage


def build_modules(run, rec):
    frozen = run / "corpus"
    corpus(DEFAULT_CORPUS)
    shutil.copytree(DEFAULT_CORPUS, frozen)
    manifest = corpus(frozen)
    board_lock = BOARD_LOCK.read_bytes()
    sim_lock = SIM_LOCK.read_bytes()
    hardware = BOARD_LOCK.with_name("fpga.json")
    require(sha256(BOARD_LOCK) == BOARD_LOCK_SHA, "wrong U280 lock")
    rec.summary.update(corpus_sha256=CORPUS_SHA, board_lock_sha256=BOARD_LOCK_SHA,
                       board_hardware_sha256=sha256(hardware))

    builder = [sys.executable, "-B", PROJECT / "scripts/ptx_module.py"]
    for entry, (delivery, delivery_sha) in DELIVERIES.items():
        source = frozen / "sources" / (entry + ".ptx")
        sim = PROJECT / "results" / delivery / "module"
        require(sha256(sim / "manifest.json") == delivery_sha, "D model delivery changed: " + entry)
        model, model_image = validate(sim, sim_lock)
        require(model["source_sha256"] == manifest["files"]["sources/" + source.name],
                "D and C sources differ: " + entry)

        module = run / "modules" / entry
        for action, arguments in (
                ("prepare", [source, "--output", module, "--hardware", hardware]),
                ("build", [module, "--vortex-source", VORTEX, "--tooldir", TOOLCHAIN,
                           "--build-root", PROJECT / "build" / run.name / entry]),
                ("validate", [module])):
            run_stage(rec, action + "_" + entry, builder + [action, *arguments, "--target-lock", BOARD_LOCK],
                      run, 360)

        board, board_image = validate(module, board_lock)
        require(board["entry"] == model["entry"] == entry and board_image == model_image,
                "U280 and model images differ: " + entry)
        for field in ("source_sha256", "profile", "abi_version", "params", "params_size", "params_align",
                      "logical_launch_model"):
            require(board[field] == model[field], "U280 and model module field differs: " + field)
        frontend = read_json(module / "frontend_manifest.json")
        require(frontend["validation_revision"] == "p0-static-v2" and
                frontend["compiler_sha256"] == sha256(PROJECT / "scripts/ptx_frontend_v12.py"),
                "unexpected frontend identity")
        command, output = rec.command("reject_model_lock_" + entry,
            builder + ["validate", module, "--target-lock", SIM_LOCK], run)
        require(command["returncode"] == 1 and not command["timed_out"] and
                json.loads(output)["error"]["code"] == "E_TARGET_MISMATCH", "wrong lock was accepted")
        command["expected_returncode"] = 1
        rec.summary["modules"][entry] = dict(
            status="PASS", source_sha256=board["source_sha256"], image_sha256=board["image_sha256"],
            manifest_sha256=sha256(module / "manifest.json"), model_manifest_sha256=delivery_sha,
            model_image_byte_identical=True, wrong_lock="E_TARGET_MISMATCH")
        rec.save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"c-v03-u280-prepare-[A-Za-z0-9_-]{1,64}", args.run_id):
        parser.error("choose a fresh c-v03-u280-prepare-* run ID")
    run = PROJECT / "results" / args.run_id
    run.mkdir()
    report = dict(run_id=run.name, argv=sys.argv, started_at=utc_now(), status="RUNNING", commands=[],
                  scope="U280-target probe compilation and offline validation", modules={},
                  physical_u280="NOT_RUN", independent_acceptance="NOT_RUN", timing7="OPEN")
    rec = Recorder(run, report, dict(os.environ))
    try:
        for name in (Path(__file__).name, "ptx_module.py", "ptx_frontend_v12.py"):
            src = PROJECT / "scripts" / name
            dest = run / "implementation" / name
            dest.parent.mkdir(exist_ok=True)
            shutil.copyfile(src, dest)
        report["implementation"] = {p.name: sha256(p) for p in (run / "implementation").iterdir()}
        build_modules(run, rec)
        require(all(sha256(PROJECT / "scripts" / name) == digest
                    for name, digest in report["implementation"].items()), "implementation changed during build")
        report.update(status="PASS", exit_code=0)
    except (OSError, ValueError, RuntimeError) as error:
        report.update(status="FAIL", exit_code=1, error=str(error))
    report["finished_at"] = utc_now()
    rec.save()
    print(report["status"], run, report.get("error", ""))
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
