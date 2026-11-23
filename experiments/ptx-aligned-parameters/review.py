"""Verify the experiment inputs, single source change, output and paired counters."""

import argparse
from collections import Counter
import json
from pathlib import Path
from statistics import median
import struct
import sys

from build import ALIGNED_READERS, BYTE_READERS, PROJECT, archives, read_layout
from run import ROUTES, SCRATCH_ALIGNMENT
from analyze import instructions
from measure import COUNTERS
from check_c_v03_receipt import BINDINGS
from run_native_smoke import sha256
from run_ptx_copy import read_json, require, write_json
from u280_perf_pair import ABI, ALPHA, workloads


def receipt(path):
    summary = read_json(path / "summary.json")
    require(summary["status"] == "PASS" and summary["exit_code"] == 0 and summary["board_execution"] == "NOT_RUN",
            "missing successful local execution: " + str(path))
    for command in summary["commands"]:
        require(command["returncode"] == 0 and not command["timed_out"] and
                sha256(path / command["log"]) == command["log_sha256"], "command or recorded log differs")
    return summary


def verify_build(build):
    report = receipt(build)
    static = {}
    for op, detail in report["operators"].items():
        archive = PROJECT / detail["archive"]
        static[op] = {}
        for route in ROUTES:
            files = build / op / route
            for name, digest in detail["variants"][route].items():
                require(sha256(files / name) == digest, "build member changed: " + str(files / name))
            code = list(instructions(files / "kernel.dump", files / "kernel.vxbin"))
            static[op][route] = dict(count=len(code), mnemonics=dict(Counter(name for _, name, _ in code)))
        bytewise, aligned = (build / op / route for route in ROUTES)
        original = (archive / "kernel_body.hpp").read_bytes()
        require(read_layout(archive) == detail["layout"] and original.count(BYTE_READERS) == 1 and
                (bytewise / "kernel_body.hpp").read_bytes() == original and
                (aligned / "kernel_body.hpp").read_bytes() == original.replace(BYTE_READERS, ALIGNED_READERS) and
                sha256(bytewise / "kernel.vxbin") == sha256(archive / "kernel.vxbin"), "reader isolation or baseline image differs")
        for name in ("kernel.cpp", "Makefile"):
            require(sha256(bytewise / name) == sha256(aligned / name) == sha256(archive / name), "wrapper or flags differ")
        counts = static[op]["aligned"]["mnemonics"]
        require(not counts.get("lbu") and counts.get("ld", 0) == len(ABI[op][1]), "expected aligned pointer loads")
    require(sha256(build / "probe/kernel.vxbin") == report["probe"]["kernel.vxbin"], "probe hash differs")
    return report, static


def verify_probe(case, layout, op, n):
    proof = read_json(case / "alignment.json")
    raw = case / "address-probe.bin"
    args = (case / "params.bin").read_bytes()
    payload, csr = struct.unpack("<QQ", raw.read_bytes())
    require(proof["status"] == "PASS" and proof["device_base_alignment"] == SCRATCH_ALIGNMENT and
            payload == csr == proof["payload_address"] == proof["mscratch"] and payload > 0 and
            payload % SCRATCH_ALIGNMENT == 0 and proof["length"] == len(args) == layout["bytes"] and
            sha256(raw) == proof["readback_sha256"] and sha256(case / "params.bin") == proof["params_sha256"],
            "unaligned or inconsistent probe evidence")
    expected_fields = {}
    for field in layout["fields"]:
        address = payload + field["offset"]
        require(address % field["align"] == 0, "field address is misaligned")
        expected_fields[field["name"]] = dict(address=address, align=field["align"])
    require(proof["fields"] == expected_fields, "field layout differs from probe receipt")
    fmt, roles, _ = ABI[op]
    values = struct.unpack(fmt, args)
    pointers, scalars = values[:len(roles)], values[len(roles):]
    require(len(set(pointers)) == len(roles) and all(ptr > 0 and ptr % 4 == 0 for ptr in pointers) and
            scalars == ((n, ALPHA) if op == "affine" else (n,)), "unexpected captured payload")
    return proof


def verify_backend(path, backend, build_path, build, cases):
    summary = receipt(path)
    capture = read_json(path / "capture.json")
    require(summary["backend"] == backend and len(summary["commands"]) == 1 and summary["repeats"] % 2 == 0 and
            capture["status"] == "PASS" and capture["exit_code"] == 0 and capture["vm_support"] == 0 and
            capture["build_summary_sha256"] == sha256(build_path / "summary.json") and
            capture["binding_sha256"] == sha256(BINDINGS / backend / "binding.json") and
            capture["probes"] == len(cases), "capture identity differs")
    logfile = path / "samples.jsonl"
    rows = [json.loads(line) for line in logfile.read_text(encoding="utf-8").splitlines()]
    index = {(r["operator"], r["n"], r["route"], r["repeat"]): r for r in rows}
    expected = {(op, n, route, repeat) for op, n in cases for route in ROUTES for repeat in range(summary["repeats"])}
    require(index.keys() == expected and len(rows) == len(index) == capture["samples"], "missing or duplicate sample")
    metrics = {}
    for (op, n), (spec, bundle, plan, subdir) in cases.items():
        case = path / op / str(n)
        proof = verify_probe(case, build["operators"][op]["layout"], op, n)
        frozen = bundle / "inputs" / subdir
        inputs = {name: plan["files"][(Path("inputs") / subdir / (name + ".bin")).as_posix()]
                  for name in (*ABI[op][1], "expected")}
        require(all(digest == sha256(frozen / (name + ".bin")) for name, digest in inputs.items()), "frozen data changed")
        expected_hash = inputs.pop("expected")
        expected_output = (frozen / "expected.bin").read_bytes()
        runs = {route: [] for route in ROUTES}
        for repeat in range(summary["repeats"]):
            order = ROUTES if repeat % 2 == 0 else ROUTES[::-1]
            for position, route in enumerate(order):
                sample = index[op, n, route, repeat]
                output = case / ("{}-{}.bin".format(route, repeat))
                require(all(sample[key] == value for key, value in spec.items()) and sample["position"] == position and
                        sample["image_sha256"] == build["operators"][op]["variants"][route]["kernel.vxbin"] and
                        sample["inputs"] == inputs and sample["params_sha256"] == proof["params_sha256"] and
                        sample["alignment_sha256"] == sha256(case / "alignment.json"), "sample provenance differs")
                require(sample["output_sha256"] == sample["expected_sha256"] == expected_hash and
                        output.read_bytes() == expected_output, "sample output or sentinel differs")
                delta = sample["delta"]
                require(sample["idle"] == sample["before"] and delta ==
                        {key: sample["after"][key] - sample["before"][key] for key in COUNTERS} and
                        min(delta.values()) >= 0 and delta["cycles"] > 0 and delta["instret"] > 0,
                        "invalid counter delta")
                runs[route].append(delta)
        statistics = {}
        for route, samples in runs.items():
            require(len({s["instret"] for s in samples}) == 1, "retired counts differ across repetitions")
            statistics[route] = {key: median(s[key] for s in samples) for key in COUNTERS}
            statistics[route]["cycles_range"] = [min(s["cycles"] for s in samples), max(s["cycles"] for s in samples)]
        baseline, aligned = (statistics[route] for route in ROUTES)
        pair_deltas = [b["cycles"] - a["cycles"] for b, a in zip(runs["bytewise"], runs["aligned"])]
        metrics["{}/{}".format(op, n)] = dict(
            statistics, probe_address=proof["payload_address"], output_sha256=expected_hash, pair_cycle_savings=pair_deltas,
            cycles_saved=baseline["cycles"] - aligned["cycles"], cycles_saved_percent=100*(1-aligned["cycles"]/baseline["cycles"]),
            instret_saved=baseline["instret"] - aligned["instret"], instret_saved_percent=100*(1-aligned["instret"]/baseline["instret"]))
    return metrics, dict(summary_sha256=sha256(path / "summary.json"), samples_sha256=sha256(logfile),
                         launches=len(rows), probes=capture["probes"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("build", "simx", "rtlsim", "prior", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    build, static = verify_build(args.build)
    cases = {}
    for bundle, _ in archives():
        plan = read_json(bundle / "plan.json")
        for op, spec, subdir in workloads(plan):
            cases[op, spec["n"]] = (spec, bundle, plan, subdir)
    prior = read_json(args.prior)
    require(prior["status"] == "PASS" and prior["board_execution"] == "NOT_RUN", "invalid previous model baseline")
    metrics, sources = {}, {}
    for backend in ("simx", "rtlsim"):
        metrics[backend], sources[backend] = verify_backend(getattr(args, backend), backend, args.build, build, cases)
    for case, sim in metrics["simx"].items():
        rtl = metrics["rtlsim"][case]
        require(all(sim[route]["instret"] == rtl[route]["instret"] for route in ROUTES) and
                sim["output_sha256"] == rtl["output_sha256"] and
                all(metrics[b][case]["bytewise"]["instret"] == prior["metrics"][b][case]["ptx"]["instret"] for b in metrics),
                "cross-backend or prior-baseline retirement or output differs")
    write_json(args.output, dict(status="PASS", exit_code=0, board_execution="NOT_RUN", static=static, metrics=metrics,
                                 captures=sources, build_summary_sha256=sha256(args.build / "summary.json"),
                                 prior_sha256=sha256(args.prior), argv=[sys.executable, "-B", *sys.argv],
                                 script_sha256=sha256(__file__)))
    for backend, results in metrics.items():
        for case, data in results.items():
            print(backend, case, "cycles", [data[r]["cycles"] for r in ROUTES], "instret", [data[r]["instret"] for r in ROUTES],
                  "cycles/instret saved %", round(data["cycles_saved_percent"], 2), round(data["instret_saved_percent"], 2))


if __name__ == "__main__":
    main()
