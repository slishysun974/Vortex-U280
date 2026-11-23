"""Run formal v1.4 P0, V03 and the original input pairs on the fixed NOXRT AFU."""

import argparse
import ctypes as C
import json
from pathlib import Path
import shutil
import sys

from afu_contract import (BACKEND, FIXED_BINDING, PROJECT, SIM_LOCK, VORTEX, Recorder, check_binding, clean_env,
                          driver_env, read_json, require, run_stage, sha256, utc_now, write_json)
from alignment import address, open_afu, verified_alignment
from model import OPS, P0_COUNT, receipt, stage_forms, witness, workloads_from_kits
from ptx_module import ModuleError, SAME_PREDICATE_LOWERING
from ptx_runtime import ALIGNED_PARAMETER_BINDINGS
from run_ptx_suite import launch_args
from u280_perf_pair import ABI, ALPHA, GUARD, payload_bytes


def binding_negative(out, built):
    out.mkdir()
    for name in ("hardware.json", "native-summary.json"):
        shutil.copyfile(FIXED_BINDING.with_name(name), out / name)
    other = read_json(FIXED_BINDING)
    other["scope"] += "; altered identity control"
    binding = out / "binding.json"
    write_json(binding, other)
    ctx = open_afu(binding, out)
    try:
        require(not ctx.aligned_parameter_binding, "altered AFU binding was approved")
        try:
            ctx.load(built / "modules/copy")
        except ModuleError as error:
            require(error.code == "E_TARGET_MISMATCH" and not ctx.modules and ctx.state == "READY",
                    "altered binding did not fail closed at load")
            write_json(out / "result.json", dict(status="PASS", binding_sha256=sha256(binding), error=error.to_dict()))
        else:
            raise RuntimeError("altered binding loaded aligned code")
    finally:
        if ctx.state == "READY":
            ctx.close()


def samples(out, built, info):
    out.mkdir()
    ctx = open_afu(FIXED_BINDING, out)
    rows = []
    try:
        for op, spec, frozen in workloads_from_kits():
            folder = out / op / str(spec["n"])
            folder.mkdir(parents=True)
            roles = ABI[op][1]
            inputs = {role: (frozen / (role + ".bin")).read_bytes() for role in roles}
            expected = dict(inputs, z=(frozen / "expected.bin").read_bytes())
            handles = {role: ctx.alloc(len(raw)) for role, raw in inputs.items()}
            bases = {role: address(ctx, handle) for role, handle in handles.items()}
            module = ctx.load(built / "modules" / op)
            require(module.manifest["image_sha256"] == info[op]["merged_image"] and
                    module.manifest["predicate_lowering"] == SAME_PREDICATE_LOWERING, "sample was not the formal v1.4 image")
            for role, raw in inputs.items():
                ctx.write(handles[role], 0, raw)
            args = launch_args(op, [handles[role] for role in roles], GUARD, spec["n"], ALPHA)
            event = ctx.launch(module, module.manifest["entry"], (spec["grid"], 1, 1), (spec["block"], 1, 1), args)
            payload = payload_bytes(op, bases, spec["n"])
            require(event.plan.payload == C.string_at(event.payload, len(payload)) == payload, "frozen input launch payload differs")
            (folder / "params.bin").write_bytes(payload)
            write_json(folder / "bases.json", bases)
            completion = ctx.wait(event, 120000)
            captures = {}
            for role, handle in handles.items():
                result = ctx.read(handle, 0, len(expected[role]))
                output = folder / (role + ".bin")
                output.write_bytes(result)
                require(result == expected[role], "full array, tail padding or sentinel differs: " + str(output))
                captures[role] = sha256(output)
                ctx.free(handle)
            row = dict(status="PASS", operator=op, **spec, image_sha256=module.manifest["image_sha256"],
                       params_sha256=sha256(folder / "params.bin"), arrays=captures, completion=completion)
            write_json(folder / "result.json", row)
            rows.append(row)
            ctx.unload(module)
            print(op, spec["n"], "full arrays and sentinels PASS", flush=True)
    finally:
        if ctx.state == "READY":
            ctx.close()
    require(len(rows) == 6, "original input coverage differs")
    write_json(out / "summary.json", dict(status="PASS", exit_code=0, cases=rows))


def worker(out, built):
    info = receipt(built)
    binding_negative(out / "altered-binding", built)
    stage_forms(out / "p0-forms", BACKEND, built, info)
    witness(out, BACKEND, built)
    samples(out / "original-inputs", built, info)


def execute(out, rec, built, alignment):
    info = receipt(built)
    check, _ = check_binding(FIXED_BINDING, fixed=True)
    capture = verified_alignment(alignment, FIXED_BINDING, built)
    require(ALIGNED_PARAMETER_BINDINGS.get(BACKEND) == capture["binding_sha256"], "runtime has not accepted this exact AFU binding")
    driver_env(rec, check)
    rec.summary.update(binding_sha256=sha256(FIXED_BINDING), alignment_sha256=sha256(alignment / "summary.json"),
                       build_sha256=sha256(built / "summary.json"), suites={})
    for op in OPS:
        module = built / "modules" / op
        require(sha256(module / "manifest.json") == info[op]["manifest_sha256"], "formal P0 module identity differs")
        suite = out / ("suite-" + op)
        run_stage(rec, "p0_suite_" + op, [sys.executable, "-B", PROJECT / "scripts/run_ptx_suite.py",
                  "--kernel", op, "--backend", BACKEND, "--module", module, "--binding", FIXED_BINDING,
                  "--target-lock", SIM_LOCK, "--output", suite], out, 1800)
        result = read_json(suite / "result.json")
        require(result["status"] == "PASS" and result["exit_code"] == 0 and result["passed"] == P0_COUNT[op] and
                len(result["rejections"]) == 19 and result["recovery"]["status"] == "PASS", "P0 suite coverage differs")
        text = run_stage(rec, "review_p0_" + op, [sys.executable, "-B", PROJECT / "scripts/verify_ptx_suite_results.py", suite], out, 360)
        require(json.loads(text)["cases"] == P0_COUNT[op], "P0 offline review coverage differs")
        rec.summary["suites"][op] = dict(passed=result["passed"], rejections=len(result["rejections"]),
            recovery=result["recovery"]["status"], sha256=sha256(suite / "result.json"))
    run_stage(rec, "forms_v03_and_original_inputs", [sys.executable, "-B", Path(__file__).resolve(), "--worker",
              "--build", built, "--alignment", alignment, "--output", out], out, 1200)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--build", type=Path, required=True)
    cli.add_argument("--alignment", type=Path, required=True)
    cli.add_argument("--output", type=Path, required=True)
    cli.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = cli.parse_args()
    out, built, alignment = (path.resolve() for path in (args.output, args.build, args.alignment))
    require(out.parent == PROJECT / "results" and out.name.startswith("local-ptx-same-predicate-afu-regress-"),
            "choose a fresh AFU regression run")
    if args.worker:
        verified_alignment(alignment, FIXED_BINDING, built)
        worker(out, built)
        return 0
    out.mkdir()
    report = dict(status="RUNNING", backend=BACKEND, commands=[], started_at=utc_now(),
                  argv=[sys.executable, "-B", *sys.argv], board_execution="NOT_RUN")
    rec = Recorder(out, report, clean_env())
    try:
        execute(out, rec, built, alignment)
        report.update(status="PASS", exit_code=0)
    except Exception as error:
        report.update(status="FAIL", exit_code=1, error=str(error))
    report["finished_at"] = utc_now()
    rec.save()
    print(report["status"], out, report.get("error", ""))
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
