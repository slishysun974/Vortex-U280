"""Capture frozen E inputs on one real C runtime context, without computing outputs.

CPython 3.6 compatible; physical u280-xrt uses the normal production board gate.
Caller supplies an already prepared binding, LD_LIBRARY_PATH and VORTEX_DRIVER.
No SSH, card configuration, reset, or CPU fallback is performed by this script.
"""
import argparse
import ctypes
import json
import os
from pathlib import Path
import platform
import sys
import time
import traceback

from runtime_unseen_common import FROZEN_SHA256, PRODUCTION, corpus, dump, need, read, sha

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))


def execute(args):
    args.out.mkdir(parents=True, exist_ok=False)
    record = dict(schema="e-runtime-unseen-capture-v1", status="RUNNING", backend=args.backend,
                  argv=sys.argv, cwd=os.getcwd(), python=platform.python_version(),
                  manifest_sha256=args.manifest_sha256, cases=[], modules={}, allocations=[],
                  context_creations=0, module_loads=0, module_unloads=0,
                  environment={k: os.environ.get(k) for k in ("VORTEX_DRIVER", "LD_LIBRARY_PATH", "PYTHONPATH")},
                  runner_sha256=sha(Path(__file__).read_bytes()), started=time.time())
    dump(args.out / "capture.json", record)
    context = None
    try:
        manifest = corpus(args.corpus, args.manifest_sha256)
        record["binding_sha256"] = sha(args.binding.read_bytes())
        record["target_lock_sha256"] = sha(args.target_lock.read_bytes())
        record["implementation"] = {}
        snapshot = args.out / "implementation"
        snapshot.mkdir()
        for name in PRODUCTION:
            data = (ROOT / "scripts" / name).read_bytes()
            (snapshot / name).write_bytes(data)
            record["implementation"][name] = sha(data)
        (args.out / "binding.json").write_bytes(args.binding.read_bytes())
        (args.out / "target_lock.json").write_bytes(args.target_lock.read_bytes())
        # Independent source gate; production validates all remaining package files.
        for name, source in manifest["sources"].items():
            module_path = args.modules / name
            need(sha((module_path / "source.ptx").read_bytes()) == source["sha256"], "wrong module source " + name)
            mm = read(module_path / "manifest.json")
            need(mm["entry"] == source["entry"], "wrong entry " + name)
            record["modules"][name] = dict(manifest_sha256=sha((module_path / "manifest.json").read_bytes()),
                                           image_sha256=sha((module_path / mm["image_file"]).read_bytes()),
                                           source_sha256=source["sha256"], path=str(module_path))
        from ptx_runtime import Context, BufferSlice
        os.chdir(args.out)
        context = Context(args.binding, args.target_lock, backend=args.backend, run_id=args.out.name)
        record["context_creations"] = 1
        record["caps_initial"] = context.query_caps()
        record["queue_native"] = context.queue.value
        handles = {}
        current = None
        current_name = None
        group = None
        for case in manifest["cases"]:
            case_dir = args.out / case["id"]
            case_dir.mkdir()
            state = dict(id=case["id"], module=case["module"], allocation_generation=case["allocation_generation"], phases={})
            record["cases"].append(state)
            if group != case["allocation_generation"]:
                for handle in handles.values():
                    context.free(handle)
                handles = {role: context.alloc(case["allocation_words"] * 4) for role in ("x", "y", "z")}
                group = case["allocation_generation"]
                allocation = dict(generation=group, bases={}, bytes=case["allocation_words"] * 4)
                # Ask native runtime directly, not BufferRegistry.pointer/packer.
                for role, handle in handles.items():
                    address = ctypes.c_uint64()
                    status = context.lib.vx_buffer_address(context.buffers[handle][0], ctypes.byref(address))
                    need(status == 0, "native allocation-address query failed")
                    allocation["bases"][role] = address.value
                record["allocations"].append(allocation)
            state["bases"] = dict(record["allocations"][-1]["bases"])
            if current_name != case["module"]:
                if current is not None:
                    context.unload(current)
                    record["module_unloads"] += 1
                current = context.load(args.modules / case["module"])
                current_name = case["module"]
                record["module_loads"] += 1
            state["phases"]["load"] = "PASS"
            for role, handle in handles.items():
                data = (args.corpus / "vectors" / case["id"] / (role + ".input.bin")).read_bytes()
                context.write(handle, 0, data)
            state["phases"]["H2D"] = "PASS"
            roles = ("x", "z") if case["semantics"] == "copy" else ("x", "y", "z")
            values = [BufferSlice(handles[role], 4 * case["offsets_words"][role], 4 * case["n"], "w" if role == "z" else "r") for role in roles]
            values.append(case["n"])
            if case["semantics"] == "affine":
                values.append(case["alpha"])
            state["before"] = context.query_caps()
            event = context.launch(current, manifest["sources"][case["module"]]["entry"],
                                   (case["grid"], 1, 1), (case["block"], 1, 1), values)
            state["phases"]["launch"] = "PASS"
            state["launched"] = context.query_caps()
            state["event_id"] = event.id
            state["queue_native"] = context.queue.value
            state["grid"] = list(event.plan.grid)
            state["block"] = list(event.plan.block)
            (case_dir / "params.plan.bin").write_bytes(event.plan.payload)
            before_payload = ctypes.string_at(event.payload, len(event.plan.payload))
            (case_dir / "params.before_mutation.bin").write_bytes(before_payload)
            # A caller is allowed to reuse/change its argument list after launch.
            values[-1] = 0xdeadbeef
            values[0] = None
            (case_dir / "params.after_mutation.bin").write_bytes(ctypes.string_at(event.payload, len(event.plan.payload)))
            state["wait"] = context.wait(event, args.timeout_ms)
            state["phases"]["wait"] = "PASS"
            state["event_completed"] = event.completed
            state["after"] = context.query_caps()
            for role, handle in handles.items():
                (case_dir / (role + ".actual.bin")).write_bytes(context.read(handle, 0, case["allocation_words"] * 4))
            state["phases"]["D2H"] = "PASS"
            state["files"] = {p.name: sha(p.read_bytes()) for p in sorted(case_dir.iterdir())}
            state["status"] = "CAPTURED"
            dump(args.out / "capture.json", record)
            print("CAPTURED", args.backend, case["id"], case["module"], flush=True)
        context.unload(current)
        record["module_unloads"] += 1
        for handle in handles.values():
            context.free(handle)
        record["caps_before_close"] = context.query_caps()
        context.close()
        record["final_state"] = context.state
        record["implementation_after"] = {name: sha((ROOT / "scripts" / name).read_bytes()) for name in PRODUCTION}
        need(record["implementation_after"] == record["implementation"], "production source changed during execution")
        record.update(status="COMPLETE", exit_code=0, finished=time.time())
        dump(args.out / "capture.json", record)
        return 0
    except Exception as error:
        record.update(status="FAIL", exit_code=1, error=str(error), traceback=traceback.format_exc(), finished=time.time())
        if context is not None:
            record["failure_state"] = context.state
            # No recovery/reset or forced resource release on failed execution.
            if context.state == "READY":
                try:
                    context.close()
                except Exception as close_error:
                    record["close_error"] = str(close_error)
        dump(args.out / "capture.json", record)
        print(record["traceback"], file=sys.stderr)
        return 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("corpus", "modules", "binding", "target-lock", "out"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--backend", required=True, choices=("simx", "rtlsim", "xrtsim", "u280-xrt"))
    parser.add_argument("--manifest-sha256", default=FROZEN_SHA256)
    parser.add_argument("--timeout-ms", type=int, default=60000)
    args = parser.parse_args()
    for name in ("corpus", "modules", "binding", "target_lock", "out"):
        setattr(args, name, getattr(args, name).resolve())
    return execute(args)


if __name__ == "__main__":
    sys.exit(main())
