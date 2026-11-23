"""Replay the archived native/PTX pairs and measure per-launch GPU counters."""

import argparse
import ctypes as C
import json
import os
from pathlib import Path
import sys


PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "scripts"))

from check_c_v03_receipt import BINDINGS
from ptx_runtime import Context, LaunchInfo, P, Q, U
from run_native_smoke import Recorder, sha256, utc_now
from run_ptx_copy import SIM_LOCK, read_json, require, run_stage, write_json
from u280_perf_pair import ABI, ROUTES, load_image, operator_path, payload_bytes, preflight, validate_images, workloads


ARCHIVES = ("20261121-v1", "copy-affine-20261121-v1")
COUNTERS = {
    "cycles": (0, 0xB00), "instret": (0, 0xB02),
    "scoreboard_stalls": (1, 0xB0A), "branches": (1, 0xB11),
    "divergence": (1, 0xB12), "alu": (1, 0xB13), "lsu": (1, 0xB15),
    "sfu": (1, 0xB16), "ifetch": (1, 0xB1A), "loads": (1, 0xB1C),
    "load_latency": (1, 0xB1D), "stores": (1, 0xB1E),
}


def snapshot(ctx):
    counts = {}
    for name, (group, address) in COUNTERS.items():
        value = Q()
        ctx.check(ctx.lib.vx_device_mpm_query(ctx.device, group, address, 0, C.byref(value)), "mpm_" + name)
        counts[name] = value.value
    return counts


def launch(ctx, module, spec, args):
    payload = C.create_string_buffer(args, len(args))
    info = LaunchInfo()
    info.struct_size, info.kernel = C.sizeof(info), module.kernel
    info.args_host, info.args_size = C.cast(payload, P), len(args)
    info.ndim = 1
    info.grid_dim, info.block_dim = (U * 3)(spec["grid"], 1, 1), (U * 3)(spec["block"], 1, 1)
    event = P()
    ctx.check(ctx.lib.vx_enqueue_launch(ctx.queue, C.byref(info), 0, None, C.byref(event)), "launch")
    ctx.check(ctx.lib.vx_event_wait_value(event, 1, ctx.timeout_ns(120000)), "wait_launch")
    ctx.check(ctx.lib.vx_event_release(event), "release_launch")


def capture_case(ctx, bundle, plan, modules, operation, spec, subdir, out, repeats, stream):
    n = spec["n"]
    case = out / operation / str(n)
    case.mkdir(parents=True)
    frozen = bundle / "inputs" / subdir
    inputs = {role: (frozen / (role + ".bin")).read_bytes() for role in ABI[operation][1]}
    expected_file = frozen / "expected.bin"
    expected = expected_file.read_bytes()
    images = {route: operator_path(plan, modules, operation) / route / "kernel.vxbin" for route in ROUTES}
    handles = {role: ctx.alloc(len(data)) for role, data in inputs.items()}
    bases = {}
    for role, handle in handles.items():
        address = Q()
        ctx.check(ctx.lib.vx_buffer_address(ctx.buffers[handle][0], C.byref(address)), "buffer_address")
        bases[role] = address.value
    args = payload_bytes(operation, bases, n)
    (case / "params.bin").write_bytes(args)

    for repeat in range(repeats):
        order = ROUTES if repeat % 2 == 0 else ROUTES[::-1]
        for position, route in enumerate(order):
            path = images[route]
            raw = path.read_bytes()
            module = load_image(ctx, C.create_string_buffer(raw, len(raw)), route)
            for role, data in inputs.items():
                ctx.write(handles[role], 0, data)
            idle = snapshot(ctx)
            before = snapshot(ctx)
            require(before == idle, "counter moved with the device idle: {} {} {}".format(operation, n, route))
            launch(ctx, module, spec, args)
            after = snapshot(ctx)
            actual = ctx.read(handles["z"], 0, len(expected))
            ctx.unload(module)
            target = case / ("{}-{}.bin".format(route, repeat))
            target.write_bytes(actual)
            require(actual == expected, "output or sentinel differs: " + str(target))
            delta = {name: after[name] - before[name] for name in COUNTERS}
            require(min(delta.values()) >= 0 and delta["cycles"] > 0 and delta["instret"] > 0,
                    "invalid counter delta: " + str(delta))
            row = dict(operator=operation, n=n, block=spec["block"], grid=spec["grid"], route=route,
                       repeat=repeat, position=position, image_sha256=sha256(path),
                       inputs={role: sha256(frozen / (role + ".bin")) for role in inputs},
                       params_sha256=sha256(case / "params.bin"), output_sha256=sha256(target),
                       expected_sha256=sha256(expected_file), idle=idle, before=before, after=after, delta=delta)
            stream.write(json.dumps(row) + "\n")
            stream.flush()
            print(operation, n, route, repeat, delta, flush=True)
    for handle in handles.values():
        ctx.free(handle)


def worker(run, backend, repeats):
    out = run / backend
    out.mkdir()
    binding = BINDINGS / backend / "binding.json"
    evidence = {"binding_sha256": sha256(binding), "lock_sha256": sha256(SIM_LOCK), "archives": {}}
    with (out / "samples.jsonl").open("x", encoding="utf-8") as stream:
        for suffix in ARCHIVES:
            bundle = PROJECT / "results" / ("u280-perf-kit-" + suffix) / "bundle"
            build = PROJECT / "results" / ("u280-perf-build-" + suffix)
            plan = preflight(bundle)
            require(sha256(build / "summary.json") == plan["build_summary_sha256"], "build identity differs")
            modules = build / "sim"
            validate_images(modules, SIM_LOCK, plan)
            evidence["archives"][suffix] = {"plan_sha256": sha256(bundle / "plan.json"),
                                            "build_summary_sha256": sha256(build / "summary.json")}
            ctx = Context(binding, SIM_LOCK, backend=backend, run_id=run.name)
            evidence["caps"] = ctx.caps
            try:
                for operation, spec, subdir in workloads(plan):
                    capture_case(ctx, bundle, plan, modules, operation, spec, subdir, out, repeats, stream)
            finally:
                if ctx.state == "READY":
                    ctx.close()
    evidence.update(status="PASS", exit_code=0, samples=12 * repeats, counter_map=COUNTERS)
    write_json(out / "capture.json", evidence)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--backend", choices=("simx", "rtlsim"), required=True)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    run = args.output.resolve()
    require(run.parent == PROJECT / "results" and args.repeats > 0, "use a new results directory and positive repeats")
    if args.worker:
        worker(run, args.backend, args.repeats)
        return 0
    run.mkdir()
    env = {key: value for key, value in os.environ.items() if key not in
           ("XCLBIN_PATH", "XCL_EMULATION_MODE", "VORTEX_CP_POLL_TIMEOUT_S")}
    binding = read_json(BINDINGS / args.backend / "binding.json")
    env.update(VORTEX_DRIVER=args.backend, LD_LIBRARY_PATH=binding["library_dir"], VORTEX_PROFILING="0")
    report = dict(status="RUNNING", started_at=utc_now(), board_execution="NOT_RUN",
                  backend=args.backend, repeats=args.repeats, commands=[])
    recorder = Recorder(run, report, env)
    try:
        command = [sys.executable, "-B", Path(__file__).resolve(), "--output", run,
                   "--backend", args.backend, "--repeats", str(args.repeats), "--worker"]
        run_stage(recorder, args.backend, command, run, 1200)
        report.update(status="PASS", exit_code=0)
    except Exception as error:
        report.update(status="FAIL", exit_code=1, error=str(error))
    report["finished_at"] = utc_now()
    recorder.save()
    print(report["status"], run, report.get("error", ""))
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
