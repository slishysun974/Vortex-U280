"""Receive the D P0 handoff through the production C module builder and runtime."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import re
import shutil
import struct
import sys

from ptx_module import ModuleError
from ptx_runtime import BufferSlice, Context
from run_native_smoke import PROJECT, Recorder, sha256, utc_now
from run_ptx_copy import BOARD_LOCK, SIM_LOCK, VORTEX, read_json, require, run_stage, write_json
from runtime_backends import BACKENDS

FORMS = "p0_form_witness"
WIDE = "guarded_wide_offset"
DELIVERIES = {
    FORMS: ("d-p0-forms-20261120-v1", "38720942427752ede47d89b7fa5637b150a52d0ccaa299294909f4da45e97e9a"),
    WIDE: ("d-guarded-wide-closeout-20261120-v1", "9cd3b975adb2f73d3a921a2eefbd37ffaa560b1495dd697523b0186df8ad54c0"),
}
ROLES = ("x", "z", "audit")
HERE = Path(__file__).resolve()
BINDINGS = PROJECT / "results/c-runtime-merge-20261111-v3/bindings"
DEFAULT_CORPUS = PROJECT / "results/c-v03-corpus-20261120-v1"
CORPUS_SHA = "68b6a6f21e43cc9712c4c71765b5b02930a854f86104f05d5183e96b81687bc4"
TOOLCHAIN = Path("/opt/vortex-ab/toolchains/8c64cf921d3c6c456e80f00d24482d0aa2153a82-rtlsim-d3-v1")


def corpus(root):
    require(sha256(root / "manifest.json") == CORPUS_SHA, "unexpected receiver corpus")
    manifest = read_json(root / "manifest.json")
    for name, expected in manifest["files"].items():
        require(sha256(root / name) == expected, "frozen file differs: " + name)
    return manifest


def build_modules(run, frozen, rec):
    builder = [sys.executable, "-B", PROJECT / "scripts/ptx_module.py"]
    for entry, (delivery_id, identity) in DELIVERIES.items():
        target = run / "modules" / entry
        origin = PROJECT / "results" / delivery_id / "module"
        require(sha256(origin / "manifest.json") == identity, "unexpected D delivery")
        for action, args in (
                ("prepare", [frozen / "sources" / (entry + ".ptx"), "--output", target,
                             "--hardware", SIM_LOCK.with_name("native_smoke.json")]),
                ("build", [target, "--vortex-source", VORTEX, "--tooldir", TOOLCHAIN,
                           "--build-root", PROJECT / "build" / run.name / entry]),
                ("validate", [target])):
            run_stage(rec, action + "_" + entry, builder + [action, *args, "--target-lock", SIM_LOCK], run, 360)
        receipt = read_json(origin / "manifest.json")
        frontend = read_json(target / "frontend_manifest.json")
        require(frontend["validation_revision"] == "p0-static-v2" and
                frontend["compiler_sha256"] == sha256(PROJECT / "scripts/ptx_frontend_v12.py"), "frontend identity")
        # Build logs carry paths and timestamps. Compare the actual handoff bytes and executable.
        names = ("source.ptx", "ir.json", "source_map.json", "kernel_body.hpp", "frontend_manifest.json",
                 "profile.json", "abi.json", "target_lock.json", "hardware.json", "kernel.cpp", "Makefile", "kernel.vxbin")
        hashes = {name: sha256(target / name) for name in names}
        for name, observed in hashes.items():
            require(observed == receipt["files"][name] == sha256(origin / name), "handoff differs: " + name)
        rec.summary["modules"][entry] = dict(status="PASS", delivery=delivery_id, delivery_manifest_sha256=identity,
             rebuilt_manifest_sha256=sha256(target / "manifest.json"), identical_files=hashes)
        record, output = rec.command("wrong_lock_" + entry, builder + ["validate", target, "--target-lock", BOARD_LOCK], run)
        require(record["returncode"] == 1 and not record["timed_out"] and
                json.loads(output)["error"]["code"] == "E_TARGET_MISMATCH", "wrong target was not diagnosed")


def capture(run, frozen, backend, manifest, *, binding=None, target_lock=SIM_LOCK, modules=None):
    binding = binding or BINDINGS / backend / "binding.json"
    modules = modules or run / "modules"
    out = run / backend
    out.mkdir()
    size = manifest["words"] * 4
    record = dict(binding_sha256=sha256(binding), cases=[], loads=[], launch_attempts=0)
    ctx = None
    try:
        ctx = Context(binding, target_lock, backend=backend, run_id=run.name)
        record["initial"] = ctx.query_caps()
        handles = {role: ctx.alloc(size) for role in ROLES}
        addresses = {}
        for role, handle in handles.items():
            address = ctypes.c_uint64()
            require(ctx.lib.vx_buffer_address(ctx.buffers[handle][0], ctypes.byref(address)) == 0,
                    "native address query failed")
            addresses[role] = address.value
        record["native_bases"] = addresses
        current, loaded = None, None
        for case in manifest["cases"]:
            entry, cid = case["entry"], case["id"]
            record["current_case"] = cid
            stage = out / cid
            stage.mkdir()
            if loaded != entry:
                if current is not None:
                    ctx.unload(current)
                current = ctx.load(modules / entry)
                loaded = entry
                record["loads"].append(entry)
            for role in ROLES:
                ctx.write(handles[role], 0, (frozen / cid / (role + ".input.bin")).read_bytes())
            args = []
            for role in (ROLES[:2] if entry == FORMS else ROLES):
                offset = 4 * case["offsets"][role]
                args.append(BufferSlice(handles[role], offset, size - offset, "r" if role == "x" else "w"))
            args.extend(case["scalars"])
            record["launch_attempts"] += 1
            event = ctx.launch(current, entry, (case["grid"], 1, 1), (case["block"], 1, 1), args)
            (stage / "params.bin").write_bytes(ctypes.string_at(event.payload, len(event.plan.payload)))
            launched = ctx.query_caps()["device_state"]
            completed = ctx.wait(event, 60000)
            for role in ROLES:
                (stage / (role + ".actual.bin")).write_bytes(ctx.read(handles[role], 0, size))
            record["cases"].append(dict(id=cid, entry=entry, event=completed, grid=event.plan.grid,
                block=event.plan.block, launched=launched, after=ctx.query_caps()["device_state"]))
            check_readbacks(stage, frozen / cid, case, addresses)
            record.pop("current_case")
        ctx.unload(current)
        for handle in handles.values():
            ctx.free(handle)
        ctx.close()
    except Exception as error:
        record["error"] = error.to_dict() if isinstance(error, ModuleError) else str(error)
        if ctx is not None and ctx.state == "READY":
            try:
                ctx.close()
            except Exception as cleanup:
                record["cleanup_error"] = str(cleanup)
        raise
    finally:
        record["final_state"] = ctx.state if ctx is not None else None
        write_json(out / "capture.json", record)


def check_readbacks(stage, frozen_case, case, bases):
    cid, entry = case["id"], case["entry"]
    files = {}
    for role in ROLES:
        path = stage / (role + ".actual.bin")
        expected = frozen_case / (role + ".expected.bin")
        require(path.read_bytes() == expected.read_bytes(), f"{cid}/{role} readback differs")
        files[path.name] = sha256(path)
    ptr = [bases[r] + 4 * case["offsets"][r] for r in (ROLES[:2] if entry == FORMS else ROLES)]
    payload = stage / "params.bin"
    expected = struct.pack("<QQI4x" if entry == FORMS else "<QQQIII4x", *ptr, *case["scalars"])
    require(payload.read_bytes() == expected, "ABI snapshot differs: " + cid)
    files[payload.name] = sha256(payload)
    return files


def review_backend(run, frozen, backend, manifest, *, binding=None):
    binding = binding or BINDINGS / backend / "binding.json"
    root = run / backend
    captured = read_json(root / "capture.json")
    caps = captured["initial"]
    require((caps["backend"], caps["device_state"], caps["threads"], caps["warps"], caps["cores"]) ==
            (backend, "READY", 4, 8, 1), "backend or geometry differs")
    require("error" not in captured and captured["final_state"] == "CLOSED" and
            captured["binding_sha256"] == sha256(binding), "failed capture or backend binding/closure differs")
    bases = captured["native_bases"]
    size = 4 * manifest["words"]
    ordered = sorted(bases[r] for r in ROLES)
    require(all(a > 0 and a % 4 == 0 for a in ordered) and
            all(b - a >= size for a, b in zip(ordered, ordered[1:])), "invalid native buffers")
    cases = manifest["cases"]
    loads = [c["entry"] for i, c in enumerate(cases) if i == 0 or cases[i - 1]["entry"] != c["entry"]]
    require(len(captured["cases"]) == len(cases) and captured["loads"] == loads, "case or load sequence differs")
    hashes = {}
    for event_id, (case, actual) in enumerate(zip(cases, captured["cases"]), 1):
        cid, entry = case["id"], case["entry"]
        require(actual["id"] == cid and actual["entry"] == entry and
                actual["grid"] == [case["grid"], 1, 1] and actual["block"] == [case["block"], 1, 1] and
                (actual["launched"], actual["after"]) == ("RUNNING", "READY") and actual["event"] ==
                dict(status="COMPLETE", event_id=event_id, generation=caps["generation"], backend=backend),
                "incorrect launch or event: " + cid)
        hashes[cid] = check_readbacks(root / cid, frozen / cid, case, bases)
    return dict(status="PASS", launches=len(cases), module_loads=len(loads), full_arrays=len(cases) * len(ROLES),
                payloads=len(cases), files=hashes)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("action", choices=("receive", "capture", "review"))
    cli.add_argument("--run-id", required=True)
    cli.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    cli.add_argument("--backend", choices=BACKENDS)
    args = cli.parse_args()
    if not re.fullmatch(r"c-v03-receipt-[A-Za-z0-9_-]{1,64}", args.run_id):
        cli.error("choose a c-v03-receipt-* identifier")
    run = PROJECT / "results" / args.run_id
    frozen = args.corpus.resolve()
    if args.action != "receive":
        manifest = corpus(frozen)
        if args.action == "capture":
            if not args.backend:
                cli.error("capture requires a backend")
            capture(run, frozen, args.backend, manifest)
        else:
            for backend in BACKENDS:
                result = review_backend(run, frozen, backend, manifest)
                require(result == read_json(run / (backend + ".review.json")), "saved review differs")
                print(backend, result["launches"], "PASS")
        return 0
    run.mkdir()
    report = dict(argv=sys.argv, run_id=run.name, status="RUNNING", started_at=utc_now(), commands=[],
                  scope="automated C runtime V03 technical receipt", independent_E="NOT_RUN",
                  human_receipt="NOT_RUN", u280="NOT_RUN", corpus_sha256=CORPUS_SHA, modules={}, backends={})
    rec = Recorder(run, report, dict(os.environ))
    try:
        manifest = corpus(frozen)
        report["implementation"] = {}
        for name in (HERE.name, "freeze_c_v03_cases.py", "ptx_module.py", "ptx_runtime.py", "ptx_launch.py",
                     "ptx_frontend_v12.py", "runtime_backends.py", "run_native_smoke.py", "run_ptx_copy.py"):
            source = PROJECT / "scripts" / name
            dest = run / "implementation" / name
            dest.parent.mkdir(exist_ok=True)
            shutil.copyfile(source, dest)
            report["implementation"][name] = sha256(dest)
        require(report["implementation"]["freeze_c_v03_cases.py"] == manifest["files"]["oracle.py"], "oracle changed")
        build_modules(run, frozen, rec)
        for backend, (driver, _, _) in BACKENDS.items():
            binding = read_json(BINDINGS / backend / "binding.json")
            run_stage(rec, "capture_" + backend, ["env", "-u", "XCLBIN_PATH", "-u", "XCL_EMULATION_MODE",
                "VORTEX_DRIVER=" + driver, "LD_LIBRARY_PATH=" + binding["library_dir"], "VORTEX_PROFILING=0",
                "XRT_DEVICE_INDEX=0", sys.executable, "-B", HERE, "capture", "--run-id", run.name,
                "--backend", backend, "--corpus", frozen], run, 300)
            result = review_backend(run, frozen, backend, manifest)
            write_json(run / (backend + ".review.json"), result)
            report["backends"][backend] = {k: v for k, v in result.items() if k != "files"}
        run_stage(rec, "offline_review", [sys.executable, "-B", HERE, "review", "--run-id", run.name,
                                         "--corpus", frozen], run)
        require(all(sha256(PROJECT / "scripts" / n) == h for n, h in report["implementation"].items()),
                "implementation changed during receipt")
        report.update(status="PASS", exit_code=0)
    except Exception as exc:
        report.update(status="FAIL", exit_code=1, error=str(exc))
    report["finished_at"] = utc_now()
    rec.save()
    print(report["status"], run, report.get("error", ""))
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
