"""Qualify fixed U280 addresses above 4 GiB before launching the five V03 probes."""

import argparse
import ctypes as C
import hashlib
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

from c_v03_board import BOARD_BACKEND, bind, preflight, review_gate
from check_c_v03_receipt import BINDINGS, WIDE
from ptx_module import ModuleError, validate
from ptx_runtime import BufferSlice, Context, P, Q, U
from ptx_u280 import BUSES
from run_native_smoke import PROJECT, Recorder, sha256, utc_now
from run_ptx_copy import SIM_LOCK, read_json, require, run_stage, write_json
from runtime_backends import BACKENDS

FOUR_GIB = 1 << 32
SIZE = 256
GUARD = 32
ALIAS = {"low": 0x01600000, "high": 0x101600000}
CASES = ("low_to_high", "high_to_low", "cross_read", "cross_write", "cross_audit")
ROLES = ("x", "z", "audit")
CORPUS_SHA = "0da11d96e0d0abd20dbd112a1b745d1b6a0dc4667e9074ef2c1a245621533997"
ORIGIN = PROJECT / "results/d-high-address-closeout-20261120-v1"
SCOPE = "v03-u280-fixed-high-address-v1"


def high_preflight(bundle):
    plan, _ = preflight(bundle)
    corpus = bundle / "high_address"
    require(plan["experiment"] == SCOPE and sha256(corpus / "corpus.json") == CORPUS_SHA,
            "unexpected high-address experiment or frozen corpus")
    frozen = read_json(corpus / "corpus.json")
    require(set(frozen) == {cid + "/" + name for cid in CASES for name in
                           ("case.json", *(r + suffix for r in ROLES for suffix in (".input.bin", ".expected.bin")))},
            "unexpected high-address inputs")
    for name, digest in frozen.items():
        require(sha256(corpus / name) == digest, "frozen high-address file differs: " + name)
    return plan


def prepare(run, ordinary):
    board = ordinary / "bundle"
    plan, _ = preflight(board)
    source = read_json(ORIGIN / "summary.json")
    require(source["status"] == "PASS" and source["corpus_sha256"] == CORPUS_SHA and
            source["image_sha256"] == plan["modules"][WIDE]["image_sha256"], "high-address model evidence differs")
    bundle = run / "bundle"
    shutil.copytree(board, bundle, ignore=shutil.ignore_patterns("plan.json"))
    for name in (HERE.name, "c_v03_board.py"):
        shutil.copyfile(HERE.parent / name, bundle / "scripts" / name)
    root = bundle / "high_address"
    root.mkdir()
    shutil.copyfile(ORIGIN / "corpus.json", root / "corpus.json")
    require(sha256(root / "corpus.json") == CORPUS_SHA, "high-address manifest changed")
    for name in read_json(root / "corpus.json"):
        destination = root / name
        destination.parent.mkdir(exist_ok=True)
        shutil.copyfile(ORIGIN / name, destination)
    plan.update(experiment=SCOPE, high_address_source_sha256=sha256(ORIGIN / "summary.json"),
                files={p.relative_to(bundle).as_posix(): sha256(p) for p in sorted(bundle.rglob("*")) if p.is_file()})
    write_json(bundle / "plan.json", plan)
    high_preflight(bundle)
    return Path(shutil.make_archive(str(run / "v03-u280-high-input"), "gztar", root_dir=run, base_dir="bundle"))


def reserve(ctx, bases):
    handles, addresses = {}, {}
    for role, base in bases.items():
        native, actual = P(), Q()
        ctx.check(ctx.lib.vx_buffer_reserve(ctx.device, base, SIZE, 3, C.byref(native)), "reserve_" + role)
        ctx.check(ctx.lib.vx_buffer_address(native, C.byref(actual)), "address_" + role)
        if actual.value != base:
            ctx.check(ctx.lib.vx_buffer_release(native), "release_wrong_address")
            raise ValueError("reserved address differs for " + role)
        handle = ctx.registry.register_native(actual.value, SIZE)
        ctx.buffers[handle] = (native, SIZE)
        handles[role], addresses[role] = handle, actual.value
    return handles, addresses


def pattern(epoch, role):
    return hashlib.sha256(("v03-u280-high/" + str(epoch) + "/" + role).encode()).digest() * (SIZE // 32)


def segments(base):
    # Keep every host transfer within one side of the HBM/4 KiB boundary.
    if base < FOUR_GIB < base + SIZE:
        return ((0, FOUR_GIB - base), (FOUR_GIB - base, SIZE))
    return ((0, SIZE),)


def write_buffer(ctx, handle, base, data):
    require(len(data) == SIZE, "wrong buffer length")
    for start, end in segments(base):
        ctx.write(handle, start, data[start:end])


def read_buffer(ctx, handle, base):
    return b"".join(ctx.read(handle, start, end - start) for start, end in segments(base))


def alias_check(ctx, out, report):
    out.mkdir()
    handles, actual = reserve(ctx, ALIAS)
    report["alias_bases"] = actual
    for epoch, order in enumerate((("low", "high"), ("high", "low")), 1):
        for role in order:
            ctx.write(handles[role], 0, pattern(epoch, role))
        for role in ALIAS:
            (out / ("{}-{}.bin".format(epoch, role))).write_bytes(ctx.read(handles[role], 0, SIZE))
        for role in ALIAS:
            require((out / ("{}-{}.bin".format(epoch, role))).read_bytes() == pattern(epoch, role),
                    "4 GiB alias qualification mismatch: epoch {} {}".format(epoch, role))
    for handle in handles.values():
        ctx.free(handle)


def check_buffers(frozen, out, phase):
    expected = "input" if phase == "before" else "expected"
    for role in ROLES:
        require((out / (role + "." + phase + ".bin")).read_bytes() ==
                (frozen / (role + "." + expected + ".bin")).read_bytes(),
                frozen.name + " " + phase + " mismatch: " + role)


def run_case(ctx, module, frozen, out, report):
    out.mkdir()
    case = read_json(frozen / "case.json")
    handles, bases = reserve(ctx, case["bases"])
    write_json(out / "reservations.json", bases)
    for role in ROLES:
        write_buffer(ctx, handles[role], bases[role], (frozen / (role + ".input.bin")).read_bytes())
    for role in ROLES:
        (out / (role + ".before.bin")).write_bytes(read_buffer(ctx, handles[role], bases[role]))
    check_buffers(frozen, out, "before")
    args = [BufferSlice(handles[r], GUARD, SIZE - GUARD, "r" if r == "x" else "w") for r in ROLES]
    args.extend(case[k] for k in ("n", "skip_lane", "bias"))
    report["launch_attempts"] += 1
    event = ctx.launch(module, WIDE, (case["grid"], 1, 1), (case["block"], 1, 1), args)
    (out / "params.bin").write_bytes(C.string_at(event.payload, len(event.plan.payload)))
    write_json(out / "event.json", ctx.wait(event))
    for role in ROLES:
        (out / (role + ".after.bin")).write_bytes(read_buffer(ctx, handles[role], bases[role]))
    check_buffers(frozen, out, "after")
    for handle in handles.values():
        ctx.free(handle)


def capture(bundle, run, backend, binding, lock, module):
    plan = high_preflight(bundle)
    descriptor, _ = validate(module, lock.read_bytes())
    require(descriptor["image_sha256"] == plan["modules"][WIDE]["image_sha256"], "wrong high-address image")
    out = run / backend
    out.mkdir()
    report = dict(backend=backend, binding_sha256=sha256(binding), phase="open", alias="NOT_RUN",
                  launch_attempts=0, completed=[])
    ctx = None
    try:
        ctx = Context(binding, lock, backend=backend, run_id=run.name)
        ctx.lib.vx_buffer_reserve.argtypes = [P, Q, Q, U, C.POINTER(P)]
        ctx.lib.vx_buffer_reserve.restype = C.c_int
        report["caps"] = {}
        for name, key in (("global_bytes", 5), ("vm", 15)):
            value = Q()
            ctx.check(ctx.lib.vx_device_query(ctx.device, key, C.byref(value)), "query_" + name)
            report["caps"][name] = value.value
        require(report["caps"] == dict(global_bytes=2 * FOUR_GIB, vm=0), "requires 8 GiB and disabled VM")
        report.update(phase="alias", alias="FAIL")
        alias_check(ctx, out / "alias", report)
        report.update(phase="load", alias="PASS")
        kernel = ctx.load(module)
        for cid in CASES:
            report["phase"] = cid
            run_case(ctx, kernel, bundle / "high_address" / cid, out / cid, report)
            report["completed"].append(cid)
        report["phase"] = "close"
        ctx.close()
        report["phase"] = "complete"
    except Exception as error:
        report["error"] = error.to_dict() if isinstance(error, ModuleError) else str(error)
        if ctx is not None and ctx.state == "READY":
            try:
                ctx.close()
            except Exception as cleanup:
                report["cleanup_error"] = str(cleanup)
        raise
    finally:
        report["device_state"] = ctx.state if ctx is not None else None
        write_json(out / "capture.json", report)


def review_capture(bundle, run, backend, binding):
    out = run / backend
    metadata = read_json(out / "capture.json")
    require(metadata["backend"] == backend and metadata["binding_sha256"] == sha256(binding) and
            metadata["phase"] == "complete" and metadata["device_state"] == "CLOSED" and
            metadata["caps"] == dict(global_bytes=2 * FOUR_GIB, vm=0) and
            metadata["alias"] == "PASS" and metadata["alias_bases"] == ALIAS and
            metadata["completed"] == list(CASES) and metadata["launch_attempts"] == len(CASES), "incomplete capture")
    for epoch in (1, 2):
        for role in ALIAS:
            require((out / "alias" / ("{}-{}.bin".format(epoch, role))).read_bytes() == pattern(epoch, role),
                    "saved alias control differs")
    for index, cid in enumerate(CASES, 1):
        raw = out / cid
        case_dir = bundle / "high_address" / cid
        case = read_json(case_dir / "case.json")
        require(read_json(raw / "reservations.json") == case["bases"], "saved device addresses differ: " + cid)
        expected = struct.pack("<QQQIII4x", *(case["bases"][r] + GUARD for r in ROLES),
                               case["n"], case["skip_lane"], case["bias"])
        require((raw / "params.bin").read_bytes() == expected and read_json(raw / "event.json") ==
                dict(backend=backend, status="COMPLETE", event_id=index, generation=0), "launch evidence differs: " + cid)
        for phase in ("before", "after"):
            check_buffers(case_dir, raw, phase)
    return dict(status="PASS", alias_readbacks=4, launches=len(CASES), payloads=len(CASES),
                full_buffers_before=len(CASES) * len(ROLES), full_buffers_after=len(CASES) * len(ROLES),
                capture_sha256=sha256(out / "capture.json"))


def board_review(bundle, run):
    high_preflight(bundle)
    gate = review_gate(run)
    receipt = review_capture(bundle, run, BOARD_BACKEND, run / "binding/binding.json")
    return dict(receipt, gate_sha256=gate)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("action", choices=("prepare", "run", "simulate", "capture", "review"))
    cli.add_argument("--bundle", type=Path, required=True)
    cli.add_argument("--output", type=Path, required=True)
    cli.add_argument("--bdf", choices=["0000:" + bus + ":00.1" for bus in BUSES])
    cli.add_argument("--backend", choices=(*BACKENDS, BOARD_BACKEND), default=BOARD_BACKEND)
    args = cli.parse_args()
    run, bundle = args.output.resolve(), args.bundle.resolve()
    require(re.fullmatch(r"c-v03-u280-[A-Za-z0-9_-]{1,50}", run.name), "choose a fresh c-v03-u280-* identifier")
    if args.action == "capture":
        if args.backend == BOARD_BACKEND:
            capture(bundle, run, args.backend, run / "binding/binding.json", bundle / "target_lock.json",
                    bundle / "modules" / WIDE)
        else:
            capture(bundle, run, args.backend, BINDINGS / args.backend / "binding.json", SIM_LOCK, ORIGIN / "module")
        return 0
    if args.action == "review":
        print(json.dumps(board_review(bundle, run)))
        return 0
    run.mkdir()
    report = dict(schema=SCOPE, argv=[sys.executable, "-B", *sys.argv], run_id=run.name, started_at=utc_now(),
                  status="RUNNING", commands=[], board_execution="NOT_RUN", alias="NOT_RUN",
                  independent_E="NOT_RUN", physical_recovery="NOT_RUN", timing7="OPEN")
    recorder = Recorder(run, report, dict(os.environ))
    try:
        if args.action == "prepare":
            archive = prepare(run, bundle)
            report.update(archive=archive.name, archive_sha256=sha256(archive),
                          plan_sha256=sha256(run / "bundle/plan.json"))
        elif args.action == "simulate":
            high_preflight(bundle)
            report["models"] = {}
            for backend, (driver, _, _) in BACKENDS.items():
                binding = BINDINGS / backend / "binding.json"
                for key in ("XCLBIN_PATH", "XCL_EMULATION_MODE", "VORTEX_CP_POLL_TIMEOUT_S"):
                    recorder.env.pop(key, None)
                recorder.env.update(VORTEX_DRIVER=driver, LD_LIBRARY_PATH=read_json(binding)["library_dir"],
                                    VORTEX_PROFILING="0", XRT_DEVICE_INDEX="0")
                run_stage(recorder, backend, [sys.executable, "-B", HERE, "capture", "--bundle", bundle,
                                               "--output", run, "--backend", backend], run, 360)
                report["models"][backend] = review_capture(bundle, run, backend, binding)
        else:
            require(args.bdf, "run requires --bdf")
            high_preflight(bundle)
            report["plan_sha256"] = sha256(bundle / "plan.json")
            bind(bundle, run, args.bdf, recorder)
            command, _ = recorder.command("capture", [sys.executable, "-B", bundle / "scripts" / HERE.name,
                                           "capture", "--bundle", bundle, "--output", run], run, 900)
            metadata = run / BOARD_BACKEND / "capture.json"
            if metadata.is_file():
                actual = read_json(metadata)
                report.update(alias=actual["alias"], last_phase=actual["phase"],
                              capture_error=actual.get("error"), launch_attempts=actual["launch_attempts"])
                if actual["launch_attempts"]:
                    report["board_execution"] = "FAIL"
            elif command["timed_out"]:
                report["board_execution"] = "FAIL"
            require(command["returncode"] == 0 and not command["timed_out"], "high-address capture failed")
            report.update(receipt=board_review(bundle, run), board_execution="PASS")
        report.update(status="PASS", exit_code=0)
    except Exception as error:
        report.update(status="FAIL", exit_code=1, error=str(error))
    report["finished_at"] = utc_now()
    recorder.save()
    print(report["status"], run, report.get("error", ""))
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
