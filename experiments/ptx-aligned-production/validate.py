"""Validate the formal aligned PTX module through production Context entry points."""

import argparse
import ctypes as C
import json
import os
from pathlib import Path
from statistics import median
import sys


PROJECT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(PROJECT / "scripts"), str(PROJECT / "experiments/ptx-performance-attribution")]

from ae_v03_execute import alias_check, run_case
from build_ae_v03 import frozen_manifest
from check_c_v03_receipt import BINDINGS, FORMS, TOOLCHAIN, WIDE
from measure import ARCHIVES, COUNTERS, snapshot
from ptx_module import ALIGNED_PARAMETER_ACCESS, validate
from ptx_runtime import Context, Q
from run_native_smoke import Recorder, sha256, utc_now
from run_ptx_copy import SIM_LOCK, VORTEX, read_json, require, run_stage, write_json
from run_ptx_suite import launch_args
from u280_perf_pair import ABI, ALPHA, GUARD, operator_path, payload_bytes, preflight, workloads


OPS = ("copy", "vadd", "affine")
BACKENDS = ("simx", "rtlsim")
ROUTES = ("bytewise", "aligned")
FROZEN = PROJECT / "results/ae-v03-frozen-20261121-v1"
TRIALS = 4


def performance_bundles():
    for suffix in ARCHIVES:
        bundle = PROJECT / "results" / ("u280-perf-kit-" + suffix) / "bundle"
        archive = PROJECT / "results" / ("u280-perf-build-" + suffix)
        plan = preflight(bundle)
        require(plan["build_summary_sha256"] == sha256(archive / "summary.json"), "archived performance build differs")
        yield bundle, archive, plan


def build(out, rec):
    baseline = {}
    sources = {name: FROZEN / "sources" / (name + ".ptx") for name in (FORMS, WIDE)}
    frozen_manifest(FROZEN)
    for _, archive, plan in performance_bundles():
        for op, _, _ in workloads(plan):
            path = operator_path(plan, archive / "sim", op) / "ptx"
            sources[op] = path / "source.ptx"
            baseline[op] = path
    modules = {}
    cli = [sys.executable, "-B", PROJECT / "scripts/ptx_module.py"]
    isolated = PROJECT / "results/local-ptx-align-build-20261121-v1"
    experiment = read_json(isolated / "summary.json")
    for name, source in sources.items():
        path = out / "modules" / name
        for action, args in (
                ("prepare", [source, "--output", path, "--hardware", SIM_LOCK.with_name("native_smoke.json"),
                             "--device-parameter-access", ALIGNED_PARAMETER_ACCESS]),
                ("build", [path, "--vortex-source", VORTEX, "--tooldir", TOOLCHAIN,
                           "--build-root", PROJECT / "build" / out.name / name]),
                ("validate", [path])):
            run_stage(rec, action + "_" + name, cli + [action, *args, "--target-lock", SIM_LOCK], out, 420)
        manifest, _ = validate(path, SIM_LOCK.read_bytes())
        info = dict(manifest=sha256(path / "manifest.json"), image=manifest["image_sha256"], source=sha256(source),
                    device_parameter_access=manifest["device_parameter_access"])
        if name in baseline:
            origin = baseline[name]
            portable, _ = validate(origin, SIM_LOCK.read_bytes())
            require(manifest["image_sha256"] == experiment["operators"][name]["variants"]["aligned"]["kernel.vxbin"]
                    and (origin / "ir.json").read_bytes() == (path / "ir.json").read_bytes(),
                    "formal code differs from validated aligned experiment or portable IR")
            info.update(bytewise=str(origin.relative_to(PROJECT)), bytewise_image=portable["image_sha256"])
        modules[name] = info
    rec.summary["modules"] = modules


def open_context(out, backend):
    return Context(BINDINGS / backend / "binding.json", SIM_LOCK, backend=backend, run_id=out.name)


def witness(out, backend, built):
    manifest = frozen_manifest(FROZEN)
    witness_root = out / "witness"
    witness_root.mkdir()
    report = dict(launch_attempts=0, completed=[])
    ctx = open_context(out, backend)
    try:
        current, module, alias_pass = None, None, False
        for spec in manifest["cases"]:
            if spec["bases"] is not None and not alias_pass:
                alias_check(ctx, FROZEN / "alias", witness_root / "alias", manifest["alias"])
                alias_pass = True
            if current != spec["entry"]:
                if module is not None:
                    ctx.unload(module)
                current = spec["entry"]
                module = ctx.load(built / "modules" / current)
            run_case(ctx, module, spec, FROZEN / spec["id"], witness_root / spec["id"], report)
            report["completed"].append(spec["id"])
        require(alias_pass and report["launch_attempts"] == len(manifest["cases"]), "incomplete witness replay")
        report.update(status="PASS", alias="PASS", corpus_sha256=sha256(FROZEN / "manifest.json"),
                      high=sum(s["bases"] is not None for s in manifest["cases"]))
        write_json(witness_root / "summary.json", report)
    finally:
        if ctx.state == "READY":
            ctx.close()


def capture_case(ctx, built, info, case, frozen, op, spec, stream):
    n, roles = spec["n"], ABI[op][1]
    size = 4 * spec["words"]
    inputs = {role: (frozen / (role + ".bin")).read_bytes() for role in roles}
    expected = (frozen / "expected.bin").read_bytes()
    buffers = [ctx.alloc(size) for _ in roles]
    bases = {}
    for role, handle in zip(roles, buffers):
        base = Q()
        ctx.check(ctx.lib.vx_buffer_address(ctx.buffers[handle][0], C.byref(base)), "buffer_address")
        bases[role] = base.value
    payload = payload_bytes(op, bases, n)
    (case / "params.bin").write_bytes(payload)
    arguments = launch_args(op, buffers, GUARD, n, ALPHA)
    for pair in range(TRIALS):
        order = ROUTES if pair % 2 == 0 else ROUTES[::-1]
        for position, route in enumerate(order):
            path = PROJECT / info["bytewise"] if route == "bytewise" else built / "modules" / op
            image = info["bytewise_image"] if route == "bytewise" else info["image"]
            module = ctx.load(path)
            require(module.manifest["image_sha256"] == image and module.manifest.get("device_parameter_access") ==
                    (ALIGNED_PARAMETER_ACCESS if route == "aligned" else None), "formal module identity differs")
            for role, handle in zip(roles, buffers):
                ctx.write(handle, 0, inputs[role])
            idle, before = snapshot(ctx), snapshot(ctx)
            require(idle == before, "core counters moved while idle")
            event = ctx.launch(module, module.manifest["entry"], (spec["grid"], 1, 1), (spec["block"], 1, 1), arguments)
            require(event.plan.payload == payload and C.string_at(event.payload, len(payload)) == payload, "payload differs")
            ctx.wait(event, 120000)
            after = snapshot(ctx)
            result = ctx.read(buffers[-1], 0, size)
            ctx.unload(module)
            output = case / ("{}-{}.bin".format(route, pair))
            output.write_bytes(result)
            require(result == expected, "full output or guard mismatch: " + str(output))
            delta = {key: after[key] - before[key] for key in COUNTERS}
            require(min(delta.values()) >= 0 and all(delta[key] > 0 for key in ("cycles", "instret")), "nonpositive counts")
            row = dict(operator=op, n=n, pair=pair, position=position, route=route, image_sha256=image,
                       params_sha256=sha256(case / "params.bin"), output_sha256=sha256(output),
                       expected_sha256=sha256(frozen / "expected.bin"), idle=idle, before=before, after=after, delta=delta)
            stream.write(json.dumps(row) + "\n")
            stream.flush()
            print(op, n, route, pair, delta["cycles"], delta["instret"], flush=True)
    for handle in buffers:
        ctx.free(handle)


def worker(out, backend, built):
    report = read_json(built / "summary.json")
    require(report["status"] == "PASS" and report["exit_code"] == 0, "production build has not passed")
    witness(out, backend, built)
    perf = out / "performance"
    perf.mkdir()
    with (perf / "samples.jsonl").open("x", encoding="utf-8") as stream:
        for bundle, _, plan in performance_bundles():
            ctx = open_context(out, backend)
            try:
                for op, spec, subdir in workloads(plan):
                    case = perf / op / str(spec["n"])
                    case.mkdir(parents=True)
                    capture_case(ctx, built, report["modules"][op], case, bundle / "inputs" / subdir, op, spec, stream)
            finally:
                if ctx.state == "READY":
                    ctx.close()


def model(out, rec, backend, built):
    binding = BINDINGS / backend / "binding.json"
    env = read_json(binding)
    rec.env.update(VORTEX_DRIVER=env["driver"], LD_LIBRARY_PATH=env["library_dir"], VORTEX_PROFILING="0")
    rec.summary.update(backend=backend, binding_sha256=sha256(binding), build_sha256=sha256(built / "summary.json"))
    runs = {}
    for op in OPS:
        root = out / ("suite-" + op)
        run_stage(rec, "p0_suite_" + op, [sys.executable, "-B", PROJECT / "scripts/run_ptx_suite.py",
                  "--kernel", op, "--backend", backend, "--module", built / "modules" / op,
                  "--binding", binding, "--target-lock", SIM_LOCK, "--output", root], out, 1200)
        report = read_json(root / "result.json")
        require(report["status"] == "PASS" and report["exit_code"] == 0 and
                report["passed"] == (504 if op == "affine" else 168), "existing P0 suite incomplete")
        runs[op] = dict(passed=report["passed"], artifact_sha256=sha256(root / "result.json"))
    rec.summary["p0_suite"] = runs
    run_stage(rec, "frozen_witness_and_performance", [sys.executable, "-B", Path(__file__).resolve(), "worker",
              "--output", out, "--backend", backend, "--build", built], out, 1200)


def review_model(path, built, backend):
    report = read_json(path / "summary.json")
    require(report["status"] == "PASS" and report["exit_code"] == 0 and report["backend"] == backend and
            report["build_sha256"] == sha256(built / "summary.json"), "backend receipt differs")
    require(all(c["returncode"] == 0 and not c["timed_out"] and sha256(path / c["log"]) == c["log_sha256"]
                for c in report["commands"]), "backend command or log differs")
    witness_receipt = read_json(path / "witness/summary.json")
    require(witness_receipt["status"] == "PASS" and witness_receipt["launch_attempts"] == 13 and
            witness_receipt["high"] == 5, "witness receipt differs")
    perf = path / "performance"
    log = perf / "samples.jsonl"
    samples = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    index = {(r["operator"], r["n"], r["route"], r["pair"]): r for r in samples}
    require(len(index) == len(samples) == 48, "sample count differs")
    out = {}
    for bundle, _, plan in performance_bundles():
        for op, spec, subdir in workloads(plan):
            n = spec["n"]
            case = perf / op / str(n)
            expected = bundle / "inputs" / subdir / "expected.bin"
            rows = {route: [] for route in ROUTES}
            for pair in range(TRIALS):
                order = ROUTES if pair % 2 == 0 else ROUTES[::-1]
                for pos, route in enumerate(order):
                    row = index[op, n, route, pair]
                    output = case / ("{}-{}.bin".format(route, pair))
                    require(row["position"] == pos and row["params_sha256"] == sha256(case / "params.bin") and
                            row["output_sha256"] == row["expected_sha256"] == sha256(expected) and
                            output.read_bytes() == expected.read_bytes() and row["idle"] == row["before"] and
                            row["delta"] == {k: row["after"][k] - row["before"][k] for k in COUNTERS}, "sample evidence differs")
                    rows[route].append(row["delta"])
            base, aligned = (rows[route] for route in ROUTES)
            pair_savings = [b["cycles"] - a["cycles"] for b, a in zip(base, aligned)]
            require(min(pair_savings) > 0 and all(len({r["instret"] for r in rows[route]}) == 1 for route in ROUTES),
                    "regression in paired cycles or retirement stability")
            stats = {route: {key: median(r[key] for r in rows[route]) for key in ("cycles", "instret")} for route in ROUTES}
            out["{}/{}".format(op, n)] = dict(stats, pair_cycle_savings=pair_savings)
    return dict(metrics=out, samples_sha256=sha256(log), suite=report["p0_suite"], witness=witness_receipt)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("phase", choices=("build", "model", "worker", "review"))
    cli.add_argument("--output", type=Path, required=True)
    cli.add_argument("--backend", choices=BACKENDS)
    for name in ("build", *BACKENDS):
        cli.add_argument("--" + name, type=Path)
    args = cli.parse_args()
    out = args.output.resolve()
    require(out.parent == PROJECT / "results", "choose an output in results")
    if args.phase == "worker":
        worker(out, args.backend, args.build.resolve())
        return 0
    out.mkdir()
    report = dict(status="RUNNING", board_execution="NOT_RUN", commands=[], argv=[sys.executable, "-B", *sys.argv],
                  script_sha256=sha256(__file__), started_at=utc_now())
    env = {key: value for key, value in os.environ.items() if key not in
           ("XCLBIN_PATH", "XCL_EMULATION_MODE", "VORTEX_CP_POLL_TIMEOUT_S")}
    rec = Recorder(out, report, env)
    try:
        if args.phase == "build":
            build(out, rec)
        elif args.phase == "model":
            model(out, rec, args.backend, args.build.resolve())
        else:
            report["models"] = {b: review_model(getattr(args, b), args.build, b) for b in BACKENDS}
            sim, rtl = (report["models"][b]["metrics"] for b in BACKENDS)
            require(all(sim[case][route]["instret"] == rtl[case][route]["instret"]
                        for case in sim for route in ROUTES), "model retirement differs")
        report.update(status="PASS", exit_code=0)
    except Exception as error:
        report.update(status="FAIL", exit_code=1, error=str(error))
    report["finished_at"] = utc_now()
    rec.save()
    print(report["status"], out, report.get("error", ""))
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
