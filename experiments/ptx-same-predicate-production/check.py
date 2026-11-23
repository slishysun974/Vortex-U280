"""Recheck the formal same-predicate build, model runs, and archived observations."""

import argparse
import gzip
import json
import os
from pathlib import Path
import re
from statistics import median
import struct
import sys

from lsu import TRACE_BINDINGS, analyze_log, data_sites, module_path
from model import (ABI, BACKENDS, BINDINGS, COUNTERS, FORMS, P0_COUNT, PROJECT, ROUTES, SIM_LOCK,
                   TRIALS, Recorder, payload_bytes, read_json, receipt, require, run_stage,
                   sha256, utc_now, workloads_from_kits)

from ae_v03_execute import ROLES, check_bytes
from build_ae_v03 import frozen_manifest
from ptx_module import validate
from run_d_p0_closeout import CASES, compatibility_report
from run_ptx_copy import VORTEX
from validate import FROZEN

sys.path.insert(0, str(PROJECT / "experiments/ptx-same-predicate"))
from review import check_arrays, inject_false_lane, successful


def verify_host(rec):
    output = run_stage(rec, "runner_unittest", [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-v"],
                       PROJECT, 300)
    count = re.search(r"Ran (\d+) tests?", output)
    skipped = re.search(r"^OK \(skipped=(\d+)\)", output, re.M)
    require(count, "no unittest totals")
    rec.summary["runner_unittest"] = dict(total=int(count[1]), skipped=int(skipped[1]) if skipped else 0, exit_code=0)
    rec.summary["archived_modules"] = compatibility_report()


def check_regressions(path, backend, info):
    report = read_json(path / "summary.json")
    for op, total in P0_COUNT.items():
        result = path / ("suite-" + op) / "result.json"
        row = read_json(result)
        require(row["status"] == "PASS" and row["exit_code"] == 0 and row["passed"] == total and
                row["backend"] == backend and len(row["rejections"]) == 19 and row["recovery"]["status"] == "PASS" and
                sha256(result) == report["suites"][op]["sha256"], "P0 suite evidence differs")
    p0_root = path / "p0-forms"
    forms = read_json(p0_root / "summary.json")
    require(forms["status"] == "PASS" and forms["exit_code"] == 0 and set(forms["cases"]) == set(CASES) and
            len(forms["forms"]) == len(forms["rejections"]) == 17 and forms["image_sha256"] == info[FORMS]["merged_image"],
            "P0 form matrix evidence differs")
    for cid, row in forms["cases"].items():
        for role, digest in row["arrays"].items():
            actual = p0_root / cid / (role + ".bin")
            require(sha256(actual) == digest and actual.read_bytes() ==
                    (p0_root / cid / "expected" / f"{cid}_{role}.bin").read_bytes(), "P0 form capture differs")
    corpus = frozen_manifest(FROZEN)
    root = path / "witness"
    witness = read_json(root / "summary.json")
    require(witness["status"] == witness["alias"] == "PASS" and witness["corpus_sha256"] == sha256(FROZEN / "manifest.json") and
            witness["completed"] == [case["id"] for case in corpus["cases"]] and witness["launch_attempts"] == 13 and
            witness["high"] == 5, "V03 receipt differs")
    require(read_json(root / "alias/reservations.json") == dict(device_bases=corpus["alias"], range_bytes=2**33, vm=0),
            "V03 alias reservations differ")
    for source in (FROZEN / "alias").glob("*.bin"):
        require(source.read_bytes() == (root / "alias" / source.name).read_bytes(), "V03 alias bytes differ")
    for index, case in enumerate(corpus["cases"], 1):
        raw = root / case["id"]
        for phase in ("before", "after"):
            check_bytes(raw, FROZEN / case["id"], phase)
        bases = read_json(raw / "reservations.json")
        if case["bases"] is not None:
            require(bases == case["bases"], "V03 high allocation differs")
        roles = ROLES[:2] if case["entry"] == FORMS else ROLES
        pointers = [bases[role] + 4 * case["offsets"][role] for role in roles]
        layout = "<QQI4x" if case["entry"] == FORMS else "<QQQIII4x"
        require((raw / "params.bin").read_bytes() == struct.pack(layout, *pointers, *case["scalars"]) and
                read_json(raw / "event.json") == dict(backend=backend, event_id=index, generation=0, status="COMPLETE"),
                "V03 payload or event differs")
    return dict(p0_suites=report["suites"], form_cases=len(forms["cases"]), form_rejections=len(forms["rejections"]),
                v03_cases=witness["launch_attempts"], v03_high=witness["high"], v03_alias=witness["alias"])


def check_performance(path, backend, info, work):
    perf = path / "performance"
    samples = perf / "samples.jsonl"
    rows = [json.loads(line) for line in samples.read_bytes().splitlines()]
    index = {(r["operator"], r["n"], r["pair"], r["route"]): r for r in rows}
    require(len(index) == len(rows) == len(work) * 2 * TRIALS, "wrong number of paired launches")
    old = read_json(PROJECT / "results/local-ptx-same-predicate-review-20261121-v1/summary.json")
    prior = old["models"][backend]["measure"]["metrics"]
    metrics = {}
    for (op, n), (spec, frozen) in work.items():
        key = f"{op}/{n}"
        folder = perf / op / str(n)
        require((folder / "params.bin").read_bytes() == payload_bytes(op, read_json(folder / "bases.json"), n),
                "paired payload differs")
        values = {route: [] for route in ROUTES}
        for pair in range(TRIALS):
            order = ROUTES if pair % 2 == 0 else ROUTES[::-1]
            for position, route in enumerate(order):
                row = index[op, n, pair, route]
                trial = folder / f"{route}-{pair}"
                delta = {k: row["after"][k] - row["before"][k] for k in COUNTERS}
                require(row["delta"] == delta and row["idle"] == row["before"] and
                        delta["instret"] == prior[key][route]["instret"] and row["position"] == position and
                        all(row[k] == value for k, value in spec.items()) and row["captures"] == check_arrays(trial, frozen, op) and
                        row["image_sha256"] == info[op][route + "_image"] and row["params_sha256"] == sha256(folder / "params.bin"),
                        "paired capture differs: " + str(trial))
                values[route].append(delta)
        stats = {route: {k: median(row[k] for row in values[route]) for k in ("cycles", "instret")} for route in ROUTES}
        metrics[key] = dict(**stats, reduction_pct={k: 100 * (1 - stats["merged"][k] / stats["aligned"][k])
                                                   for k in ("cycles", "instret")},
                            paired_cycle_savings=[a["cycles"] - b["cycles"] for a, b in zip(values["aligned"], values["merged"])])
    return dict(metrics=metrics, samples_sha256=sha256(samples), launches=len(rows))


def check_lsu(path, backend, built, info, work):
    run = successful(path)
    require(run["backend"] == backend and run["binding_sha256"] == sha256(TRACE_BINDINGS / backend / "binding.json") and
            run["build_sha256"] == sha256(built / "summary.json") and len(run["cases"]) == 2 * len(work),
            "DEBUG3 identity differs")
    arrays, mixed, negative = 0, 0, None
    for (op, n), (spec, frozen) in work.items():
        for route in ROUTES:
            case = path / op / str(n) / route
            row = read_json(case / "summary.json")
            command, = row["commands"]
            require(row["status"] == "PASS" and row["exit_code"] == 0 and command["returncode"] == 0 and
                    not command["timed_out"] and sha256(case / command["log"]) == command["log_sha256"],
                    "DEBUG3 command or log differs")
            stored = run["cases"][(case / "summary.json").relative_to(path).as_posix()]
            bases = read_json(case / "bases.json")
            image = module_path(built, op, route) / "kernel.vxbin"
            sites, static = data_sites(image, op)
            proof = row["proof"]
            raw = case / "lsu.log.gz"
            require(stored["sha256"] == sha256(case / "summary.json") and row["raw_trace_sha256"] == sha256(raw) and
                    row["captures"] == check_arrays(case, frozen, op) and (case / "params.bin").read_bytes() == payload_bytes(op, bases, n) and
                    row["image_sha256"] == info[op][route + "_image"] == sha256(image) and
                    row["sites"] == {str(pc): list(site) for pc, site in sites.items()} and row["static_opcodes"] == static and
                    proof["status"] == "PASS" and proof["dispatched_warps"] == 8 * spec["grid"] and
                    proof["active_array_requests"] == n * len(ABI[op][1]) and proof["false_predicate_array_requests"] == 0,
                    "DEBUG3 evidence differs: " + str(case))
            arrays += proof["active_array_requests"]
            if n % 4:
                tail = proof["last_warp"]
                require(proof["false_threads"] == 3 and not any(tail[str(i)] for i in range(n, n + 3)) and
                        [event["buffer"] for event in tail[str(n - 1)]] == list(ABI[op][1]) and
                        all(event["lane0_first_mask"] == "1000" for event in tail[str(n - 1)]), "tail request mask differs")
                mixed += 1
                if op == "copy" and route == "merged":
                    event = tail[str(n-1)][0 if backend == "simx" else -1]
                    with gzip.open(raw, "rt", encoding="utf-8") as stream:
                        try:
                            analyze_log(inject_false_lane(stream, backend, event), backend, op, spec, bases, sites)
                        except RuntimeError as error:
                            require(str(error).startswith(f"false-predicate lane issued array request: index {n},"),
                                    "DEBUG3 negative control failed for a different reason")
                            negative = dict(status="PASS", operation=event["operation"], reason=str(error))
                        else:
                            raise RuntimeError("the false lane injection was not detected")
    require(negative, "DEBUG3 negative control did not run")
    return dict(launches=len(run["cases"]), mixed_tail_launches=mixed, checked_array_requests=arrays,
                false_predicate_array_requests=0, negative_control=negative, summary_sha256=sha256(path / "summary.json"))


def review(args, report):
    built = args.build.resolve()
    info = receipt(built)
    successful(built)
    for name, row in info.items():
        path = built / "modules" / name
        manifest, _ = validate(path, SIM_LOCK.read_bytes())
        require(manifest["image_sha256"] == row["merged_image"] and
                sha256(path / "manifest.json") == row["manifest_sha256"] and
                sha256(path / "source_map.json") == row["source_map_sha256"], "formal build evidence differs")
    host = successful(args.host)
    report.update(build_summary_sha256=sha256(built / "summary.json"), runner_unittest=host["runner_unittest"],
                  host_summary_sha256=sha256(args.host / "summary.json"), models={})
    work = {(op, spec["n"]): (spec, frozen) for op, spec, frozen in workloads_from_kits()}
    require(len(work) == 6, "expected the six original work items")
    for backend in BACKENDS:
        path = getattr(args, backend)
        model = successful(path)
        require(model["backend"] == backend and model["binding_sha256"] == sha256(BINDINGS / backend / "binding.json") and
                model["build_sha256"] == report["build_summary_sha256"], "model identity differs")
        report["models"][backend] = dict(regressions=check_regressions(path, backend, info),
            performance=check_performance(path, backend, info, work),
            lsu=check_lsu(getattr(args, "trace_" + backend), backend, built, info, work))


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("phase", choices=("host", "review"))
    cli.add_argument("--output", type=Path, required=True)
    inputs = ("host", "build", *BACKENDS, *(f"trace-{b}" for b in BACKENDS))
    for name in inputs:
        cli.add_argument("--" + name, type=Path)
    args = cli.parse_args()
    if args.phase == "review" and not all(getattr(args, name.replace("-", "_")) for name in inputs):
        cli.error("review needs all model, build, host and trace input directories")
    out = args.output.resolve()
    require(out.parent == PROJECT / "results" and out.name.startswith("local-ptx-same-predicate-production-"),
            "choose a new formal review run")
    out.mkdir()
    report = dict(status="RUNNING", commands=[], argv=[sys.executable, "-B", *sys.argv], started_at=utc_now(),
                  board_execution="NOT_RUN", afu_execution="NOT_RUN")
    rec = Recorder(out, report, dict(os.environ, VORTEX_SOURCE=str(VORTEX)))
    try:
        if args.phase == "host":
            verify_host(rec)
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
