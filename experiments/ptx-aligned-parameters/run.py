"""Measure bytewise and aligned PTX readers on the fixed SimX or RTL binding."""

import argparse
import ctypes as C
import json
import os
from pathlib import Path
import struct
import sys

from build import PROJECT, archives
from measure import COUNTERS, launch, snapshot
from check_c_v03_receipt import BINDINGS
from ptx_runtime import Context, Q
from run_native_smoke import Recorder, sha256, utc_now
from run_ptx_copy import SIM_LOCK, read_json, require, run_stage, write_json
from u280_perf_pair import ABI, GUARD, load_image, payload_bytes, preflight, workloads


ROUTES = ("bytewise", "aligned")
SCRATCH_ALIGNMENT = 64


def load(ctx, path, label):
    image = path.read_bytes()
    return load_image(ctx, C.create_string_buffer(image, len(image)), label)


def probe_alignment(ctx, build, args, layout, spec, handles, case):
    probe = load(ctx, build / "probe/kernel.vxbin", "address-probe")
    launch(ctx, probe, dict(spec, grid=1), args)
    observed = ctx.read(handles["x"], GUARD * 4, 16)
    ctx.unload(probe)
    (case / "address-probe.bin").write_bytes(observed)
    payload, mscratch = struct.unpack("<QQ", observed)
    require(payload == mscratch and payload > 0 and payload % SCRATCH_ALIGNMENT == 0,
            "device payload base differs from MSCRATCH or lacks allocation alignment")
    fields = {p["name"]: {"address": payload + p["offset"], "align": p["align"]} for p in layout["fields"]}
    require(all(field["address"] % field["align"] == 0 for field in fields.values()), "device field is misaligned")
    evidence = dict(status="PASS", payload_address=payload, mscratch=mscratch,
                    device_base_alignment=SCRATCH_ALIGNMENT, fields=fields,
                    length=len(args), params_sha256=sha256(case / "params.bin"),
                    readback_sha256=sha256(case / "address-probe.bin"))
    write_json(case / "alignment.json", evidence)
    print(case.name, "alignment", hex(payload), "bytes", len(args), flush=True)
    return evidence


def capture_case(ctx, bundle, build, report, work, out, repeats, output):
    op, spec, subdir = work
    n = spec["n"]
    case = out / op / str(n)
    case.mkdir(parents=True)
    frozen = bundle / "inputs" / subdir
    inputs = {name: (frozen / (name + ".bin")).read_bytes() for name in ABI[op][1]}
    expected_path = frozen / "expected.bin"
    expected = expected_path.read_bytes()
    input_hashes = {name: sha256(frozen / (name + ".bin")) for name in inputs}
    handles = {name: ctx.alloc(len(data)) for name, data in inputs.items()}
    bases = {}
    for name, handle in handles.items():
        address = Q()
        ctx.check(ctx.lib.vx_buffer_address(ctx.buffers[handle][0], C.byref(address)), "buffer_address")
        bases[name] = address.value
    args = payload_bytes(op, bases, n)
    layout = report["operators"][op]["layout"]
    require(len(args) == layout["bytes"], "payload length differs from module layout")
    (case / "params.bin").write_bytes(args)
    ctx.write(handles["x"], 0, inputs["x"])
    alignment = probe_alignment(ctx, build, args, layout, spec, handles, case)
    images = {route: build / op / route / "kernel.vxbin" for route in ROUTES}
    image_hashes = {route: sha256(path) for route, path in images.items()}
    require(all(image_hashes[route] == report["operators"][op]["variants"][route]["kernel.vxbin"] for route in ROUTES),
            "image hash disagrees with build receipt")
    for repeat in range(repeats):
        order = ROUTES if repeat % 2 == 0 else ROUTES[::-1]
        for position, route in enumerate(order):
            module = load(ctx, images[route], route)
            for name, data in inputs.items():
                ctx.write(handles[name], 0, data)
            idle, before = snapshot(ctx), snapshot(ctx)
            require(idle == before, "counter moved during idle window")
            launch(ctx, module, spec, args)
            after = snapshot(ctx)
            actual = ctx.read(handles["z"], 0, len(expected))
            ctx.unload(module)
            captured = case / ("{}-{}.bin".format(route, repeat))
            captured.write_bytes(actual)
            require(actual == expected, "output or sentinel mismatch: " + str(captured))
            delta = {key: after[key] - before[key] for key in COUNTERS}
            require(min(delta.values()) >= 0 and delta["cycles"] > 0 and delta["instret"] > 0,
                    "invalid active counter delta")
            row = dict(operator=op, **spec, route=route, repeat=repeat, position=position,
                       image_sha256=image_hashes[route], inputs=input_hashes, params_sha256=alignment["params_sha256"],
                       alignment_sha256=sha256(case / "alignment.json"), output_sha256=sha256(captured),
                       expected_sha256=sha256(expected_path), idle=idle, before=before, after=after, delta=delta)
            output.write(json.dumps(row) + "\n")
            output.flush()
            print(op, n, route, repeat, delta["cycles"], delta["instret"], flush=True)
    for handle in handles.values():
        ctx.free(handle)


def worker(out, backend, build, repeats):
    report = read_json(build / "summary.json")
    require(report["status"] == "PASS" and report["exit_code"] == 0 and report["lock_sha256"] == sha256(SIM_LOCK),
            "requires successful model-only build")
    require(sha256(build / "probe/kernel.vxbin") == report["probe"]["kernel.vxbin"], "probe image changed")
    binding = BINDINGS / backend / "binding.json"
    launches = 0
    with (out / "samples.jsonl").open("x", encoding="utf-8") as stream:
        for bundle, archive in archives():
            plan = preflight(bundle)
            require(plan["build_summary_sha256"] == sha256(archive / "summary.json"), "archive build identity differs")
            ctx = Context(binding, SIM_LOCK, backend=backend, run_id=out.name)
            try:
                vm = Q()
                ctx.check(ctx.lib.vx_device_query(ctx.device, 0xF, C.byref(vm)), "query_vm")
                require(vm.value == 0, "alignment audit is scoped to the no-VM D5 bindings")
                for item in workloads(plan):
                    capture_case(ctx, bundle, build, report, item, out, repeats, stream)
                    launches += 2 * repeats
            finally:
                if ctx.state == "READY":
                    ctx.close()
    write_json(out / "capture.json", dict(status="PASS", exit_code=0, samples=launches, vm_support=0,
                                         probes=launches // (2 * repeats), counter_map=COUNTERS,
                                         binding_sha256=sha256(binding), build_summary_sha256=sha256(build / "summary.json")))


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--output", type=Path, required=True)
    cli.add_argument("--build", type=Path, required=True)
    cli.add_argument("--backend", choices=("simx", "rtlsim"), required=True)
    cli.add_argument("--repeats", type=int, default=4)
    cli.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = cli.parse_args()
    out, build = args.output.resolve(), args.build.resolve()
    require(out.parent == PROJECT / "results" and args.repeats > 0 and args.repeats % 2 == 0,
            "use a new results directory and an even number of paired repetitions")
    if args.worker:
        worker(out, args.backend, build, args.repeats)
        return 0
    out.mkdir()
    env = {key: value for key, value in os.environ.items() if key not in
           ("XCLBIN_PATH", "XCL_EMULATION_MODE", "VORTEX_CP_POLL_TIMEOUT_S")}
    binding = read_json(BINDINGS / args.backend / "binding.json")
    env.update(VORTEX_DRIVER=args.backend, LD_LIBRARY_PATH=binding["library_dir"], VORTEX_PROFILING="0")
    report = dict(status="RUNNING", board_execution="NOT_RUN", backend=args.backend, repeats=args.repeats,
                  commands=[], started_at=utc_now(), script_sha256=sha256(__file__), argv=[sys.executable, "-B", *sys.argv])
    rec = Recorder(out, report, env)
    try:
        run_stage(rec, args.backend, [sys.executable, "-B", Path(__file__).resolve(), "--output", out, "--build", build,
                                     "--backend", args.backend, "--repeats", str(args.repeats), "--worker"], out, 1200)
        report.update(status="PASS", exit_code=0)
    except Exception as error:
        report.update(status="FAIL", exit_code=1, error=str(error))
    report["finished_at"] = utc_now()
    rec.save()
    print(report["status"], out, report.get("error", ""))
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
