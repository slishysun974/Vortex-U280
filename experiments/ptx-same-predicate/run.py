"""Isolated comparison of consecutive same-predicate regions in three aligned PTX samples."""

import argparse
import ctypes as C
import difflib
import json
import os
from pathlib import Path
import re
import shutil
import sys

PROJECT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(PROJECT / path) for path in (
    "scripts", "experiments/ptx-performance-attribution", "experiments/ptx-aligned-parameters",
    "experiments/ptx-aligned-production")]

from build import compile_device
from check_c_v03_receipt import BINDINGS, TOOLCHAIN
from measure import COUNTERS, snapshot
from ptx_module import ALIGNED_PARAMETER_ACCESS, validate
from ptx_runtime import Context, LaunchInfo, P, Q, U, VX_CAPS_VM_SUPPORT
from run_native_smoke import Recorder, sha256, utc_now
from run_ptx_copy import SIM_LOCK, VORTEX, read_json, require, run_stage, write_json
from u280_perf_pair import ABI, load_image, payload_bytes, validate_ptx_layout, workloads
from validate import performance_bundles


FORMAL = PROJECT / "results/local-ptx-aligned-production-build-20261121-v1"
BACKENDS = ("simx", "rtlsim")
ROUTES = ("aligned", "merged")
TRIALS = 4
READ, WRITE = "ld.global.u32", "st.global.u32"
REGIONS = {
    "copy": (READ, WRITE),
    "vadd": (READ, READ, "add.u32", WRITE),
    "affine": (READ, READ, "mul.lo.u32", "add.u32", WRITE),
}


def merge_region(op, baseline):
    ir = read_json(baseline / "ir.json")["instructions"]
    length = len(REGIONS[op])
    region = ir[-length-1:-1]
    require(tuple(ins["opcode"] for ins in region) == REGIONS[op] and ir[-1]["opcode"] == "ret",
            "unexpected PTX suffix")
    guard = region[0]["predicate"]
    require(guard and all(ins["predicate"] == guard for ins in region), "different PTX predicates")
    # The exact opcode list excludes predicate writes. The formal emitter has
    # already been validated against the IR and source map by ptx_module.
    locations = read_json(baseline / "source_map.json")
    rows = [row["generated_line"] - 1 for row in locations
            if any(ins["source_location"]["line"] == row["line"] for ins in region)]
    require(len(rows) == length and rows == list(range(rows[0], rows[0] + length)),
            "guarded statements are not consecutive")
    header = (baseline / "kernel_body.hpp").read_bytes().decode()
    original = header.splitlines(keepends=True)
    statements = [re.fullmatch(r"  if \((!?v\d+)\) \{ (.+;) \}\n", original[row]) for row in rows]
    require(all(statements) and len({match[1] for match in statements}) == 1, "different generated guards")
    body = [match[2] for match in statements]
    first, end = rows[0], rows[-1] + 1
    merged = original[:first] + [f"  if ({statements[0][1]}) {{\n"]
    merged.extend(f"    {line}\n" for line in body)
    merged.extend(["  }\n", *original[end:]])
    return header, "".join(merged)


def build_variants(out, rec):
    archived = read_json(FORMAL / "summary.json")
    require(archived["status"] == "PASS" and archived["exit_code"] == 0, "formal baseline unavailable")
    lock = SIM_LOCK.read_bytes()
    root = PROJECT / "build" / out.name
    root.mkdir()
    cli = [sys.executable, "-B", PROJECT / "scripts/ptx_module.py"]
    rec.summary.update(formal_summary_sha256=sha256(FORMAL / "summary.json"), lock_sha256=sha256(SIM_LOCK), operators={})
    for op in REGIONS:
        archive = FORMAL / "modules" / op
        old, old_image = validate(archive, lock)
        validate_ptx_layout(old, op)
        require(old["device_parameter_access"] == ALIGNED_PARAMETER_ACCESS and
                old["image_sha256"] == archived["modules"][op]["image"], "archived aligned identity differs")
        work = out / op
        work.mkdir()
        aligned, merged = (work / route for route in ROUTES)
        native_root = root / op
        run_stage(rec, op + "_prepare", cli + ["prepare", archive / "source.ptx", "--output", aligned,
                  "--hardware", SIM_LOCK.with_name("native_smoke.json"), "--device-parameter-access",
                  ALIGNED_PARAMETER_ACCESS, "--target-lock", SIM_LOCK], out, 180)
        run_stage(rec, op + "_build", cli + ["build", aligned, "--build-root", native_root,
                  "--vortex-source", VORTEX, "--tooldir", TOOLCHAIN, "--target-lock", SIM_LOCK], out, 420)
        formal, image = validate(aligned, lock)
        require(image == old_image and all((archive / name).read_bytes() == (aligned / name).read_bytes()
                for name in ("source.ptx", "ir.json", "abi.json", "kernel.cpp", "Makefile", "kernel_body.hpp")),
                "fresh formal baseline differs from the aligned archive")
        header, variant = merge_region(op, aligned)
        merged.mkdir()
        for name in ("kernel.cpp", "Makefile"):
            shutil.copyfile(aligned / name, merged / name)
        (merged / "kernel_body.hpp").write_bytes(variant.encode())
        patch = difflib.unified_diff(header.splitlines(keepends=True), variant.splitlines(keepends=True),
                                     "aligned/kernel_body.hpp", "merged/kernel_body.hpp")
        (work / "same-predicate.diff").write_bytes("".join(patch).encode())
        build_record = read_json(aligned / "build.json")
        flags, = [arg for arg in build_record["commands"][-1]["argv"] if arg.startswith("CONFIGS=")]
        variant_files = compile_device(merged, native_root, flags, rec, op + "_merged")
        require(all(variant_files[name] == sha256(aligned / name) for name in ("kernel.cpp", "Makefile")),
                "wrapper or compiler rules changed")
        rec.summary["operators"][op] = dict(aligned_image=formal["image_sha256"], merged_image=variant_files["kernel.vxbin"],
            merged_files=variant_files, source=old["source_sha256"], diff_sha256=sha256(work / "same-predicate.diff"))


def cases():
    for bundle, _, plan in performance_bundles():
        for op, spec, subdir in workloads(plan):
            yield op, spec, bundle / "inputs" / subdir


def context(binding, backend, out):
    ctx = Context(binding, SIM_LOCK, backend=backend, run_id=out.name)
    vm = Q()
    ctx.check(ctx.lib.vx_device_query(ctx.device, VX_CAPS_VM_SUPPORT, C.byref(vm)), "query_vm")
    require(vm.value == 0, "aligned queue launch requires disabled VM")
    return ctx


def build_receipt(built):
    report = read_json(built / "summary.json")
    require(report["status"] == "PASS" and report["exit_code"] == 0 and report["lock_sha256"] == sha256(SIM_LOCK),
            "paired build did not pass")
    return report["operators"]


def images(built, op, record):
    paths = {route: built / op / route / "kernel.vxbin" for route in ROUTES}
    require(all(sha256(path) == record[route + "_image"] for route, path in paths.items()), "build image differs")
    return paths


def buffers_for(ctx, frozen, op, spec):
    inputs = {role: (frozen / (role + ".bin")).read_bytes() for role in ABI[op][1]}
    expected = (frozen / "expected.bin").read_bytes()
    require(all(len(data) == len(expected) == 4 * spec["words"] for data in inputs.values()), "bad input shape")
    handles = {role: ctx.alloc(len(data)) for role, data in inputs.items()}
    bases = {}
    for role, handle in handles.items():
        value = Q()
        ctx.check(ctx.lib.vx_buffer_address(ctx.buffers[handle][0], C.byref(value)), "buffer_address")
        bases[role] = value.value
    return inputs, expected, handles, bases


def launch(ctx, module, spec, args, timeout_ms):
    payload = C.create_string_buffer(args, len(args))
    info = LaunchInfo()
    info.struct_size, info.kernel = C.sizeof(info), module.kernel
    info.args_host, info.args_size = C.cast(payload, P), len(args)
    info.ndim = 1
    info.grid_dim, info.block_dim = (U * 3)(spec["grid"], 1, 1), (U * 3)(spec["block"], 1, 1)
    event = P()
    ctx.check(ctx.lib.vx_enqueue_launch(ctx.queue, C.byref(info), 0, None, C.byref(event)), "launch")
    ctx.check(ctx.lib.vx_event_wait_value(event, 1, ctx.timeout_ns(timeout_ms)), "wait_launch")
    ctx.check(ctx.lib.vx_event_release(event), "release_launch")


def invoke(ctx, path, spec, payload, inputs, handles, out, trace=False):
    image = path.read_bytes()
    module = load_image(ctx, C.create_string_buffer(image, len(image)), path.parent.name)
    for role, data in inputs.items():
        ctx.write(handles[role], 0, data)
    if trace:
        libc = C.CDLL(None)
        require(libc.fflush(None) == 0, "failed to flush prelaunch native trace")
        print("LSU_TRACE_BEGIN", flush=True)
    else:
        idle, before = snapshot(ctx), snapshot(ctx)
        require(idle == before, "core counters moved while idle")
    launch(ctx, module, spec, payload, 360000 if trace else 120000)
    if trace:
        require(libc.fflush(None) == 0, "failed to flush native launch trace")
        print("LSU_TRACE_END", flush=True)
    else:
        after = snapshot(ctx)
    captures = {}
    for role, data in inputs.items():
        value = ctx.read(handles[role], 0, len(data))
        destination = out / (role + ".bin")
        destination.write_bytes(value)
        if role != "z":
            require(value == data, "input buffer changed: " + str(destination))
        captures[role] = sha256(destination)
    ctx.unload(module)
    if trace:
        return captures
    delta = {key: after[key] - before[key] for key in COUNTERS}
    require(min(delta.values()) >= 0 and min(delta["cycles"], delta["instret"]) > 0, "invalid counter delta")
    return dict(idle=idle, before=before, after=after, delta=delta, captures=captures)


def performance_worker(out, backend, built):
    report = build_receipt(built)
    ctx = context(BINDINGS / backend / "binding.json", backend, out)
    try:
        with (out / "samples.jsonl").open("x", encoding="utf-8") as samples:
            for op, spec, frozen in cases():
                directory = out / op / str(spec["n"])
                directory.mkdir(parents=True)
                paths = images(built, op, report[op])
                inputs, expected, handles, bases = buffers_for(ctx, frozen, op, spec)
                payload = payload_bytes(op, bases, spec["n"])
                (directory / "params.bin").write_bytes(payload)
                write_json(directory / "bases.json", bases)
                for pair in range(TRIALS):
                    order = ROUTES if pair % 2 == 0 else ROUTES[::-1]
                    for position, route in enumerate(order):
                        trial = directory / (route + "-" + str(pair))
                        trial.mkdir()
                        row = invoke(ctx, paths[route], spec, payload, inputs, handles, trial)
                        require((trial / "z.bin").read_bytes() == expected, "full output differs: " + str(trial))
                        row.update(operator=op, **spec, pair=pair, position=position, route=route,
                                   params_sha256=sha256(directory / "params.bin"), image_sha256=sha256(paths[route]))
                        samples.write(json.dumps(row) + "\n")
                        samples.flush()
                        print(op, spec["n"], route, pair, row["delta"]["cycles"], row["delta"]["instret"], flush=True)
                for handle in handles.values():
                    ctx.free(handle)
    finally:
        if ctx.state == "READY":
            ctx.close()


def binding_env(rec, binding):
    info = read_json(binding)
    rec.env.update(VORTEX_DRIVER=info["driver"], LD_LIBRARY_PATH=info["library_dir"], VORTEX_PROFILING="0")


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("action", choices=("build", "measure", "worker"))
    cli.add_argument("--output", type=Path, required=True)
    cli.add_argument("--build", type=Path)
    cli.add_argument("--backend", choices=BACKENDS)
    args = cli.parse_args()
    out = args.output.resolve()
    require(out.parent == PROJECT / "results" and out.name.startswith("local-ptx-same-predicate-"),
            "use a new local results directory")
    if args.action != "build" and not (args.backend and args.build):
        cli.error("--backend and --build are required for measurement")
    if args.action == "worker":
        performance_worker(out, args.backend, args.build.resolve())
        return 0
    out.mkdir()
    report = dict(status="RUNNING", board_execution="NOT_RUN", afu_execution="NOT_RUN", commands=[],
                  started_at=utc_now(), argv=[sys.executable, "-B", *sys.argv], script_sha256=sha256(__file__))
    env = {key: value for key, value in os.environ.items()
           if key not in ("XCLBIN_PATH", "XCL_EMULATION_MODE", "VORTEX_CP_POLL_TIMEOUT_S")}
    rec = Recorder(out, report, env)
    try:
        if args.action == "build":
            build_variants(out, rec)
        else:
            built = args.build.resolve()
            binding = BINDINGS / args.backend / "binding.json"
            binding_env(rec, binding)
            report.update(backend=args.backend, binding_sha256=sha256(binding), trials=TRIALS,
                          build_sha256=sha256(built / "summary.json"))
            run_stage(rec, args.backend, [sys.executable, "-B", Path(__file__).resolve(), "worker", "--build", built,
                      "--backend", args.backend, "--output", out], out, 1200)
        report.update(status="PASS", exit_code=0)
    except Exception as error:
        report.update(status="FAIL", exit_code=1, error=str(error))
    report["finished_at"] = utc_now()
    rec.save()
    print(report["status"], out, report.get("error", ""))
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
