"""Check per-lane LSU requests on the separately instrumented NOXRT AFU."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import ctypes as C
import gzip
from pathlib import Path
import sys

from afu_contract import (BACKEND, FIXED_BINDING, PROJECT, SIM_LOCK, Recorder, check_binding, clean_env, driver_env,
                          read_json, require, run_stage, sha256, utc_now, write_json)
from alignment import open_afu, verified_alignment
from model import OPS, receipt, workloads_from_kits
from ptx_module import SAME_PREDICATE_LOWERING, validate
from u280_perf_pair import ABI, load_image, payload_bytes

ISOLATED = str(PROJECT / "experiments/ptx-same-predicate")
sys.path.insert(0, ISOLATED)
from run import buffers_for, launch
from trace import analyze_log, data_sites
sys.path.insert(0, ISOLATED)
from review import inject_false_lane


def worker(out, binding, built, op, spec, frozen):
    path = built / "modules" / op
    manifest, image = validate(path, SIM_LOCK.read_bytes())
    require(manifest["predicate_lowering"] == SAME_PREDICATE_LOWERING and
            manifest["image_sha256"] == receipt(built)[op]["merged_image"], "debug replay image is not the formal v1.4 artifact")
    ctx = open_afu(binding, out)
    try:
        require(not ctx.aligned_parameter_binding, "trace binding entered the formal allowlist")
        inputs, expected, handles, bases = buffers_for(ctx, frozen, op, spec)
        module = load_image(ctx, C.create_string_buffer(image, len(image)), manifest["entry"])
        payload = payload_bytes(op, bases, spec["n"])
        (out / "params.bin").write_bytes(payload)
        write_json(out / "bases.json", bases)
        for role, raw in inputs.items():
            ctx.write(handles[role], 0, raw)
        libc = C.CDLL(None)
        require(libc.fflush(None) == 0, "could not flush AFU pre-launch trace")
        print("LSU_TRACE_BEGIN", flush=True)
        launch(ctx, module, spec, payload, 360000)
        require(libc.fflush(None) == 0, "could not flush AFU launch trace")
        print("LSU_TRACE_END", flush=True)
        hashes = {}
        for role, handle in handles.items():
            wanted = expected if role == "z" else inputs[role]
            data = ctx.read(handle, 0, len(wanted))
            dest = out / (role + ".bin")
            dest.write_bytes(data)
            require(data == wanted, "traced full array or sentinel differs: " + role)
            hashes[role] = sha256(dest)
        write_json(out / "capture.json", dict(image_sha256=manifest["image_sha256"], arrays=hashes))
        ctx.unload(module)
    finally:
        if ctx.state == "READY":
            ctx.close()


def run_case(out, env, binding, built, op, spec):
    n = spec["n"]
    folder = out / op / str(n)
    folder.mkdir(parents=True)
    row = dict(status="RUNNING", commands=[], operator=op, **spec, started_at=utc_now())
    rec = Recorder(folder, row, env)
    try:
        log = folder / "lsu.log.gz"
        run_stage(rec, "capture_pre_cache_lsu", ["bash", "-o", "pipefail", "-c", '"$@" 2>&1 | gzip -1 > "$0"', log,
                  sys.executable, "-B", Path(__file__).resolve(), "--worker", "--output", folder, "--binding", binding,
                  "--build", built, "--operator", op, "--n", str(n)], folder, 480)
        image = built / "modules" / op / "kernel.vxbin"
        sites, static = data_sites(image, op)
        bases = read_json(folder / "bases.json")
        # The AFU instantiates the same tagged CTA and LSU RTL trace format
        # as processor RTL. The runtime/backend in this receipt is xrtsim.
        with gzip.open(log, "rt", encoding="utf-8") as stream:
            proof = analyze_log(stream, "rtlsim", op, spec, bases, sites)
        arrays = read_json(folder / "capture.json")
        require(array_identity(arrays, op, image), "trace capture image or arrays differ")
        if n % 4:
            tail = proof["last_warp"]
            active = tail[n - 1]
            require(proof["false_threads"] == 3 and all(not tail[i] for i in range(n, n + 3)) and
                    [event["buffer"] for event in active] == list(ABI[op][1]) and
                    all(event["lane0_first_mask"] == "1000" for event in active), "AFU tail-lane mask differs")
            if op == "copy":
                with gzip.open(log, "rt", encoding="utf-8") as stream:
                    try:
                        analyze_log(inject_false_lane(stream, "rtlsim", active[-1]), "rtlsim", op, spec, bases, sites)
                    except RuntimeError as error:
                        require(str(error).startswith(f"false-predicate lane issued array request: index {n},"),
                                "injected false-lane control failed for a different reason")
                        row["negative_control"] = dict(status="PASS", operation="ST", reason=str(error))
                    else:
                        raise RuntimeError("false-lane injection was not detected")
        row.update(status="PASS", exit_code=0, requests=proof, sites=sites, static_opcodes=static,
                   raw_trace_sha256=sha256(log), params_sha256=sha256(folder / "params.bin"), **arrays)
    except Exception as error:
        row.update(status="FAIL", exit_code=1, error=str(error))
    row["finished_at"] = utc_now()
    rec.save()
    print(op, n, row["status"], row.get("error", ""), flush=True)
    return folder / "summary.json", row["status"]


def array_identity(capture, op, image):
    return set(capture["arrays"]) == set(ABI[op][1]) and capture["image_sha256"] == sha256(image)


def execute(out, rec, args, built):
    trace_build = args.trace_build.resolve()
    trace_report = read_json(trace_build / "summary.json")
    binding = trace_build / "binding/binding.json"
    require(trace_report["status"] == "PASS" and trace_report["exit_code"] == 0 and
            trace_report["binding_sha256"] == sha256(binding) and trace_report["fixed_binding_sha256"] == sha256(FIXED_BINDING),
            "trace build has not passed")
    info, _ = check_binding(binding, fixed=False)
    verified_alignment(args.fixed_alignment, FIXED_BINDING, built)
    verified_alignment(args.trace_alignment, binding, built)
    driver_env(rec, info)
    rec.summary.update(build_sha256=sha256(built / "summary.json"), binding_sha256=sha256(binding),
                       trace_build_sha256=sha256(trace_build / "summary.json"),
                       trace_alignment_sha256=sha256(args.trace_alignment / "summary.json"), cases={})
    work = sorted(workloads_from_kits(), key=lambda row: row[1]["n"])
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = [pool.submit(run_case, out, rec.env, binding, built, op, spec) for op, spec, _ in work]
        for future in as_completed(futures):
            path, status = future.result()
            rec.summary["cases"][path.relative_to(out).as_posix()] = dict(status=status, sha256=sha256(path))
            rec.save()
    require(len(rec.summary["cases"]) == 6 and all(r["status"] == "PASS" for r in rec.summary["cases"].values()),
            "at least one AFU LSU trace failed")


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    for name in ("build", "output"):
        cli.add_argument("--" + name, type=Path, required=True)
    for name in ("trace-build", "fixed-alignment", "trace-alignment", "binding"):
        cli.add_argument("--" + name, type=Path)
    cli.add_argument("--jobs", type=int, default=2)
    cli.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    cli.add_argument("--operator", choices=OPS, help=argparse.SUPPRESS)
    cli.add_argument("--n", type=int, help=argparse.SUPPRESS)
    args = cli.parse_args()
    out, built = args.output.resolve(), args.build.resolve()
    if args.worker:
        _, spec, frozen = next(row for row in workloads_from_kits() if row[0] == args.operator and row[1]["n"] == args.n)
        worker(out, args.binding, built, args.operator, spec, frozen)
        return 0
    require(out.parent == PROJECT / "results" and out.name.startswith("local-ptx-same-predicate-afu-trace-")
            and args.jobs > 0 and args.trace_build and args.fixed_alignment and args.trace_alignment, "invalid AFU trace arguments")
    out.mkdir()
    report = dict(status="RUNNING", backend=BACKEND, commands=[], started_at=utc_now(),
                  argv=[sys.executable, "-B", *sys.argv], board_execution="NOT_RUN", scope="instrumented NOXRT AFU RTL LSU")
    rec = Recorder(out, report, clean_env())
    try:
        execute(out, rec, args, built)
        report.update(status="PASS", exit_code=0)
    except Exception as error:
        report.update(status="FAIL", exit_code=1, error=str(error))
    report["finished_at"] = utc_now()
    rec.save()
    print(report["status"], out, report.get("error", ""))
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
