"""Run and verify the frozen A/E V03 corpus without consulting author answers."""

import argparse
import ctypes as C
import json
import os
from pathlib import Path
import re
import shutil
import struct
import sys

HERE = Path(__file__).resolve()
if sys.version_info[:2] == (3, 6):
    sys.path.insert(0, str(HERE.parents[1] / "vendor/dataclasses-0.8"))

from build_ae_v03 import CORPUS_SHA, SCHEMA, frozen_manifest
from c_v03_board import BOARD_BACKEND, PY_FILES, bind, check_commands, review_gate
from c_v03_high_board import read_buffer, reserve, write_buffer
from check_c_v03_receipt import BINDINGS, FORMS, ROLES, WIDE
from ptx_module import BOARD_LOCK_SHA, ModuleError, validate
from ptx_runtime import BufferSlice, Context, P, Q, U
from ptx_u280 import BUSES, QUERY_SOURCE, RUNTIME_SHAS, XCLBIN_SHA
from run_native_smoke import PROJECT, Recorder, sha256, utc_now
from run_ptx_copy import BOARD_LOCK, SIM_LOCK, read_json, require, run_stage, write_json
from runtime_backends import BACKENDS


def preflight(bundle):
    plan = read_json(bundle / "plan.json")
    frozen = frozen_manifest(bundle / "frozen")
    require(plan["schema"] == SCHEMA and plan["corpus_sha256"] == CORPUS_SHA and
            plan["runtime_sha256"] == RUNTIME_SHAS and plan["xclbin_sha256"] == XCLBIN_SHA and
            sha256(bundle / "target_lock.json") == BOARD_LOCK_SHA, "wrong A/E kit identity")
    files = {p.relative_to(bundle).as_posix(): sha256(p) for p in bundle.rglob("*")
             if p.is_file() and p != bundle / "plan.json"}
    require(files == plan["files"], "A/E kit member differs")
    verify_modules(bundle / "modules", bundle / "target_lock.json", frozen, plan["modules"])
    return plan, frozen


def verify_modules(modules, lock, frozen, reviewed):
    for entry in (FORMS, WIDE):
        root = modules / entry
        metadata, _ = validate(root, lock.read_bytes())
        require(metadata["entry"] == entry and metadata["source_sha256"] == frozen["files"]["sources/" + entry + ".ptx"] and
                reviewed[entry] == dict(image_sha256=metadata["image_sha256"], manifest_sha256=sha256(root / "manifest.json")),
                "module differs: " + entry)


def prepare(run, frozen, build):
    manifest = frozen_manifest(frozen)
    record = read_json(build / "summary.json")
    check_commands(build, record)
    require(record["corpus_sha256"] == CORPUS_SHA and record["freeze_receipt_sha256"] == sha256(frozen / "freeze.json"),
            "build must follow the frozen A/E inputs")
    bundle = run / "bundle"
    (bundle / "scripts").mkdir(parents=True)
    for name in (*PY_FILES, HERE.name, "c_v03_high_board.py", "build_ae_v03.py"):
        shutil.copyfile(HERE.parent / name, bundle / "scripts" / name)
    vendor = PROJECT / "third_party/dataclasses-0.8"
    provenance = read_json(vendor / "provenance.json")
    dependency = bundle / "vendor/dataclasses-0.8"
    dependency.mkdir(parents=True)
    for name, expected in provenance["files"].items():
        require(Path(name).name == name and sha256(vendor / name) == expected, "3.6 backport differs")
        shutil.copyfile(vendor / name, dependency / name)
    shutil.copyfile(vendor / "provenance.json", dependency / "provenance.json")
    shutil.copyfile(BOARD_LOCK, bundle / "target_lock.json")
    shutil.copyfile(BOARD_LOCK.with_name("fpga.json"), bundle / "hardware.json")
    (bundle / "query.cpp").write_bytes(QUERY_SOURCE.encode())
    shutil.copytree(frozen, bundle / "frozen")
    verify_modules(build / "modules/board", BOARD_LOCK, manifest, record["modules"]["board"])
    shutil.copytree(build / "modules/board", bundle / "modules")
    plan = dict(schema=SCHEMA, corpus_sha256=CORPUS_SHA, modules=record["modules"]["board"],
                build_summary_sha256=sha256(build / "summary.json"), xclbin_sha256=XCLBIN_SHA, runtime_sha256=RUNTIME_SHAS,
                files={p.relative_to(bundle).as_posix(): sha256(p) for p in sorted(bundle.rglob("*")) if p.is_file()})
    write_json(bundle / "plan.json", plan)
    preflight(bundle)
    return Path(shutil.make_archive(str(run / "ae-v03-u280-input"), "gztar", root_dir=run, base_dir="bundle"))


def alias_check(ctx, frozen, out, bases):
    out.mkdir()
    ctx.lib.vx_buffer_reserve.argtypes = [P, Q, Q, U, C.POINTER(P)]
    ctx.lib.vx_buffer_reserve.restype = C.c_int
    capabilities = []
    for key in (5, 15):
        value = Q()
        ctx.check(ctx.lib.vx_device_query(ctx.device, key, C.byref(value)), "query_fixed_address")
        capabilities.append(value.value)
    require(capabilities == [2**33, 0], "requires the fixed 8 GiB device window with VM disabled")
    handles, actual = reserve(ctx, bases)
    write_json(out / "reservations.json", dict(device_bases=actual, range_bytes=capabilities[0], vm=capabilities[1]))
    for epoch, order in enumerate((("low", "high"), ("high", "low")), 1):
        for role in order:
            name = "{}-{}.bin".format(epoch, role)
            ctx.write(handles[role], 0, (frozen / name).read_bytes())
        for role in order:
            name = "{}-{}.bin".format(epoch, role)
            (out / name).write_bytes(ctx.read(handles[role], 0, 256))
            require((out / name).read_bytes() == (frozen / name).read_bytes(), "independent alias guard differs: " + name)
    for handle in handles.values():
        ctx.free(handle)


def check_bytes(raw, frozen, phase):
    suffix = "input" if phase == "before" else "expected"
    for role in ROLES:
        require((raw / (role + "." + phase + ".bin")).read_bytes() ==
                (frozen / (role + "." + suffix + ".bin")).read_bytes(),
                raw.name + " " + phase + " differs: " + role)


def run_case(ctx, module, spec, frozen, raw, report):
    raw.mkdir()
    size = 4 * spec["words"]
    fixed = spec["bases"] is not None
    if fixed:
        handles, bases = reserve(ctx, spec["bases"])
    else:
        handles = {role: ctx.alloc(size) for role in ROLES}
        bases = {}
        for role, handle in handles.items():
            address = Q()
            ctx.check(ctx.lib.vx_buffer_address(ctx.buffers[handle][0], C.byref(address)), "address_" + role)
            bases[role] = address.value
    write_json(raw / "reservations.json", bases)
    for role, handle in handles.items():
        data = (frozen / (role + ".input.bin")).read_bytes()
        if fixed:
            write_buffer(ctx, handle, bases[role], data)
        else:
            ctx.write(handle, 0, data)
    for phase in ("before", "after"):
        for role, handle in handles.items():
            data = read_buffer(ctx, handle, bases[role]) if fixed else ctx.read(handle, 0, size)
            (raw / (role + "." + phase + ".bin")).write_bytes(data)
        check_bytes(raw, frozen, phase)
        if phase == "before":
            roles = ROLES[:2] if spec["entry"] == FORMS else ROLES
            offsets = {role: 4 * spec["offsets"][role] for role in roles}
            args = [BufferSlice(handles[r], offsets[r], size - offsets[r], "r" if r == "x" else "w") for r in roles]
            report["launch_attempts"] += 1
            print("AE_V03_BEGIN", spec["id"], flush=True)
            event = ctx.launch(module, spec["entry"], (spec["grid"], 1, 1), (spec["block"], 1, 1), args + spec["scalars"])
            (raw / "params.bin").write_bytes(C.string_at(event.payload, len(event.plan.payload)))
            write_json(raw / "event.json", ctx.wait(event))
            print("AE_V03_END", spec["id"], flush=True)
    for handle in handles.values():
        ctx.free(handle)


def capture(bundle, run, backend, binding, lock, modules):
    plan, manifest = preflight(bundle)
    reviewed = {}
    for entry in (FORMS, WIDE):
        meta, _ = validate(modules / entry, lock.read_bytes())
        require(meta["image_sha256"] == plan["modules"][entry]["image_sha256"] and
                meta["source_sha256"] == manifest["files"]["sources/" + entry + ".ptx"], "execution image differs")
        reviewed[entry] = sha256(modules / entry / "manifest.json")
    out = run / backend
    out.mkdir()
    result = dict(backend=backend, binding_sha256=sha256(binding), plan_sha256=sha256(bundle / "plan.json"),
                  modules=reviewed, alias="NOT_RUN", launch_attempts=0, completed=[], phase="open")
    ctx = None
    try:
        ctx = Context(binding, lock, backend=backend, run_id=run.name)
        current, module = None, None
        for spec in manifest["cases"]:
            if spec["bases"] is not None and result["alias"] != "PASS":
                result.update(phase="alias", alias="FAIL")
                alias_check(ctx, bundle / "frozen/alias", out / "alias", manifest["alias"])
                result["alias"] = "PASS"
            result["phase"] = spec["id"]
            if current != spec["entry"]:
                if module is not None:
                    ctx.unload(module)
                current = spec["entry"]
                module = ctx.load(modules / current)
            run_case(ctx, module, spec, bundle / "frozen" / spec["id"], out / spec["id"], result)
            result["completed"].append(spec["id"])
        result["phase"] = "close"
        ctx.close()
        result["phase"] = "complete"
    except Exception as error:
        result["error"] = error.to_dict() if isinstance(error, ModuleError) else str(error)
        if ctx is not None and ctx.state == "READY":
            try:
                ctx.close()
            except Exception as cleanup:
                result["cleanup_error"] = str(cleanup)
        raise
    finally:
        result["state"] = ctx.state if ctx is not None else None
        write_json(out / "capture.json", result)


def review_capture(bundle, run, backend, binding):
    _, manifest = preflight(bundle)
    out = run / backend
    result = read_json(out / "capture.json")
    require(result["backend"] == backend and result["binding_sha256"] == sha256(binding) and
            result["plan_sha256"] == sha256(bundle / "plan.json") and result["phase"] == "complete" and
            result["state"] == "CLOSED" and result["alias"] == "PASS" and
            result["completed"] == [s["id"] for s in manifest["cases"]] and
            result["launch_attempts"] == len(manifest["cases"]), "incomplete A/E capture")
    require(read_json(out / "alias/reservations.json") == dict(device_bases=manifest["alias"], range_bytes=2**33, vm=0),
            "alias allocation differs")
    for source in (bundle / "frozen/alias").glob("*.bin"):
        require(source.read_bytes() == (out / "alias" / source.name).read_bytes(), "alias array differs")
    high = 0
    for index, spec in enumerate(manifest["cases"], 1):
        raw = out / spec["id"]
        for phase in ("before", "after"):
            check_bytes(raw, bundle / "frozen" / spec["id"], phase)
        bases = read_json(raw / "reservations.json")
        ordered = sorted(bases.values())
        require(set(bases) == set(ROLES) and all(a > 0 and a % 4 == 0 for a in ordered) and
                all(b - a >= 4 * spec["words"] for a, b in zip(ordered, ordered[1:])), "invalid allocation layout")
        if spec["bases"] is not None:
            high += 1
            require(bases == spec["bases"], "fixed allocation differs: " + spec["id"])
        roles = ROLES[:2] if spec["entry"] == FORMS else ROLES
        pointers = [bases[r] + 4 * spec["offsets"][r] for r in roles]
        layout = "<QQI4x" if spec["entry"] == FORMS else "<QQQIII4x"
        require((raw / "params.bin").read_bytes() == struct.pack(layout, *pointers, *spec["scalars"]) and
                read_json(raw / "event.json") == dict(backend=backend, event_id=index, generation=0, status="COMPLETE"),
                "event or ABI differs: " + spec["id"])
    count = len(manifest["cases"])
    return dict(status="PASS", launches=count, ordinary=count - high, high=high, alias_readbacks=4,
                full_buffers_before=3 * count, full_buffers_after=3 * count, payloads=count,
                capture_sha256=sha256(out / "capture.json"), modules=result["modules"])


def board_review(bundle, run):
    receipt = review_capture(bundle, run, BOARD_BACKEND, run / "binding/binding.json")
    plan = read_json(bundle / "plan.json")
    require(receipt["modules"] == {entry: item["manifest_sha256"] for entry, item in plan["modules"].items()},
            "board module capture differs")
    return dict(receipt, gate_sha256=review_gate(run))


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("action", choices=("prepare", "simulate", "capture", "run", "review"))
    cli.add_argument("--bundle", type=Path)
    cli.add_argument("--output", type=Path, required=True)
    cli.add_argument("--frozen", type=Path)
    cli.add_argument("--build", type=Path)
    cli.add_argument("--lock", type=Path)
    cli.add_argument("--binding", type=Path)
    cli.add_argument("--bdf", choices=["0000:" + bus + ":00.1" for bus in BUSES])
    cli.add_argument("--backend", choices=(*BACKENDS, BOARD_BACKEND), default=BOARD_BACKEND)
    args = cli.parse_args()
    run = args.output.resolve()
    bundle = args.bundle.resolve() if args.bundle else None
    require(re.fullmatch(r"(?:ae-v03-|c-v03-u280-)[A-Za-z0-9_-]{1,50}", run.name), "invalid output directory")
    if args.action == "capture":
        model = args.backend != BOARD_BACKEND
        capture(bundle, run, args.backend, args.binding if model else run / "binding/binding.json",
                args.lock if model else bundle / "target_lock.json",
                args.build / "modules/sim" if model else bundle / "modules")
        return 0
    if args.action == "review":
        print(json.dumps(board_review(bundle, run)))
        return 0
    run.mkdir()
    report = dict(schema=SCHEMA, run_id=run.name, argv=[sys.executable, "-B", *sys.argv], started_at=utc_now(),
                  status="RUNNING", commands=[], board_execution="NOT_RUN", corpus_sha256=CORPUS_SHA,
                  human_signoff="NOT_RUN", physical_recovery="NOT_RUN", timing7="OPEN")
    rec = Recorder(run, report, dict(os.environ))
    try:
        if args.action == "prepare":
            archive = prepare(run, args.frozen.resolve(), args.build.resolve())
            report.update(archive=archive.name, archive_sha256=sha256(archive),
                          plan_sha256=sha256(run / "bundle/plan.json"))
        else:
            plan, frozen = preflight(bundle)
            report["plan_sha256"] = sha256(bundle / "plan.json")
            child = [sys.executable, "-B", bundle / "scripts" / HERE.name, "capture", "--bundle", bundle, "--output", run]
            if args.action == "simulate":
                build = args.build.resolve()
                require(sha256(build / "summary.json") == plan["build_summary_sha256"], "different build run")
                verify_modules(build / "modules/sim", SIM_LOCK, frozen, read_json(build / "summary.json")["modules"]["sim"])
                shutil.copyfile(SIM_LOCK, run / "sim-lock.json")
                report["models"] = {}
                for backend, (driver, _, _) in BACKENDS.items():
                    binding = BINDINGS / backend / "binding.json"
                    for key in ("XCLBIN_PATH", "XCL_EMULATION_MODE", "VORTEX_CP_POLL_TIMEOUT_S"):
                        rec.env.pop(key, None)
                    rec.env.update(VORTEX_DRIVER=driver, LD_LIBRARY_PATH=read_json(binding)["library_dir"],
                                   VORTEX_PROFILING="0", XRT_DEVICE_INDEX="0")
                    run_stage(rec, backend, child + ["--backend", backend, "--binding", binding,
                                                   "--build", build, "--lock", run / "sim-lock.json"], run, 450)
                    report["models"][backend] = review_capture(bundle, run, backend, binding)
            else:
                require(args.bdf, "physical execution requires --bdf")
                bind(bundle, run, args.bdf, rec)
                command, _ = rec.command("capture", child, run, 1500)
                metadata = run / BOARD_BACKEND / "capture.json"
                if metadata.is_file():
                    actual = read_json(metadata)
                    report.update(alias=actual["alias"], last_phase=actual["phase"], launch_attempts=actual["launch_attempts"],
                                  capture_error=actual.get("error"))
                    if actual["launch_attempts"]:
                        report["board_execution"] = "FAIL"
                elif command["timed_out"]:
                    report["board_execution"] = "FAIL"
                require(command["returncode"] == 0 and not command["timed_out"], "physical capture failed")
                report.update(board_execution="PASS", receipt=board_review(bundle, run))
        report.update(status="PASS", exit_code=0)
    except Exception as error:
        report.update(status="FAIL", exit_code=1, error=str(error))
    report["finished_at"] = utc_now()
    rec.save()
    print(report["status"], run, report.get("error", ""))
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
