"""Recheck NOXRT alignment, formal v1.4 regression, and isolated LSU captures."""

import argparse
from pathlib import Path
import re
import sys

from afu_contract import (BACKEND, FIXED_BINDING, FIXED_SHA, PROJECT, SIM_LOCK, VORTEX, Recorder, check_binding,
                          clean_env, read_json, require, run_stage, sha256, utc_now)
from alignment import verified_alignment
from model import P0_COUNT, receipt, workloads_from_kits
from ptx_module import SAME_PREDICATE_LOWERING, validate
from ptx_runtime import ALIGNED_PARAMETER_BINDINGS, ALIGNED_PARAMETER_BINDINGS_REVISION
from u280_perf_pair import ABI, GUARD, payload_bytes
from check import check_regressions
from review import check_arrays, successful


def host_checks(rec):
    rec.env["VORTEX_SOURCE"] = str(VORTEX)
    text = run_stage(rec, "runner_unittest", [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-v"],
                     PROJECT, 360)
    count = re.search(r"Ran (\d+) tests?", text)
    skipped = re.search(r"^OK \(skipped=(\d+)\)", text, re.M)
    require(count, "missing unit test total")
    rec.summary["runner_unittest"] = dict(total=int(count[1]), skipped=int(skipped[1]) if skipped else 0, exit_code=0)


def identities(built):
    successful(built)
    modules = receipt(built)
    for name, reference in modules.items():
        path = built / "modules" / name
        manifest, _ = validate(path, SIM_LOCK.read_bytes())
        require(manifest["predicate_lowering"] == SAME_PREDICATE_LOWERING and
                manifest["image_sha256"] == reference["merged_image"] and
                sha256(path / "manifest.json") == reference["manifest_sha256"], "formal module identity differs")
    return modules


def check_originals(root, modules, work):
    folder = root / "original-inputs"
    report = read_json(folder / "summary.json")
    expected_count = len(work)
    require(report["status"] == "PASS" and report["exit_code"] == 0 and len(report["cases"]) == expected_count,
            "original input replay did not pass")
    rows = {(row["operator"], row["n"]): row for row in report["cases"]}
    require(rows.keys() == work.keys(), "wrong original inputs")
    evidence = {}
    for (op, n), (spec, frozen) in work.items():
        path = folder / op / str(n)
        row = rows[op, n]
        require(row == read_json(path / "result.json") and row["status"] == "PASS" and
                row["completion"]["status"] == "COMPLETE" and row["completion"]["backend"] == BACKEND and
                all(row[k] == v for k, v in spec.items()) and row["arrays"] == check_arrays(path, frozen, op) and
                row["image_sha256"] == modules[op]["merged_image"] and row["params_sha256"] == sha256(path / "params.bin") and
                payload_bytes(op, read_json(path / "bases.json"), n) == (path / "params.bin").read_bytes(),
                "original input evidence differed")
        evidence[f"{op}/{n}"] = dict(status="PASS", prefix_guard_words=GUARD,
                                     suffix_and_tail_words=spec["words"] - GUARD - n, readback_sha256=row["arrays"])
    return evidence


def check_trace(root, trace_build, trace_alignment, built, modules, work):
    report = successful(root)
    build_report = successful(trace_build)
    binding = trace_build / "binding/binding.json"
    check_binding(binding, fixed=False)
    proof = verified_alignment(trace_alignment, binding, built)
    require(report["backend"] == BACKEND and report["binding_sha256"] == build_report["binding_sha256"] == sha256(binding)
            and report["trace_alignment_sha256"] == sha256(trace_alignment / "summary.json") and
            report["trace_build_sha256"] == sha256(trace_build / "summary.json") and
            report["build_sha256"] == sha256(built / "summary.json") and len(report["cases"]) == len(work),
            "AFU trace run identity differs")
    rows = {}
    for (op, n), (spec, frozen) in work.items():
        case = root / op / str(n)
        raw = case / "lsu.log.gz"
        item = read_json(case / "summary.json")
        command, = item["commands"]
        req = item["requests"]
        require(item["status"] == req["status"] == "PASS" and item["exit_code"] == command["returncode"] == 0 and
                not command["timed_out"] and sha256(case / command["log"]) == command["log_sha256"] and
                sha256(case / "summary.json") == report["cases"][(case / "summary.json").relative_to(root).as_posix()]["sha256"] and
                item["raw_trace_sha256"] == sha256(raw) and item["image_sha256"] == modules[op]["merged_image"] and
                item["arrays"] == check_arrays(case, frozen, op) and item["params_sha256"] == sha256(case / "params.bin") and
                (case / "params.bin").read_bytes() == payload_bytes(op, read_json(case / "bases.json"), n) and
                req["active_threads"] == n and req["dispatched_warps"] == 8 * spec["grid"] and
                req["active_array_requests"] == n * len(ABI[op][1]) and req["false_predicate_array_requests"] == 0,
                "AFU LSU evidence differs: " + str(case))
        if n % 4:
            tail = req["last_warp"]
            require(req["false_threads"] == 3 and not any(tail[str(i)] for i in range(n, n + 3)) and
                    all(request["lane0_first_mask"] == "1000" for request in tail[str(n-1)]), "AFU tail mask differs")
        rows[f"{op}/{n}"] = dict(requests=req["active_array_requests"], false_threads=req["false_threads"],
                                 false_predicate_array_requests=req["false_predicate_array_requests"], last_warp=req["last_warp"])
    negative = read_json(root / "copy/16381/summary.json")["negative_control"]
    require(negative["status"] == "PASS" and negative["reason"].startswith("false-predicate lane issued array request: index 16381,"),
            "AFU trace false-lane injection did not pass")
    return dict(status="PASS", launches=len(rows), active_array_requests=sum(row["requests"] for row in rows.values()),
                false_predicate_array_requests=0, alignment_probe_launches=proof["probe_launches"], cases=rows,
                build_summary_sha256=sha256(trace_build / "summary.json"), trace_summary_sha256=sha256(root / "summary.json"),
                binding_sha256=sha256(binding), negative_control=negative)


def review(args, report):
    built = args.build.resolve()
    modules = identities(built)
    check_binding(FIXED_BINDING, fixed=True)
    alignment = verified_alignment(args.alignment, FIXED_BINDING, built)
    fixed = successful(args.regress)
    host = successful(args.host)
    require(ALIGNED_PARAMETER_BINDINGS[BACKEND] == FIXED_SHA == fixed["binding_sha256"] and fixed["backend"] == BACKEND and
            fixed["build_sha256"] == sha256(built / "summary.json") and
            fixed["alignment_sha256"] == sha256(args.alignment / "summary.json"), "fixed regression identity differs")
    negative_dir = args.regress / "altered-binding"
    negative = read_json(negative_dir / "result.json")
    require(negative["status"] == "PASS" and negative["error"]["code"] == "E_TARGET_MISMATCH" and
            negative["error"]["phase"] == "load" and negative["binding_sha256"] == sha256(negative_dir / "binding.json") != FIXED_SHA,
            "altered binding negative control differs")
    regs = check_regressions(args.regress, BACKEND, modules)
    require(sum(row["passed"] for row in regs["p0_suites"].values()) == sum(P0_COUNT.values()) == 840,
            "incomplete P0 verification")
    work = {(op, spec["n"]): (spec, frozen) for op, spec, frozen in workloads_from_kits()}
    report.update(binding_acceptance_revision=ALIGNED_PARAMETER_BINDINGS_REVISION, binding_sha256=FIXED_SHA,
                  runtime_sha256=sha256(PROJECT / "scripts/ptx_runtime.py"), build_sha256=sha256(built / "summary.json"),
                  fixed_alignment=dict(status="PASS", launches=alignment["probe_launches"], vm_support=alignment["vm_support"],
                                       observed_bases=sorted({hex(row["a0"]) for row in alignment["probes"].values()}),
                                       capture_sha256=sha256(args.alignment / "capture.json")),
                  regressions=regs, original_inputs=check_originals(args.regress, modules, work),
                  regression_sha256=sha256(args.regress / "summary.json"), altered_binding=negative,
                  runner_unittest=host["runner_unittest"], host_sha256=sha256(args.host / "summary.json"))
    report["trace"] = check_trace(args.trace, args.trace_build, args.trace_alignment, built, modules, work)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("phase", choices=("host", "review"))
    cli.add_argument("--output", type=Path, required=True)
    inputs = ("build", "host", "alignment", "regress", "trace", "trace-build", "trace-alignment")
    for name in inputs:
        cli.add_argument("--" + name, type=Path)
    args = cli.parse_args()
    if args.phase == "review" and not all(getattr(args, name.replace("-", "_")) for name in inputs):
        cli.error("review requires the alignment, build, regression, trace and host receipts")
    out = args.output.resolve()
    require(out.parent == PROJECT / "results" and out.name.startswith("local-ptx-same-predicate-afu-"), "choose a new AFU evidence run")
    out.mkdir()
    report = dict(status="RUNNING", commands=[], argv=[sys.executable, "-B", *sys.argv], started_at=utc_now(),
                  board_execution="NOT_RUN")
    rec = Recorder(out, report, clean_env())
    try:
        if args.phase == "host":
            host_checks(rec)
        else:
            review(args, report)
        report.update(status="PASS", exit_code=0)
    except Exception as error:
        report.update(status="FAIL", exit_code=1, error=str(error))
    report["finished_at"] = utc_now()
    rec.save()
    print(report["status"], out, report.get("error", ""))
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
