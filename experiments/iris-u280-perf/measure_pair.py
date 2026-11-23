"""Run native and PTX Iris images in the same queue against the same buffers."""
import argparse
import ctypes
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
if sys.version_info[:2] == (3, 6):
    sys.path.insert(0, str(HERE.parent / "vendor/dataclasses-0.8"))
if HERE.name == "scripts":
    from iris_inputs import ENTRY, ROLES, load_inputs
else:
    sys.path.insert(0, str(HERE.parent / "iris-u280"))
    from capture import ENTRY, ROLES, load_inputs

from ptx_module import inspect_vxbin, validate
from ptx_runtime import BufferSlice, Context, Q
from run_native_smoke import sha256
from run_ptx_copy import read_json, require, write_json
from u280_aligned_counters import CounterCapture


def capture(a):
    a.output.mkdir()
    plan = read_json(a.inputs / "manifest.json")
    physical = a.backend == "u280-xrt"
    record = dict(backend=a.backend, launch_attempts=0, completed=[], binding_sha256=sha256(a.binding),
                  lock_sha256=sha256(a.lock), input_manifest_sha256=sha256(a.inputs / "manifest.json"))
    ctx = counts = None
    try:
        ptx, ptx_image = validate(a.module, a.lock.read_bytes())
        native = read_json(a.module / "native.json")
        image = (a.module / "native.vxbin").read_bytes()
        ptx_manifest = sha256(a.module / "manifest.json")
        require(native["lock_sha256"] == record["lock_sha256"] and native["ptx_manifest_sha256"] == ptx_manifest
                and native["native_image_sha256"] == hashlib.sha256(image).hexdigest()
                and native["symbol"] == inspect_vxbin(image), "native module identity differs")
        record["images"] = dict(native=native["native_image_sha256"], ptx=ptx["image_sha256"])
        record["ptx_manifest_sha256"] = ptx_manifest
        ctx = Context(a.binding, a.lock, backend=a.backend, run_id=a.output.parent.name)
        record["caps"] = ctx.query_caps()
        images_by_route = {"ptx": (ptx, ptx_image),
                           "native": (dict(ptx, image_sha256=record["images"]["native"]), image)}
        cases = {}
        for spec in plan["cases"]:
            key = spec["id"]
            images = load_inputs(a.inputs, spec)
            handles = {role: ctx.alloc(len(images[role])) for role in ROLES}
            bases = {}
            for role, handle in handles.items():
                address = Q()
                ctx.check(ctx.lib.vx_buffer_address(ctx.buffers[handle][0], ctypes.byref(address)), "address")
                bases[role] = address.value
            args = [BufferSlice(handles[role], 16, spec["access_bytes"][role], "w" if role == "out" else "r")
                    for role in ROLES]
            raw = a.output / key
            raw.mkdir()
            write_json(raw / "bases.json", bases)
            cases[key] = spec, images, handles, args + [spec["n"]], raw

        counts = CounterCapture(ctx, a.output) if physical else None
        first_output = None
        with (a.output / "samples.jsonl").open("x", encoding="utf-8", newline="\n") as stream:
            for item in plan["schedule"]:
                key, route = item["case"], item["route"]
                spec, images, handles, args, raw = cases[key]
                record["current_case"] = item
                # Both fixed images reserve the same VMA. Only one may be loaded.
                # Complete the upload before the first idle counter read.
                module = ctx._load_verified_image(*images_by_route[route])
                for role in ROLES:
                    ctx.write(handles[role], 0, images[role])
                if physical:
                    before = counts.before(item)
                    require(before is not None, "unqualified pre-launch MPM sample")
                record["launch_attempts"] += 1
                event = ctx.launch(module, ENTRY, (spec["grid"], 1, 1), (32, 1, 1), args)
                completion = ctx.wait(event)
                delta = counts.after(item, before) if physical else None
                require(not physical or delta is not None, "unqualified post-launch MPM sample")
                output = ctx.read(handles["out"], 0, len(images["out"]))
                output_hash = hashlib.sha256(output).hexdigest()
                if output_hash != plan["expected"][key]:
                    (raw / (route + ".mismatch.bin")).write_bytes(output)
                    raise ValueError("output, padding or guard differs: " + key + "/" + route)
                if item["scope"] != "probe":
                    if item["position"] == 0:
                        first_output = output
                    else:
                        require(first_output == output, "paired full readbacks differ")
                for role in ("x", "sums"):
                    require(ctx.read(handles[role], 0, len(images[role])) == images[role], "input changed: " + role)
                payload = bytes(event.plan.payload)
                ctx.unload(module)
                if item["save"]:
                    (raw / (route + ".out.bin")).write_bytes(output)
                    (raw / (route + ".params.bin")).write_bytes(payload)
                sample = dict(item, n=spec["n"], event=completion, counts=delta, full_inputs_match=True,
                              payload_sha256=hashlib.sha256(payload).hexdigest(), output_sha256=output_hash)
                stream.write(json.dumps(sample) + "\n")
                stream.flush()
                record["completed"].append(key)
        if physical:
            counts.close(len(plan["schedule"]) - 2)
            require(counts.record["status"] == "PASS", "incomplete MPM qualification")
            gate = ctx.board_gate
            clocks = gate.report("paired-end")["platforms"][0]["clocks"]
            require([c for c in clocks if c["id"] == "DATA_CLK"] == [gate.record["clock_readback"]],
                    "DATA_CLK changed during the session")
        ctx.close()
        del record["current_case"]
    except Exception as error:
        record["error"] = str(error)
        if ctx is not None and ctx.state == "READY":
            try:
                ctx.close()
            except Exception as cleanup:
                record["cleanup_error"] = str(cleanup)
        raise
    finally:
        if counts is not None and not counts.stream.closed:
            counts.stream.close()
        record["final_state"] = ctx.state if ctx is not None else None
        write_json(a.output / "capture.json", record)


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    for name in ("inputs", "module", "binding", "lock", "output"):
        cli.add_argument("--" + name, required=True, type=Path)
    cli.add_argument("--backend", choices=("u280-xrt", "simx"), required=True)
    capture(cli.parse_args())
