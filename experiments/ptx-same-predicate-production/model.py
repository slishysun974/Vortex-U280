"""Exercise formal P0/V03 modules and paired performance through Context."""

import argparse
import ctypes as C
import json
import os
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(PROJECT / name) for name in (
    "scripts", "experiments/ptx-aligned-production", "experiments/ptx-performance-attribution")]

import ptx_frontend_v14 as codegen
from check_c_v03_receipt import BINDINGS, FORMS
from measure import COUNTERS, snapshot
from ptx_runtime import BufferSlice, Context, Q
from run_d_p0_closeout import CASES, SOURCE, source_checks, stage
from run_native_smoke import Recorder, sha256, utc_now
from run_ptx_copy import SIM_LOCK, read_json, require, run_stage, write_json
from run_ptx_suite import launch_args
from u280_perf_pair import ABI, ALPHA, GUARD, payload_bytes, workloads
from validate import BACKENDS, OPS, TRIALS, performance_bundles, witness


FORMAL = PROJECT / "results/local-ptx-aligned-production-build-20261121-v1"
ROUTES = ("aligned", "merged")
P0_COUNT = dict(copy=168, vadd=168, affine=504)


def receipt(built):
    report = read_json(built / "summary.json")
    require(report["status"] == "PASS" and report["exit_code"] == 0 and report["lock_sha256"] == sha256(SIM_LOCK),
            "formal build has not passed")
    return report["modules"]


def workloads_from_kits():
    for bundle, _, plan in performance_bundles():
        for op, spec, subdir in workloads(plan):
            yield op, spec, bundle / "inputs" / subdir


def stage_forms(out, backend, built, info):
    out.mkdir()
    path = built / "modules" / FORMS
    require((path / "source.ptx").read_bytes() == SOURCE.read_bytes(), "P0 form witness bytes differ")
    report = dict(cases={})
    ir = source_checks(path, report, codegen)
    ctx = Context(BINDINGS / backend / "binding.json", SIM_LOCK, backend=backend, run_id=out.name)
    try:
        module = ctx.load(path)
        require(module.manifest["image_sha256"] == info[FORMS]["merged_image"], "P0 form image differs")
        for cid, rotation in zip(CASES, (0, 2)):
            directory = out / cid
            spec = stage(directory, ir, module.manifest["native_entry"], rotation)
            size = spec["words"] * 4
            handles = {role: ctx.alloc(size) for role in ("x", "z")}
            for role, handle in handles.items():
                ctx.write(handle, 0, (directory / "inputs" / f"{cid}_{role}.bin").read_bytes())
            # Match the fixed 32-byte pointer offset of the existing P0 matrix.
            args = [BufferSlice(handles[role], 32, size - 32, access) for role, access in (("x", "r"), ("z", "w"))]
            event = ctx.launch(module, FORMS, (spec["grid"], 1, 1), (spec["block"], 1, 1), args + [spec["bias"]])
            (directory / "params.bin").write_bytes(event.plan.payload)
            write_json(directory / "event.json", ctx.wait(event))
            hashes = {}
            for role, handle in handles.items():
                actual = directory / (role + ".bin")
                actual.write_bytes(ctx.read(handle, 0, size))
                require(actual.read_bytes() == (directory / "expected" / f"{cid}_{role}.bin").read_bytes(),
                        "P0 form witness output differs: " + cid)
                hashes[role] = sha256(actual)
                ctx.free(handle)
            report["cases"][cid] = dict(status="PASS", arrays=hashes)
        ctx.unload(module)
    finally:
        if ctx.state == "READY":
            ctx.close()
    report.update(status="PASS", exit_code=0, image_sha256=info[FORMS]["merged_image"])
    write_json(out / "summary.json", report)


def measure_case(ctx, out, built, op, spec, frozen, info, stream):
    n, size = spec["n"], 4 * spec["words"]
    roles = ABI[op][1]
    inputs = {role: (frozen / (role + ".bin")).read_bytes() for role in roles}
    expected = dict(inputs, z=(frozen / "expected.bin").read_bytes())
    handles = {role: ctx.alloc(size) for role in roles}
    bases = {}
    for role in roles:
        base = Q()
        ctx.check(ctx.lib.vx_buffer_address(ctx.buffers[handles[role]][0], C.byref(base)), "buffer_address")
        bases[role] = base.value
    payload = payload_bytes(op, bases, n)
    (out / "params.bin").write_bytes(payload)
    write_json(out / "bases.json", bases)
    args = launch_args(op, [handles[role] for role in roles], GUARD, n, ALPHA)
    for pair in range(TRIALS):
        order = ROUTES if pair % 2 == 0 else ROUTES[::-1]
        for position, route in enumerate(order):
            path = (FORMAL if route == "aligned" else built) / "modules" / op
            module = ctx.load(path)
            manifest = module.manifest
            require(manifest["image_sha256"] == info[route + "_image"] and manifest.get("predicate_lowering") ==
                    (codegen.PREDICATE_LOWERING if route == "merged" else None), "timed image differs")
            for role, data in inputs.items():
                ctx.write(handles[role], 0, data)
            idle, before = snapshot(ctx), snapshot(ctx)
            require(idle == before, "counter moved while idle")
            event = ctx.launch(module, manifest["entry"], (spec["grid"], 1, 1), (spec["block"], 1, 1), args)
            require(event.plan.payload == C.string_at(event.payload, len(payload)) == payload, "launch payload differs")
            ctx.wait(event, 120000)
            after = snapshot(ctx)
            captures = {}
            trial = out / f"{route}-{pair}"
            trial.mkdir()
            for role in roles:
                result = ctx.read(handles[role], 0, size)
                capture = trial / (role + ".bin")
                capture.write_bytes(result)
                require(result == expected[role], "full array or sentinel differs: " + str(capture))
                captures[role] = sha256(capture)
            ctx.unload(module)
            delta = {name: after[name] - before[name] for name in COUNTERS}
            require(min(delta.values()) >= 0 and min(delta["cycles"], delta["instret"]) > 0, "invalid counter delta")
            row = dict(operator=op, **spec, route=route, pair=pair, position=position, idle=idle, before=before,
                       after=after, delta=delta, params_sha256=sha256(out / "params.bin"), captures=captures,
                       image_sha256=manifest["image_sha256"])
            stream.write(json.dumps(row) + "\n")
            stream.flush()
            print(op, n, route, pair, delta["cycles"], delta["instret"], flush=True)
    for handle in handles.values():
        ctx.free(handle)


def worker(out, backend, built):
    info = receipt(built)
    stage_forms(out / "p0-forms", backend, built, info)
    witness(out, backend, built)
    perf = out / "performance"
    perf.mkdir()
    ctx = Context(BINDINGS / backend / "binding.json", SIM_LOCK, backend=backend, run_id=out.name)
    try:
        with (perf / "samples.jsonl").open("x", encoding="utf-8") as stream:
            for op, spec, frozen in workloads_from_kits():
                directory = perf / op / str(spec["n"])
                directory.mkdir(parents=True)
                measure_case(ctx, directory, built, op, spec, frozen, info[op], stream)
    finally:
        if ctx.state == "READY":
            ctx.close()


def model(out, rec, backend, built):
    info = receipt(built)
    binding = BINDINGS / backend / "binding.json"
    env = read_json(binding)
    rec.env.update(VORTEX_DRIVER=env["driver"], LD_LIBRARY_PATH=env["library_dir"], VORTEX_PROFILING="0")
    rec.summary.update(binding_sha256=sha256(binding), build_sha256=sha256(built / "summary.json"), suites={})
    for op in OPS:
        module = built / "modules" / op
        require(sha256(module / "manifest.json") == info[op]["manifest_sha256"], "P0 module manifest differs")
        root = out / ("suite-" + op)
        run_stage(rec, "p0_suite_" + op, [sys.executable, "-B", PROJECT / "scripts/run_ptx_suite.py",
                  "--kernel", op, "--backend", backend, "--module", module, "--binding", binding,
                  "--target-lock", SIM_LOCK, "--output", root], out, 1200)
        result = read_json(root / "result.json")
        require(result["status"] == "PASS" and result["exit_code"] == 0 and result["passed"] == P0_COUNT[op]
                and len(result["rejections"]) == 19 and result["recovery"]["status"] == "PASS", "incomplete P0 suite")
        rec.summary["suites"][op] = dict(passed=result["passed"], rejections=len(result["rejections"]),
            recovery=result["recovery"]["status"], sha256=sha256(root / "result.json"))
    run_stage(rec, "forms_v03_and_performance", [sys.executable, "-B", Path(__file__).resolve(), "--worker",
              "--backend", backend, "--build", built, "--output", out], out, 1200)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--backend", choices=BACKENDS, required=True)
    cli.add_argument("--build", type=Path, required=True)
    cli.add_argument("--output", type=Path, required=True)
    cli.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = cli.parse_args()
    out, built = args.output.resolve(), args.build.resolve()
    require(out.parent == PROJECT / "results" and out.name.startswith("local-ptx-same-predicate-production-"),
            "choose a new formal model run")
    if args.worker:
        worker(out, args.backend, built)
        return 0
    out.mkdir()
    env = {key: value for key, value in os.environ.items()
           if key not in ("XCLBIN_PATH", "XCL_EMULATION_MODE", "VORTEX_CP_POLL_TIMEOUT_S")}
    report = dict(status="RUNNING", backend=args.backend, commands=[], started_at=utc_now(),
                  argv=[sys.executable, "-B", *sys.argv], board_execution="NOT_RUN", afu_execution="NOT_RUN")
    rec = Recorder(out, report, env)
    try:
        model(out, rec, args.backend, built)
        report.update(status="PASS", exit_code=0)
    except Exception as error:
        report.update(status="FAIL", exit_code=1, error=str(error))
    report["finished_at"] = utc_now()
    rec.save()
    print(report["status"], out, report.get("error", ""))
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
