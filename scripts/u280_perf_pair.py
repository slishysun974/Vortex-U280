"""Measure same-queue native/PTX integer pairs on U280 with Vortex2 event profiling."""

import argparse
import ctypes as C
import json
import os
from pathlib import Path
import random
import re
import shutil
import statistics
import struct
import sys
import time

HERE = Path(__file__).resolve()
if sys.version_info[:2] == (3, 6):
    sys.path.insert(0, str(HERE.parents[1] / "vendor/dataclasses-0.8"))

from c_v03_board import BOARD_BACKEND, PY_FILES, bind, check_commands, review_gate
from check_c_v03_receipt import BINDINGS
from ptx_module import BOARD_LOCK_SHA, ModuleError, inspect_vxbin, validate
from ptx_runtime import Context, LaunchInfo, Module, P, Q, QueueInfo, U
from ptx_u280 import BUSES, QUERY_SOURCE, RUNTIME_SHAS, XCLBIN_SHA
from run_native_smoke import PROJECT, Recorder, sha256, utc_now
from run_ptx_copy import BOARD_LOCK, SIM_LOCK, read_json, require, run_stage, write_json

SCHEMA = "u280-native-ptx-vadd-perf-v1"
SUITE_SCHEMA = "u280-native-ptx-integer-perf-v2"
ROUTES = ("native", "ptx")
BLOCK = 32
GUARD = 16
CASES = (1024, 16381)
WARM, TRIALS = 5, 30
PILOT = (1, 2)
ALPHA = 0x9e3779b9
ABI = {
    "copy": ("<QQI4x", ("x", "z"), ("n",)),
    "vadd": ("<QQQI4x", ("x", "y", "z"), ("n",)),
    "affine": ("<QQQII", ("x", "y", "z"), ("n", "alpha")),
}
METRICS = ("load_ns", "h2d_ns", "execute_wait_ns", "execute_profile_ns", "d2h_ns", "total_ns", "total_with_load_ns")
PROFILE_FIELDS = ("queued_ns", "submit_ns", "start_ns", "end_ns")
CLOCK = getattr(time, "perf_counter_ns", lambda: int(time.perf_counter() * 10**9))


class EventProfile(C.Structure):
    _fields_ = [(name, Q) for name in PROFILE_FIELDS]


def cases():
    return [dict(n=n, block=BLOCK, grid=(n + BLOCK - 1) // BLOCK,
                 words=((n + BLOCK - 1) // BLOCK) * BLOCK + 2 * GUARD) for n in CASES]


def operations(plan):
    return plan["operators"] if plan["schema"] == SUITE_SCHEMA else ("vadd",)


def operator_path(plan, path, operation):
    return path / operation if plan["schema"] == SUITE_SCHEMA else path


def workloads(plan):
    for operation in operations(plan):
        for spec in plan["cases"]:
            yield operation, spec, operator_path(plan, Path(), operation) / str(spec["n"])


def payload_bytes(operation, bases, n):
    layout, pointers, scalars = ABI[operation]
    values = dict(n=n, alpha=ALPHA)
    return struct.pack(layout, *(bases[r] + 4 * GUARD for r in pointers), *(values[name] for name in scalars))


def freeze_inputs(root, plan):
    for operation, spec, subdir in workloads(plan):
        n = spec["n"]
        case = root / subdir
        case.mkdir(parents=True)
        rng = random.Random(0x4021A11 + n)
        x, y, initial = ([rng.getrandbits(32) for _ in range(spec["words"])] for _ in range(3))
        expected = initial[:]
        if operation == "copy":
            expected[GUARD:GUARD + n] = x[GUARD:GUARD + n]
        else:
            scale = ALPHA if operation == "affine" else 1
            expected[GUARD:GUARD + n] = [(scale * x[i] + y[i]) & 0xffffffff for i in range(GUARD, GUARD + n)]
        inputs = dict(x=x, y=y, z=initial, expected=expected)
        for name in (*ABI[operation][1], "expected"):
            words = inputs[name]
            (case / (name + ".bin")).write_bytes(struct.pack("<{}I".format(len(words)), *words))


def validate_ptx_layout(ptx, operation):
    layout, pointers, scalars = ABI[operation]
    fields = [(name, 8 * i) for i, name in enumerate(pointers)]
    fields.extend((name, 8 * len(pointers) + 4 * i) for i, name in enumerate(scalars))
    require(ptx["entry"] == operation + "_u32" and ptx["native_entry"] == "main" and
            ptx["params_size"] == struct.calcsize(layout) and [(p["name"], p["offset"]) for p in ptx["params"]] == fields,
            "paired PTX parameter layout differs: " + operation)


def validate_pair(path, lock, expected, operation="vadd"):
    ptx, _ = validate(path / "ptx", lock.read_bytes())
    validate_ptx_layout(ptx, operation)
    for route, source in (("native", "kernel.cpp"), ("ptx", "source.ptx")):
        directory = path / route
        require(sha256(directory / "kernel.vxbin") == expected[route]["image_sha256"] and
                sha256(directory / source) == expected[route]["source_sha256"], "paired image/source differs: " + route)
        inspect_vxbin((directory / "kernel.vxbin").read_bytes())


def preflight(bundle):
    plan = read_json(bundle / "plan.json")
    require(plan["schema"] in (SCHEMA, SUITE_SCHEMA) and plan["cases"] == cases() and plan["warm"] == WARM and plan["trials"] == TRIALS and
            plan["xclbin_sha256"] == XCLBIN_SHA and plan["runtime_sha256"] == RUNTIME_SHAS and
            sha256(bundle / "target_lock.json") == BOARD_LOCK_SHA, "paired plan or board identity differs")
    if plan["schema"] == SUITE_SCHEMA:
        names = operations(plan)
        require(names and set(names) <= set(ABI) and len(set(names)) == len(names) and
                set(plan["workloads"]) == set(names) and plan["affine_alpha"] == ALPHA, "invalid operator suite")
    actual = {p.relative_to(bundle).as_posix(): sha256(p) for p in bundle.rglob("*")
              if p.is_file() and p != bundle / "plan.json"}
    require(actual == plan["files"], "paired kit member differs")
    validate_images(bundle / "modules", bundle / "target_lock.json", plan)
    return plan


def validate_images(root, lock, plan):
    for operation in operations(plan):
        expected = plan["workloads"][operation] if plan["schema"] == SUITE_SCHEMA else plan["modules"]
        validate_pair(operator_path(plan, root, operation), lock, expected, operation)


def prepare(run, build):
    compiled = read_json(build / "summary.json")
    check_commands(build, compiled)
    physical, model = (compiled["targets"][target] for target in ("board", "sim"))
    plan = dict(schema=SCHEMA, cases=cases(), warm=WARM, trials=TRIALS, guard_words=GUARD,
                xclbin_sha256=XCLBIN_SHA, runtime_sha256=RUNTIME_SHAS, build_summary_sha256=sha256(build / "summary.json"))
    if "operators" in compiled:
        plan.update(schema=SUITE_SCHEMA, operators=compiled["operators"], affine_alpha=ALPHA,
                    workloads={op: physical["workloads"][op]["modules"] for op in compiled["operators"]})
        require(all(model["workloads"][op]["modules"] == plan["workloads"][op] for op in operations(plan)),
                "board and model code differ")
    else:
        plan["modules"] = physical["modules"]
        require(model["modules"] == plan["modules"], "board and model code differ")
    validate_images(build / "board", BOARD_LOCK, plan)
    bundle = run / "bundle"
    stage = bundle / "scripts"
    stage.mkdir(parents=True)
    for name in (*PY_FILES, HERE.name):
        shutil.copyfile(HERE.parent / name, stage / name)
    vendor = PROJECT / "third_party/dataclasses-0.8"
    dependency = bundle / "vendor/dataclasses-0.8"
    dependency.mkdir(parents=True)
    for name, expected_hash in read_json(vendor / "provenance.json")["files"].items():
        require(Path(name).name == name and sha256(vendor / name) == expected_hash, "3.6 backport differs")
        shutil.copyfile(vendor / name, dependency / name)
    shutil.copyfile(vendor / "provenance.json", dependency / "provenance.json")
    shutil.copyfile(BOARD_LOCK, bundle / "target_lock.json")
    shutil.copyfile(BOARD_LOCK.with_name("fpga.json"), bundle / "hardware.json")
    (bundle / "query.cpp").write_bytes(QUERY_SOURCE.encode())
    shutil.copytree(build / "board", bundle / "modules")
    freeze_inputs(bundle / "inputs", plan)
    plan["files"] = {p.relative_to(bundle).as_posix(): sha256(p) for p in sorted(bundle.rglob("*")) if p.is_file()}
    write_json(bundle / "plan.json", plan)
    preflight(bundle)
    return Path(shutil.make_archive(str(run / "u280-perf-input"), "gztar", root_dir=run, base_dir="bundle"))


def load_image(ctx, image, name):
    native, kernel = P(), P()
    ctx.check(ctx.lib.vx_module_load_bytes(ctx.device, C.cast(image, P), C.sizeof(image), C.byref(native)), "module_load")
    ctx.check(ctx.lib.vx_module_get_kernel(native, b"main", C.byref(kernel)), "kernel_entry")
    module = Module(dict(entry=name), native, kernel)
    ctx.modules.add(module)
    return module


def timings(boundaries, profiles):
    begin, loaded, uploaded, executed, readback = boundaries
    return dict(load_ns=loaded - begin, h2d_ns=uploaded - loaded, execute_wait_ns=executed - uploaded,
                execute_profile_ns=profiles["launch"]["end_ns"] - profiles["launch"]["start_ns"],
                d2h_ns=readback - executed, total_ns=readback - loaded, total_with_load_ns=readback - begin,
                h2d_profile_ns=sum(p["end_ns"] - p["start_ns"] for name, p in profiles.items() if name.startswith("write_")),
                d2h_profile_ns=profiles["read_z"]["end_ns"] - profiles["read_z"]["start_ns"])


def trial(ctx, route, image, buffers, host, payload, spec, actual):
    uploads = tuple("write_" + role for role in buffers)
    events = {phase: P() for phase in (*uploads, "launch", "read_z")}
    size = 4 * spec["words"]
    launch = LaunchInfo()
    launch.struct_size = C.sizeof(launch)
    launch.args_host, launch.args_size = C.cast(payload, P), C.sizeof(payload)
    launch.ndim, launch.grid_dim, launch.block_dim = 1, (U * 3)(spec["grid"], 1, 1), (U * 3)(BLOCK, 1, 1)
    timeout = ctx.timeout_ns(60000)
    begin = CLOCK()
    module = load_image(ctx, image, route)
    launch.kernel = module.kernel
    loaded = CLOCK()
    for role in buffers:
        name = "write_" + role
        ctx.check(ctx.lib.vx_enqueue_write(ctx.queue, buffers[role], 0, host[role], size, 0, None, C.byref(events[name])), name)
    ctx.check(ctx.lib.vx_event_wait_value(events[uploads[-1]], 1, timeout), "wait_uploads")
    uploaded = CLOCK()
    ctx.check(ctx.lib.vx_enqueue_launch(ctx.queue, C.byref(launch), 0, None, C.byref(events["launch"])), "launch")
    ctx.check(ctx.lib.vx_event_wait_value(events["launch"], 1, timeout), "wait_launch")
    executed = CLOCK()
    ctx.check(ctx.lib.vx_enqueue_read(ctx.queue, actual, buffers["z"], 0, size, 0, None, C.byref(events["read_z"])), "read_z")
    ctx.check(ctx.lib.vx_event_wait_value(events["read_z"], 1, timeout), "wait_read")
    readback = CLOCK()
    profiles = {}
    for name, event in events.items():
        profile = EventProfile()
        ctx.check(ctx.lib.vx_event_get_profiling(event, C.byref(profile)), "profile_" + name)
        profiles[name] = {field: getattr(profile, field) for field in PROFILE_FIELDS}
        ctx.check(ctx.lib.vx_event_release(event), "release_" + name)
    ctx.unload(module)
    boundaries = [begin, loaded, uploaded, executed, readback]
    return dict(host_ns=boundaries, queue_profiles=profiles, **timings(boundaries, profiles))


def capture(bundle, run, backend, binding, modules, lock, warm, trials):
    plan = preflight(bundle)
    validate_images(modules, lock, plan)
    images = {}
    for operation in operations(plan):
        for route in ROUTES:
            raw = (operator_path(plan, modules, operation) / route / "kernel.vxbin").read_bytes()
            images[operation, route] = C.create_string_buffer(raw, len(raw))
    out = run / backend
    out.mkdir()
    report = dict(backend=backend, state="NOT_OPEN", samples=0, binding_sha256=sha256(binding),
                  plan_sha256=sha256(bundle / "plan.json"), clock="perf_counter (host monotonic)", warm=warm, trials=trials)
    ctx = None
    try:
        ctx = Context(binding, lock, backend=backend, run_id=run.name)
        ctx.check(ctx.lib.vx_queue_release(ctx.queue), "release_unused_queue")
        ctx.queue = P()
        info = QueueInfo(C.sizeof(QueueInfo), None, 1, 1)  # VX_QUEUE_PROFILING_ENABLE
        ctx.check(ctx.lib.vx_queue_create(ctx.device, C.byref(info), C.byref(ctx.queue)), "profile_queue")
        ctx.lib.vx_event_get_profiling.argtypes = [P, C.POINTER(EventProfile)]
        ctx.lib.vx_event_get_profiling.restype = C.c_int
        with (out / "samples.jsonl").open("x", encoding="utf-8", newline="\n") as stream:
            for operation, spec, subdir in workloads(plan):
                n, size = spec["n"], 4 * spec["words"]
                source = bundle / "inputs" / subdir
                case = out / subdir
                case.mkdir(parents=True)
                host = {r: C.create_string_buffer((source / (r + ".bin")).read_bytes(), size) for r in ABI[operation][1]}
                expected = (source / "expected.bin").read_bytes()
                actual = C.create_string_buffer(size)
                handles = {r: ctx.alloc(size) for r in host}
                buffers = {r: ctx.buffers[h][0] for r, h in handles.items()}
                bases = {}
                for role, buffer in buffers.items():
                    address = Q()
                    ctx.check(ctx.lib.vx_buffer_address(buffer, C.byref(address)), "buffer_address")
                    bases[role] = address.value
                write_json(case / "bases.json", bases)
                args = payload_bytes(operation, bases, n)
                (case / "params.bin").write_bytes(args)
                payload = C.create_string_buffer(args, len(args))
                for pair in range(warm + trials):
                    order = ROUTES if pair % 2 == 0 else ROUTES[::-1]
                    for position, route in enumerate(order):
                        report["current"] = dict(operation=operation, n=n, pair=pair, route=route)
                        measured = trial(ctx, route, images[operation, route], buffers, host, payload, spec, actual)
                        name = route + ".out.bin"
                        if actual.raw != expected:
                            (case / (route + ".mismatch.bin")).write_bytes(actual.raw)
                            raise RuntimeError("output/sentinel differs: {} {} {} pair {}".format(operation, n, route, pair))
                        if pair == warm + trials - 1:
                            (case / name).write_bytes(actual.raw)
                        measured.update(n=n, pair=pair, position=position, route=route, warmup=pair < warm,
                                        output_sha256=plan["files"]["inputs/{}/expected.bin".format(subdir.as_posix())])
                        if plan["schema"] == SUITE_SCHEMA:
                            measured["operator"] = operation
                        stream.write(json.dumps(measured, separators=(",", ":")) + "\n")
                        stream.flush()
                        report["samples"] += 1
                for handle in handles.values():
                    ctx.free(handle)
        ctx.close()
        report.pop("current", None)
    except Exception as error:
        report["error"] = error.to_dict() if isinstance(error, ModuleError) else str(error)
        if ctx is not None and ctx.state == "READY":
            try:
                ctx.close()
            except Exception as cleanup:
                report["cleanup_error"] = str(cleanup)
        raise
    finally:
        report["state"] = ctx.state if ctx is not None else "NOT_OPEN"
        write_json(out / "capture.json", report)


def summary_stats(values):
    return dict(median=statistics.median(values), min=min(values), max=max(values))


def review_capture(bundle, run, backend, binding, warm, trials):
    plan = preflight(bundle)
    out = run / backend
    meta = read_json(out / "capture.json")
    rows = [json.loads(line) for line in (out / "samples.jsonl").read_text(encoding="utf-8").splitlines()]
    workload_count = len(operations(plan)) * len(plan["cases"])
    count = 2 * workload_count * (warm + trials)
    require(meta["backend"] == backend and meta["state"] == "CLOSED" and "error" not in meta and
            meta["binding_sha256"] == sha256(binding) and meta["plan_sha256"] == sha256(bundle / "plan.json") and
            meta["samples"] == len(rows) == count and (meta["warm"], meta["trials"]) == (warm, trials), "incomplete timing capture")
    samples = iter(rows)
    results = {}
    for operation, spec, subdir in workloads(plan):
        n = spec["n"]
        roles = ABI[operation][1]
        stages = (*("write_" + role for role in roles), "launch", "read_z")
        raw = out / subdir
        expected = plan["files"]["inputs/{}/expected.bin".format(subdir.as_posix())]
        bases = read_json(raw / "bases.json")
        ordered = sorted(bases.values())
        require(set(bases) == set(roles) and all(a > 0 and a % 4 == 0 for a in ordered) and
                all(b - a >= 4 * spec["words"] for a, b in zip(ordered, ordered[1:])) and
                (raw / "params.bin").read_bytes() == payload_bytes(operation, bases, n),
                "buffer addresses or parameter layout differ")
        values = {route: [] for route in ROUTES}
        for route in ROUTES:
            require(sha256(raw / (route + ".out.bin")) == expected, "saved output differs: " + route)
        for pair in range(warm + trials):
            order = ROUTES if pair % 2 == 0 else ROUTES[::-1]
            for position, route in enumerate(order):
                row = next(samples)
                require(row.get("operator", "vadd") == operation and
                        (row["n"], row["pair"], row["position"], row["route"], row["warmup"], row["output_sha256"]) ==
                        (n, pair, position, route, pair < warm, expected), "timing sample identity or bytes differ")
                boundaries = row["host_ns"]
                require(len(boundaries) == 5 and all(a < b for a, b in zip(boundaries, boundaries[1:])), "invalid host timing order")
                profiles = row["queue_profiles"]
                require(set(profiles) == set(stages), "unexpected timing stages")
                for stage in stages:
                    q, s, a, b = (profiles[stage][name] for name in PROFILE_FIELDS)
                    require(0 < q <= s <= a < b, "invalid event profile: " + stage)
                require(all(row[name] == value for name, value in timings(boundaries, profiles).items()), "derived timing differs")
                if pair >= warm:
                    values[route].append(row)
        metrics = (*METRICS, "h2d_profile_ns", "d2h_profile_ns")
        results[subdir.as_posix()] = dict(grid=spec["grid"], block=BLOCK, h2d_bytes=4 * len(roles) * spec["words"],
                               d2h_bytes=4 * spec["words"],
                               stats={r: {m: summary_stats([s[m] for s in values[r]]) for m in metrics} for r in ROUTES},
                               paired_ptx_minus_native={m: summary_stats([p[m] - v[m] for v, p in zip(values["native"], values["ptx"])])
                                                        for m in metrics})
    return dict(status="PASS", launches=count, measured=2 * workload_count * trials, cases=results,
                raw_sha256=sha256(out / "samples.jsonl"), capture_sha256=sha256(out / "capture.json"))


def board_review(bundle, run):
    receipt = review_capture(bundle, run, BOARD_BACKEND, run / "binding/binding.json", WARM, TRIALS)
    return dict(receipt, gate_sha256=review_gate(run))


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("action", choices=("prepare", "pilot", "run", "capture", "capture-pilot", "review"))
    cli.add_argument("--output", type=Path, required=True)
    cli.add_argument("--bundle", type=Path)
    cli.add_argument("--build", type=Path)
    cli.add_argument("--binding", type=Path)
    cli.add_argument("--lock", type=Path)
    cli.add_argument("--bdf", choices=["0000:" + bus + ":00.1" for bus in BUSES])
    args = cli.parse_args()
    run = args.output.resolve()
    bundle = args.bundle.resolve() if args.bundle else None
    require(re.fullmatch(r"(?:u280-perf-|c-v03-u280-perf-)[A-Za-z0-9_-]{1,48}", run.name), "invalid performance run ID")
    if args.action == "capture":
        capture(bundle, run, BOARD_BACKEND, run / "binding/binding.json", bundle / "modules", bundle / "target_lock.json", WARM, TRIALS)
        return 0
    if args.action == "capture-pilot":
        capture(bundle, run, "simx", args.binding, args.build / "sim", args.lock, *PILOT)
        return 0
    if args.action == "review":
        print(json.dumps(board_review(bundle, run)))
        return 0
    run.mkdir()
    report = dict(schema=SCHEMA, run_id=run.name, argv=[sys.executable, "-B", *sys.argv], status="RUNNING", commands=[],
                  started_at=utc_now(), board_execution="NOT_RUN", physical_recovery="NOT_RUN", timing7="OPEN")
    rec = Recorder(run, report, dict(os.environ))
    try:
        if args.action == "prepare":
            archive = prepare(run, args.build.resolve())
            report["schema"] = read_json(run / "bundle/plan.json")["schema"]
            report.update(archive=archive.name, archive_sha256=sha256(archive), plan_sha256=sha256(run / "bundle/plan.json"))
        else:
            plan = preflight(bundle)
            report["schema"] = plan["schema"]
            report["plan_sha256"] = sha256(bundle / "plan.json")
            child = [sys.executable, "-B", bundle / "scripts" / HERE.name]
            shared = ["--bundle", bundle, "--output", run]
            if args.action == "pilot":
                build = args.build.resolve()
                require(sha256(build / "summary.json") == plan["build_summary_sha256"], "pilot build differs")
                binding = BINDINGS / "simx/binding.json"
                for key in ("XCLBIN_PATH", "XCL_EMULATION_MODE", "VORTEX_CP_POLL_TIMEOUT_S"):
                    rec.env.pop(key, None)
                rec.env.update(VORTEX_DRIVER="simx", LD_LIBRARY_PATH=read_json(binding)["library_dir"], VORTEX_PROFILING="0")
                run_stage(rec, "pilot_simx", child + ["capture-pilot", *shared, "--binding", binding, "--build", build,
                                                      "--lock", SIM_LOCK], run, 240)
                report["receipt"] = review_capture(bundle, run, "simx", binding, *PILOT)
            else:
                require(args.bdf, "physical measurement requires --bdf")
                bind(bundle, run, args.bdf, rec)
                report["board_execution"] = "FAIL"
                run_stage(rec, "capture", child + ["capture", *shared], run, 900)
                report.update(receipt=board_review(bundle, run), board_execution="PASS")
        report.update(status="PASS", exit_code=0)
    except Exception as error:
        report.update(status="FAIL", exit_code=1, error=str(error))
    report["finished_at"] = utc_now()
    rec.save()
    print(report["status"], run, report.get("error", ""))
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
