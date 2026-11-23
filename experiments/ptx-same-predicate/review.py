"""Check recorded builds, paired counters, complete arrays and DEBUG3 receipts."""

import argparse
import gzip
import json
import os
from pathlib import Path
import re
from statistics import median
import sys

from run import (ABI, BACKENDS, BINDINGS, COUNTERS, FORMAL, PROJECT, ROUTES, SIM_LOCK, TRIALS, VORTEX, Recorder,
                 build_receipt, cases, images, merge_region, payload_bytes, read_json, require,
                 run_stage, sha256, utc_now)
from trace import MASK, TRACE_BINDINGS, analyze_log, data_sites
from u280_perf_pair import GUARD


def successful(path):
    report = read_json(path / "summary.json")
    require(report["status"] == "PASS" and report["exit_code"] == 0 and report["board_execution"] == "NOT_RUN",
            "unsuccessful command receipt: " + str(path))
    for command in report["commands"]:
        require(command["returncode"] == 0 and not command["timed_out"] and
                sha256(path / command["log"]) == command["log_sha256"], "command record or log differs")
    return report


def check_build(built):
    successful(built)
    report = build_receipt(built)
    static = {}
    for op, record in report.items():
        root = built / op
        formal = FORMAL / "modules" / op
        require(sha256(formal / "kernel.vxbin") == record["aligned_image"] and
                sha256(root / "same-predicate.diff") == record["diff_sha256"], "baseline or source diff changed")
        _, merged = merge_region(op, root / "aligned")
        require((root / "merged/kernel_body.hpp").read_bytes() == merged.encode() and
                all(sha256(root / "merged" / name) == digest for name, digest in record["merged_files"].items()),
                "merged files differ from build receipt")
        static[op] = {}
        for route, path in images(built, op, record).items():
            sites, counts = data_sites(path, op)
            splits = 1 if route == "merged" else len(ABI[op][1])
            require(all(counts.get(kind) == splits for kind in ("vx_split_n", "beqz", "vx_join"))
                    and "lbu" not in counts, "disassembly lacks expected guarded regions or aligned loads")
            static[op][route] = dict(sites=sites, counts=counts, instructions=sum(counts.values()))
    return report, static


def check_arrays(path, frozen, op):
    hashes = {}
    for role in ABI[op][1]:
        output = path / (role + ".bin")
        expected = frozen / ("expected.bin" if role == "z" else role + ".bin")
        require(output.read_bytes() == expected.read_bytes(), "full captured array changed: " + str(output))
        hashes[role] = sha256(output)
    return hashes


def check_measure(path, backend, built, operators, work):
    report = successful(path)
    require(report["backend"] == backend and report["trials"] == TRIALS and
            report["binding_sha256"] == sha256(BINDINGS / backend / "binding.json") and
            report["build_sha256"] == sha256(built / "summary.json"), "counter run identity differs")
    rows = [json.loads(line) for line in (path / "samples.jsonl").read_bytes().splitlines()]
    prior_path = PROJECT / f"results/local-ptx-aligned-production-{backend}-20261121-v1/performance/samples.jsonl"
    prior = {(row["operator"], row["n"], row["pair"]): row for line in prior_path.read_bytes().splitlines()
             if (row := json.loads(line))["route"] == "aligned"}
    ordered = {(r["operator"], r["n"], r["pair"], r["route"]): r for r in rows}
    require(len(rows) == len(ordered) == len(work) * 2 * TRIALS, "missing or duplicate timed launch")
    result = {}
    for (op, n), (spec, frozen) in work.items():
        directory = path / op / str(n)
        payload = payload_bytes(op, read_json(directory / "bases.json"), n)
        require((directory / "params.bin").read_bytes() == payload, "captured counter payload differs")
        deltas = {route: [] for route in ROUTES}
        for pair in range(TRIALS):
            order = ROUTES if pair % 2 == 0 else ROUTES[::-1]
            for position, route in enumerate(order):
                row = ordered[op, n, pair, route]
                capture = directory / (route + "-" + str(pair))
                require(all(row[key] == value for key, value in spec.items()) and row["position"] == position and
                        row["params_sha256"] == sha256(directory / "params.bin") and
                        row["image_sha256"] == operators[op][route + "_image"] and
                        row["captures"] == check_arrays(capture, frozen, op), "counter capture differs")
                delta = {key: row["after"][key] - row["before"][key] for key in COUNTERS}
                require(row["idle"] == row["before"] and row["delta"] == delta and min(delta.values()) >= 0 and
                        min(delta["instret"], delta["cycles"]) > 0, "counter delta differs")
                if route == "aligned":
                    old = prior[op, n, pair]
                    require(old["image_sha256"] == row["image_sha256"] and old["delta"]["instret"] == delta["instret"],
                            "formal baseline retirement did not reproduce")
                deltas[route].append(delta)
        metrics = {route: {key: median(d[key] for d in deltas[route]) for key in ("cycles", "instret")}
                   for route in ROUTES}
        for route, values in deltas.items():
            require(len({row["instret"] for row in values}) == 1, "retirement count changed between repeats: " + route)
        result[f"{op}/{n}"] = dict(**metrics,
            reduction_pct={key: 100 * (1 - metrics["merged"][key] / metrics["aligned"][key])
                           for key in ("cycles", "instret")},
            paired_cycle_savings=[a["cycles"] - b["cycles"] for a, b in zip(deltas["aligned"], deltas["merged"])])
    return dict(metrics=result, launch_count=len(rows), samples_sha256=sha256(path / "samples.jsonl"),
                formal_samples_sha256=sha256(prior_path), summary_sha256=sha256(path / "summary.json"))


def inject_false_lane(lines, backend, tail):
    active_addr = int(tail["address"], 16)
    bit_order = "1000" if backend == "simx" else "0001"
    packet = "mem-req: op=LD" if backend == "simx" else "Wr Req:"
    for line in lines:
        mask = MASK.search(line) if packet in line else None
        if mask and mask[1] == bit_order:
            values = re.match(r"\{([^}]+)\}", line[mask.end():])
            fields = values[1].split(", ")
            index = 0 if backend == "simx" else 3
            if int(fields[index], 16) == active_addr:
                fields[1 if backend == "simx" else 2] = hex(active_addr + 4)
                yield (line[:mask.start(1)] + ("1100" if backend == "simx" else "0011") +
                       line[mask.end(1):mask.end()] + "{" + ", ".join(fields) + "}" +
                       line[mask.end() + values.end():])
                yield from lines
                return
        yield line
    raise RuntimeError("tail packet to mutate was absent")


def check_trace(path, backend, built, operators, static, work):
    report = successful(path)
    require(report["backend"] == backend and report["build_sha256"] == sha256(built / "summary.json") and
            report["binding_sha256"] == sha256(TRACE_BINDINGS / backend / "binding.json"), "trace run identity differs")
    total, mixed, negative = 0, 0, None
    receipts = {(r["operator"], r["n"], r["route"]): r for r in report["cases"]}
    require(len(receipts) == len(report["cases"]) == 2 * len(work), "trace coverage differs")
    for (op, n), (spec, frozen) in work.items():
        for route in ROUTES:
            directory = path / op / str(n) / route
            row = read_json(directory / "trace.json")
            bases = read_json(directory / "bases.json")
            raw = directory / "lsu.log.gz"
            captures = check_arrays(directory, frozen, op)
            sites = static[op][route]["sites"]
            require(row == receipts[op, n, route] and row["status"] == "PASS" and
                    row["raw_trace_sha256"] == sha256(raw) and row["output_sha256"] == captures["z"] and
                    row["image_sha256"] == operators[op][route + "_image"] and
                    row["params_sha256"] == sha256(directory / "params.bin") and
                    (directory / "params.bin").read_bytes() == payload_bytes(op, bases, n) and
                    row["sites"] == {str(pc): list(site) for pc, site in sites.items()} and
                    row["dispatched_warps"] == spec["grid"] * 8 and row["active_threads"] == n and
                    row["false_threads"] == spec["grid"] * spec["block"] - n and row["false_predicate_array_requests"] == 0,
                    "trace receipt or artifact differs")
            roles = ABI[op][1]
            require((row["active_loads"], row["active_stores"], row["active_array_requests"]) ==
                    ((len(roles) - 1) * n, n, len(roles) * n), "trace request totals differ")
            total += row["active_array_requests"]
            if n % 4:
                tail = row["last_warp"]
                require(row["false_threads"] == 3 and set(tail) == {str(i) for i in range(n-1, n+3)} and
                        [event["buffer"] for event in tail[str(n-1)]] == list(roles) and
                        all(event["lane0_first_mask"] == "1000" for event in tail[str(n-1)]) and
                        all(not tail[str(i)] for i in range(n, n+3)), "tail mixed warp differs")
                mixed += 1
                if op == "copy" and route == "merged":
                    target = tail[str(n-1)][0 if backend == "simx" else -1]
                    with gzip.open(raw, "rt", encoding="utf-8") as stream:
                        try:
                            analyze_log(inject_false_lane(stream, backend, target), backend, op, spec, bases, sites)
                        except RuntimeError as error:
                            require(str(error).startswith(f"false-predicate lane issued array request: index {n},"),
                                    "negative control failed for another reason: " + str(error))
                            negative = dict(status="PASS", injection="extra " + target["operation"], error=str(error))
                        else:
                            raise RuntimeError("negative control did not detect an active false lane")
    require(negative is not None, "negative control was not exercised")
    return dict(launch_count=len(receipts), mixed_tail_launches=mixed, active_array_requests=total,
                false_predicate_array_requests=0, negative_control=negative, summary_sha256=sha256(path / "summary.json"))


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--build", type=Path, required=True)
    cli.add_argument("--output", type=Path, required=True)
    for backend in BACKENDS:
        cli.add_argument("--measure-" + backend, type=Path, required=True)
        cli.add_argument("--trace-" + backend, type=Path, required=True)
    args = cli.parse_args()
    out, built = args.output.resolve(), args.build.resolve()
    require(out.parent == PROJECT / "results" and out.name.startswith("local-ptx-same-predicate-"), "choose a new run")
    out.mkdir()
    report = dict(status="RUNNING", board_execution="NOT_RUN", afu_execution="NOT_RUN", commands=[],
                  started_at=utc_now(), argv=[sys.executable, "-B", *sys.argv], script_sha256=sha256(__file__),
                  lock_sha256=sha256(SIM_LOCK), build_summary_sha256=sha256(built / "summary.json"))
    rec = Recorder(out, report, dict(os.environ, VORTEX_SOURCE=str(VORTEX)))
    try:
        output = run_stage(rec, "runner_unittest", [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-v"],
                           PROJECT, 300)
        count = re.search(r"Ran (\d+) tests?", output)
        skipped = re.search(r"^OK \(skipped=(\d+)\)", output, re.M)
        require(count, "missing unittest count")
        report["runner_unittest"] = dict(total=int(count[1]), skipped=int(skipped[1]) if skipped else 0, exit_code=0)
        ops, static = check_build(built)
        work = {(op, spec["n"]): (spec, frozen) for op, spec, frozen in cases()}
        require(len(work) == 6, "expected three operators and two original input sizes")
        report.update(static=static, models={})
        for backend in BACKENDS:
            measure = check_measure(getattr(args, "measure_" + backend), backend, built, ops, work)
            trace = check_trace(getattr(args, "trace_" + backend), backend, built, ops, static, work)
            report["models"][backend] = dict(measure=measure, trace=trace)
        first, second = (report["models"][b]["measure"]["metrics"] for b in BACKENDS)
        require(all(first[case][route]["instret"] == second[case][route]["instret"]
                    for case in first for route in ROUTES), "retirement differs between models")
        report.update(status="PASS", exit_code=0)
    except Exception as error:
        report.update(status="FAIL", exit_code=1, error=str(error))
    report["finished_at"] = utc_now()
    rec.save()
    print(report["status"], out, report.get("error", ""))
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
