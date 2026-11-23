"""Recheck D probe captures and the pinned source from disk, without device execution."""
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import struct
import sys

from run_d_guarded_wide import BACKENDS, CASES, IMAGE_SHA, SOURCE, check_trace
from run_native_smoke import PROJECT, sha256
from run_ptx_copy import SIM_LOCK, VORTEX, capture_comparison, read_json, require, write_json
from ptx_module import inspect_vxbin, validate


def audit(run, report):
    lock = read_json(PROJECT / "configs/target_lock.json")
    inventory = PROJECT / lock["evidence"] / "source_manifest.json"
    require(sha256(inventory) == lock["source_manifest_sha256"], "source inventory mismatch")
    entries = read_json(inventory)
    for root in (PROJECT / "upstream/vortex", VORTEX):
        for item in entries:
            require(sha256(root / item["path"]) == item["sha256"], "source differs: " + str(root / item["path"]))
        report["source_checkouts"][str(root)] = len(entries)

    summary = read_json(run / "summary.json")
    require(summary["status"] == "PASS" and summary["exit_code"] == 0, "source run incomplete")
    for path in (run / "implementation").rglob("*"):
        if path.is_file():
            rel = path.relative_to(run / "implementation")
            require(sha256(path) == sha256(PROJECT / rel), "implementation changed: " + str(rel))
    module = run / "module"
    manifest, image = validate(module, SIM_LOCK.read_bytes())
    require(manifest["image_sha256"] == IMAGE_SHA and sha256(SOURCE) == manifest["source_sha256"], "wrong probe")
    pc = inspect_vxbin(image)["entry_pc"]
    ir = read_json(module / "ir.json")
    mapping = read_json(module / "source_map.json")
    require(len(ir["instructions"]) == len(mapping), "source mapping incomplete")
    for ins, mapped in zip(ir["instructions"], mapping):
        report["form_locations"].setdefault(ins["opcode"], []).append(
            dict(ptx_line=ins["source_location"]["line"], cpp_line=mapped["generated_line"]))
    commands = {c["label"]: c for c in summary["commands"]}
    labels = {"prepare", "build", "validate"}
    for case, *_ in CASES:
        labels.update(prefix + "_" + case for prefix in ("host", *BACKENDS))
    require(set(commands) == labels and len(commands) == len(summary["commands"]), "unexpected command set")
    for command in commands.values():
        require(command["returncode"] == 0 and not command["timed_out"] and
                sha256(run / command["log"]) == command["log_sha256"], "command evidence changed")
    report["command_logs_verified"] = len(commands)
    require(sha256(run / "corpus.json") == summary["corpus_sha256"], "corpus manifest mismatch")
    for name, digest in read_json(run / "corpus.json").items():
        require(sha256(run / name) == digest, "input or reference changed: " + name)
    for cid, *_ in CASES:
        root = run / cid
        case = read_json(root / "case.json")
        for role in ("x", "z", "audit"):
            filename = cid + "_" + role + ".bin"
            expected = (root / "expected" / filename).read_bytes()
            require(all((root / b / "actual" / filename).read_bytes() == expected for b in BACKENDS),
                    "cross-backend array mismatch: " + filename)
        for backend in BACKENDS:
            stage = root / backend
            raw = (run / commands[backend + "_" + cid]["log"]).read_text(encoding="utf-8")
            comparison = capture_comparison(root, stage / "actual", raw, case, ir, pc)
            require(comparison["status"] == "PASS" and sha256(stage / "kernel.vxbin") == IMAGE_SHA,
                    "capture or staged image mismatch")
            archived = read_json(stage / "comparison.json")
            ptr = comparison["device_addresses"]
            payload = struct.pack("<QQQIII4x", ptr["x"], ptr["z"], ptr["audit"],
                                  case["n"], case["skip_lane"], case["bias"])
            comparison["fixed_layout_match"] = (stage / "actual" / (cid + "_params.bin")).read_bytes() == payload
            require(comparison["fixed_layout_match"] and archived == comparison, "parameter layout or comparison changed")
            if backend != "xrtsim":
                trace = check_trace(raw, backend, case, comparison["device_addresses"])
                archived_trace = read_json(stage / "trace.json")
                # JSON stores the per-lane tuples as lists.
                require(trace["status"] == "PASS" and json.loads(json.dumps(trace)) == archived_trace,
                        "raw LSU trace mismatch")
                report["lsu_totals"][backend].update(trace["counts"])
            report["captures"][backend] += 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"d-guarded-wide-review-[A-Za-z0-9_-]{1,64}", args.run_id):
        parser.error("supply a fresh d-guarded-wide-review-* run id")
    output = PROJECT / "results" / args.run_id
    output.mkdir()
    report = dict(scope="D author offline replay and fixed-source inventory", run=str(args.run),
                  argv=sys.argv, source_checkouts={}, form_locations={}, captures=Counter(),
                  lsu_totals={b: Counter() for b in ("simx", "rtlsim")})
    try:
        audit(args.run.resolve(), report)
        report.update(status="PASS", exit_code=0)
    except (ValueError, RuntimeError, OSError, KeyError) as error:
        report.update(status="FAIL", exit_code=1, error=str(error))
    write_json(output / "result.json", report)
    print(report["status"], output, report.get("error", ""))
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
