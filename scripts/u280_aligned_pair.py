"""Offline preflight and local fixed-U280 aligned-pair capture."""
import argparse
import json
import os
from pathlib import Path
import re
import statistics
import sys
import time

HERE = Path(__file__).resolve()
if sys.version_info[:2] == (3, 6):
    sys.path.insert(0, str(HERE.parents[1] / "third_party/dataclasses-0.8"))

from c_v03_board import bind, review_gate
from ptx_launch import BufferSlice
from ptx_module import ModuleError, digest, inspect_vxbin, read_json, validate, write_json
from ptx_runtime import Context
from ptx_u280 import BUSES, RUNTIME_SHAS, XCLBIN_SHA, XCLBIN_UUID
from ptx_u280_aligned import (COUNTS, OPERATORS, PLAN_SHA256, PROBE_SHA256, ROUTES,
                              qualify, require, verify_module)
from run_native_smoke import Recorder, sha256, utc_now
from run_ptx_copy import run_stage

SCHEMA = "u280-aligned-predicate-pair-run-v1"
CLOCK = getattr(time, "perf_counter_ns", lambda: int(time.perf_counter() * 10**9))


def preflight(bundle, compiled):
    raw = (bundle / "plan.json").read_bytes()
    require(digest(raw) == PLAN_SHA256, "frozen pair plan differs")
    plan = read_json(raw)
    require((plan["xclbin_sha256"], plan["xclbin_uuid"], plan["runtime_sha256"]) ==
            (XCLBIN_SHA, XCLBIN_UUID, RUNTIME_SHAS), "requires fixed D10/D12")
    members = {p.relative_to(bundle).as_posix(): sha256(p) for p in bundle.rglob("*")
               if p.is_file() and p != bundle / "plan.json"}
    require(members == plan["files"], "frozen pair member identity differs")
    lock = (bundle / "target_lock.json").read_bytes()
    manifests = {}
    for op in OPERATORS:
        for route in ROUTES:
            path = compiled / "modules" / op / route
            manifest, image = validate(path, lock)
            require(verify_module(manifest, image) == (op, route), "aligned pair route differs")
            manifests[op, route] = manifest
    probe = (compiled / "probe/kernel.vxbin").read_bytes()
    require(digest(probe) == PROBE_SHA256, "fixed bytewise probe image differs")
    inspect_vxbin(probe)
    return plan, manifests, probe


def measure(ctx, bundle, compiled, output, plan, manifests, counters=None):
    samples = 0
    results = {}
    schedule = read_json((bundle / "pair-schedule.json").read_bytes())
    with (output / "samples.jsonl").open("x", encoding="utf-8", newline="\n") as stream:
        for op in OPERATORS:
            manifest = manifests[op, "aligned"]
            roles = [p["name"] for p in manifest["params"] if p["kind"] == "pointer"]
            for spec in plan["cases"]:
                n = spec["n"]
                case = Path(op) / str(n)
                source = bundle / "inputs" / case
                raw = {role: (source / (role + ".bin")).read_bytes() for role in roles}
                expected = (source / "expected.bin").read_bytes()
                require(all(len(data) == 4 * spec["words"] and digest(data) ==
                            plan["files"]["inputs/{}/{}.bin".format(case.as_posix(), role)]
                            for role, data in dict(raw, expected=expected).items()), "frozen workload bytes differ")
                captures = output / "outputs" / case
                captures.mkdir(parents=True)
                handles = {role: ctx.alloc(len(data)) for role, data in raw.items()}
                scalars = dict(n=n, alpha=plan["affine_alpha"])
                args = [BufferSlice(handles[name], 4 * plan["guard_words"], 4 * n, "w" if name == "z" else "r")
                        if name in handles else scalars[name] for name in (p["name"] for p in manifest["params"])]
                pairs = [row for row in schedule if (row["operator"], row["n"]) == (op, n)]
                deltas = []
                for row in pairs:
                    measured = {}
                    for route in row["order"]:
                        start = CLOCK()
                        module = ctx.load(compiled / "modules" / op / route)
                        loaded = CLOCK()
                        for role, data in raw.items():
                            ctx.write(handles[role], 0, data)
                        uploaded = CLOCK()
                        sample = dict(scope="pair", operator=op, n=n, pair=row["pair"], route=route)
                        before = counters.before(sample) if counters is not None else None
                        execute_start = CLOCK() if counters is not None else uploaded
                        event = ctx.launch(module, manifest["entry"], (spec["grid"], 1, 1), (spec["block"], 1, 1), args)
                        ctx.wait(event)
                        completed = CLOCK()
                        counts = counters.after(sample, before) if counters is not None else None
                        download_start = CLOCK() if counters is not None else completed
                        actual = ctx.read(handles["z"], 0, len(expected))
                        downloaded = CLOCK()
                        if actual != expected:
                            (captures / (route + ".mismatch.bin")).write_bytes(actual)
                            raise ValueError("output or sentinel differs for {} {} {} pair {}".format(op, n, route, row["pair"]))
                        ctx.unload(module)
                        if row["pair"] == plan["warm"] + plan["trials"] - 1:
                            (captures / (route + ".out.bin")).write_bytes(actual)
                            (captures / (route + ".params.bin")).write_bytes(event.plan.payload)
                        times = dict(load_ns=loaded - start, h2d_ns=uploaded - loaded,
                                     execute_wait_ns=completed - execute_start, d2h_ns=downloaded - download_start)
                        times["total_ns"] = sum(times.values())
                        captured = dict(row, route=route, output_sha256=digest(actual), **times)
                        if counters is not None:
                            captured["device_counts"] = counts
                        stream.write(json.dumps(captured) + "\n")
                        stream.flush()
                        measured[route] = times
                        samples += 1
                    if not row["warmup"]:
                        deltas.append({key: measured["merged"][key] - value for key, value in measured["aligned"].items()})
                results[case.as_posix()] = {key: statistics.median(sample[key] for sample in deltas) for key in deltas[0]}
                for handle in handles.values():
                    ctx.free(handle)
    return dict(launches=samples, median_merged_minus_aligned_ns=results,
                samples_sha256=sha256(output / "samples.jsonl"))


def capture(bundle, compiled, output, *, counter_mode=False):
    plan, manifests, probe = preflight(bundle, compiled)
    # The worker already has the observer loaded. Keep it out of xbutil and
    # the BDF query subprocesses used by BoardGate.
    os.environ.pop("LD_PRELOAD", None)
    binding = output / "binding/binding.json"
    ctx = Context(binding, bundle / "target_lock.json", backend="u280-xrt", run_id=output.name, u280_aligned=True)
    expected = 2 * len(OPERATORS) * len(COUNTS) * (plan["warm"] + plan["trials"])
    counters = None
    try:
        if counter_mode:
            from u280_aligned_counters import CounterCapture
            counters = CounterCapture(ctx, output)
        qualify(ctx, bundle, manifests, probe, output, counters)
        result = measure(ctx, bundle, compiled, output, plan, manifests, counters)
        require(result["launches"] == expected, "incomplete aligned pair")
    finally:
        if counters is not None:
            counters.close(expected)
        if ctx.state == "READY":
            ctx.close()
    result.update(gate_sha256=review_gate(output), alignment_sha256=sha256(output / "alignment.json"))
    write_json(output / "capture.json", result)


def run(bundle, compiled, output, bdf, argv, *, counter_mode=False):
    preflight(bundle, compiled)
    output.mkdir(parents=True, exist_ok=False)
    report = dict(schema=SCHEMA, status="RUNNING", board_execution="NOT_RUN", argv=argv,
                  run_id=output.name, started_at=utc_now(), commands=[])
    recorder = Recorder(output, report, dict(os.environ))
    try:
        recorder.env.pop("LD_PRELOAD", None)
        observer = output / "cp_caps_observer.so"
        run_stage(recorder, "build_cp_observer", ["/opt/rh/devtoolset-9/root/usr/bin/g++", "-std=c++11", "-O2", "-fPIC", "-shared",
            HERE.parents[1] / "native/u280_cp_caps_observer.cpp", "-o", observer, "-ldl"], output)
        bind(bundle, output, bdf, recorder)
        recorder.env["LD_PRELOAD"] = str(observer)
        report.update(board_execution="FAIL", observer_sha256=sha256(observer))
        flags = ["--counters"] if counter_mode else []
        run_stage(recorder, "capture", [sys.executable, "-B", HERE, "capture", "--bundle", bundle,
            "--compiled", compiled, "--output", output, *flags], output, 900)
        report.update(status="PASS", board_execution="PASS", exit_code=0, capture_sha256=sha256(output / "capture.json"))
    except Exception as error:
        report.update(status="FAIL", exit_code=1, error=str(error))
    report["finished_at"] = utc_now()
    recorder.save()
    print(json.dumps(report))
    return report["exit_code"]


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("action", choices=("preflight", "run", "capture"))
    cli.add_argument("--bundle", required=True, type=Path)
    cli.add_argument("--compiled", required=True, type=Path)
    cli.add_argument("--output", type=Path)
    cli.add_argument("--bdf", choices=["0000:" + bus + ":00.1" for bus in BUSES])
    cli.add_argument("--counters", action="store_true")
    args = cli.parse_args()
    bundle, compiled = args.bundle.resolve(), args.compiled.resolve()
    try:
        if args.action == "preflight":
            plan, _, _ = preflight(bundle, compiled)
            print(json.dumps(dict(status="PASS", board_execution="NOT_RUN", planned_pairs=len(OPERATORS) *
                len(COUNTS) * (plan["warm"] + plan["trials"]), modules=6, formal_load="requires_live_staging")))
            return 0
        if not args.output or not re.fullmatch(r"u280-aligned-[A-Za-z0-9_-]{1,64}", args.output.name):
            cli.error("run and capture require an explicit u280-aligned-* output directory")
        if args.action == "capture":
            capture(bundle, compiled, args.output.resolve(), counter_mode=args.counters)
            return 0
        if not args.bdf:
            cli.error("run requires the selected physical BDF")
        return run(bundle, compiled, args.output.resolve(), args.bdf, [sys.executable, "-B", *sys.argv],
                   counter_mode=args.counters)
    except (OSError, ValueError, KeyError) as error:
        detail = error.to_dict() if isinstance(error, ModuleError) else dict(message=str(error))
        print(json.dumps(dict(status="FAIL", error=detail)))
        return 1


if __name__ == "__main__":
    sys.exit(main())
