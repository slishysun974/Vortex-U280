"""Reopen and verify the offline U280 pair as distributed."""

import argparse
import ast
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import tarfile
import tempfile

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "scripts"))

from run_native_smoke import Recorder, sha256, utc_now
from run_ptx_copy import VORTEX, read_json, require, run_stage


def execute(out, rec, source):
    receipt = read_json(source / "summary.json")
    require(receipt["status"] == "PASS" and receipt["exit_code"] == 0 and receipt["board_execution"] == "NOT_RUN"
            and receipt["formal_aligned_load"] == "BLOCKED", "offline preparation did not pass")
    expected_rejections = {"reject_board_aligned_prepare", "reject_d5_module_at_board_lock"}
    require(expected_rejections <= {c["label"] for c in receipt["commands"]}, "missing physical-load negative controls")
    for c in receipt["commands"]:
        require(c["returncode"] == (1 if c["label"] in expected_rejections else 0) and not c["timed_out"] and
                sha256(source / c["log"]) == c["log_sha256"], "preparation command evidence differs")
    archive = source / receipt["archive"]
    require(sha256(archive) == receipt["archive_sha256"], "archive differs from build receipt")
    with tempfile.TemporaryDirectory(prefix="u280-aligned-bundle-") as scratch:
        root = Path(scratch)
        with tarfile.open(archive, "r:gz") as packed:
            seen = set()
            for member in packed:
                name = PurePosixPath(member.name)
                require(name.parts and name.parts[0] == "bundle" and ".." not in name.parts and "\\" not in member.name and
                        name not in seen and (member.isdir() or member.isfile()), "unsafe or repeated archived path")
                seen.add(name)
                if member.isfile():
                    path = root.joinpath(*name.parts)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with packed.extractfile(member) as stream, path.open("xb") as write:
                        shutil.copyfileobj(stream, write)
        bundle = root / "bundle"
        checker = bundle / "verify_bundle.py"
        ast.parse(checker.read_text(encoding="utf-8"), filename=checker.name, feature_version=(3, 6))
        output = run_stage(rec, "reopened_portable_preflight", [sys.executable, "-B", checker, bundle], out, 90)
        verified = json.loads(output)
        require(verified == receipt["bundle"] and len(list(p for p in bundle.rglob("*") if p.is_file())) == receipt["archive_members"],
                "reopened archive differs from original staging receipt")
        changed = bundle / "inputs/copy/1024/expected.bin"
        raw = changed.read_bytes()
        changed.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
        control, output = rec.command("changed_sentinel_rejected", [sys.executable, "-B", checker, bundle], out, 90)
        require(control["returncode"] == 1 and not control["timed_out"] and "bundle member identity differs" in output,
                "changed frozen sentinel was not rejected")
    rec.summary.update(archive=str(archive.relative_to(PROJECT)), archive_sha256=sha256(archive), verified=verified,
                       python36_verifier_syntax="PASS", changed_sentinel="PASS", physical_vm="NOT_RUN",
                       physical_staging_probe="NOT_RUN", xrt_host_probe_compile="NOT_RUN",
                       preparation_sha256=sha256(source / "summary.json"))
    rec.env["VORTEX_SOURCE"] = str(VORTEX)
    output = run_stage(rec, "runner_unittest", [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-v"],
                       PROJECT, 360)
    ran = re.search(r"Ran (\d+) tests?", output)
    skipped = re.search(r"^OK \(skipped=(\d+)\)", output, re.M)
    require(ran, "missing unittest total")
    rec.summary["runner_unittest"] = dict(total=int(ran[1]), skipped=int(skipped[1]) if skipped else 0, exit_code=0)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--bundle-run", type=Path, required=True)
    cli.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()
    out = args.output.resolve()
    require(out.parent == PROJECT / "results" and out.name.startswith("u280-aligned-predicate-review-"), "choose a fresh offline review")
    out.mkdir()
    report = dict(status="RUNNING", commands=[], argv=[sys.executable, "-B", *sys.argv], started_at=utc_now(),
                  board_execution="NOT_RUN", formal_aligned_load="BLOCKED")
    rec = Recorder(out, report, dict(os.environ))
    try:
        execute(out, rec, args.bundle_run.resolve())
        report.update(status="PASS", exit_code=0)
    except Exception as error:
        report.update(status="FAIL", exit_code=1, error=str(error))
    report["finished_at"] = utc_now()
    rec.save()
    print(report["status"], out, report.get("error", ""))
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
