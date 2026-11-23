"""Replay the validated formal images on D6 DEBUG3 and check exact lane requests."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import gzip
import os
from pathlib import Path
import sys

from model import (BACKENDS, FORMAL, OPS, PROJECT, ROUTES, SIM_LOCK, Recorder, read_json,
                   receipt, require, run_stage, sha256, utc_now, workloads_from_kits)

sys.path.insert(0, str(PROJECT / "experiments/ptx-same-predicate"))

from ptx_module import validate
from run import binding_env, buffers_for, context, invoke, payload_bytes
from run_ptx_copy import write_json
from run_ptx_copy_trace import trace_libraries
from trace import TRACE_BINDINGS, analyze_log, data_sites


def module_path(built, op, route):
    return (FORMAL if route == "aligned" else built) / "modules" / op


def worker(out, backend, built, op, n, route):
    spec, frozen = next((spec, frozen) for name, spec, frozen in workloads_from_kits() if name == op and spec["n"] == n)
    path = module_path(built, op, route)
    manifest, raw = validate(path, SIM_LOCK.read_bytes())
    expected_image = receipt(built)[op][route + "_image"]
    require(manifest["image_sha256"] == expected_image and (path / "kernel.vxbin").read_bytes() == raw,
            "DEBUG3 image differs from the formal validated image")
    # DEBUG3 remains outside the normal aligned Context.load allowlist. Replay
    # the verified bytes on the fixed non-VM debug runtime, with the same queue ABI.
    ctx = context(TRACE_BINDINGS / backend / "binding.json", backend, out)
    try:
        inputs, expected, handles, bases = buffers_for(ctx, frozen, op, spec)
        payload = payload_bytes(op, bases, n)
        (out / "params.bin").write_bytes(payload)
        write_json(out / "bases.json", bases)
        captures = invoke(ctx, path / "kernel.vxbin", spec, payload, inputs, handles, out, trace=True)
        require((out / "z.bin").read_bytes() == expected, "full traced output differs")
        write_json(out / "captures.json", captures)
    finally:
        if ctx.state == "READY":
            ctx.close()


def run_case(out, env, backend, built, op, spec, route):
    n = spec["n"]
    folder = out / op / str(n) / route
    folder.mkdir(parents=True)
    report = dict(status="RUNNING", commands=[], operator=op, n=n, route=route, started_at=utc_now())
    rec = Recorder(folder, report, env)
    try:
        log = folder / "lsu.log.gz"
        run_stage(rec, "debug_launch", ["bash", "-o", "pipefail", "-c", '"$@" 2>&1 | gzip -1 > "$0"', log,
                  sys.executable, "-B", Path(__file__).resolve(), "--worker", "--output", folder, "--backend", backend,
                  "--build", built, "--operator", op, "--n", str(n), "--route", route], folder, 420)
        path = module_path(built, op, route) / "kernel.vxbin"
        sites, static = data_sites(path, op)
        with gzip.open(log, "rt", encoding="utf-8") as raw:
            proof = analyze_log(raw, backend, op, spec, read_json(folder / "bases.json"), sites)
        report.update(status="PASS", exit_code=0, proof=proof, image_sha256=sha256(path),
                      raw_trace_sha256=sha256(log), params_sha256=sha256(folder / "params.bin"),
                      captures=read_json(folder / "captures.json"), sites=sites, static_opcodes=static)
    except Exception as error:
        report.update(status="FAIL", exit_code=1, error=str(error))
    report["finished_at"] = utc_now()
    rec.save()
    print(backend, op, n, route, report["status"], report.get("error", ""), flush=True)
    return folder / "summary.json", report["status"]


def captures(out, rec, backend, built, jobs):
    receipt(built)
    libraries, hashes = trace_libraries(backend)
    binding = TRACE_BINDINGS / backend / "binding.json"
    require(Path(read_json(binding)["library_dir"]) == libraries, "D6 binding differs")
    binding_env(rec, binding)
    rec.summary.update(binding_sha256=sha256(binding), debug_libraries=hashes,
                       build_sha256=sha256(built / "summary.json"), cases={})
    work = sorted(workloads_from_kits(), key=lambda work: work[1]["n"])
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = [pool.submit(run_case, out, rec.env, backend, built, op, spec, route)
                   for op, spec, _ in work for route in ROUTES]
        for future in as_completed(futures):
            path, status = future.result()
            rec.summary["cases"][path.relative_to(out).as_posix()] = dict(status=status, sha256=sha256(path))
            rec.save()
    require(len(rec.summary["cases"]) == 12 and all(row["status"] == "PASS" for row in rec.summary["cases"].values()),
            "at least one formal DEBUG3 replay failed")


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--backend", choices=BACKENDS, required=True)
    cli.add_argument("--build", type=Path, required=True)
    cli.add_argument("--output", type=Path, required=True)
    cli.add_argument("--jobs", type=int, default=3)
    cli.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    cli.add_argument("--operator", choices=OPS, help=argparse.SUPPRESS)
    cli.add_argument("--n", type=int, help=argparse.SUPPRESS)
    cli.add_argument("--route", choices=ROUTES, help=argparse.SUPPRESS)
    args = cli.parse_args()
    out, built = args.output.resolve(), args.build.resolve()
    if args.worker:
        worker(out, args.backend, built, args.operator, args.n, args.route)
        return 0
    require(out.parent == PROJECT / "results" and out.name.startswith("local-ptx-same-predicate-production-") and
            args.jobs >= 1, "use a new formal DEBUG3 run and a positive job count")
    out.mkdir()
    env = {key: value for key, value in os.environ.items()
           if key not in ("XCLBIN_PATH", "XCL_EMULATION_MODE", "VORTEX_CP_POLL_TIMEOUT_S")}
    report = dict(status="RUNNING", backend=args.backend, commands=[], started_at=utc_now(),
                  argv=[sys.executable, "-B", *sys.argv], board_execution="NOT_RUN", afu_execution="NOT_RUN")
    rec = Recorder(out, report, env)
    try:
        captures(out, rec, args.backend, built, args.jobs)
        report.update(status="PASS", exit_code=0)
    except Exception as error:
        report.update(status="FAIL", exit_code=1, error=str(error))
    report["finished_at"] = utc_now()
    rec.save()
    print(report["status"], out, report.get("error", ""))
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
