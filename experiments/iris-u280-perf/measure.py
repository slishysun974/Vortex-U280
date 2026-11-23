"""Measure resident-module Iris inference on the physical board (Python 3.6)."""
import argparse
import ctypes
import hashlib
import json
from pathlib import Path
import sys
import time

if sys.version_info[:2] == (3, 6):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "vendor/dataclasses-0.8"))
from iris_inputs import ENTRY, ROLES, load_inputs
from ptx_runtime import BufferSlice, Context, Q
from run_native_smoke import sha256
from run_ptx_copy import read_json, require, write_json
from u280_aligned_counters import CounterCapture
from telemetry import Sensors, snapshot

CLOCK = getattr(time,"perf_counter_ns",lambda: int(time.perf_counter()*1e9))


def measure(a):
    plan = read_json(a.inputs/"manifest.json")
    a.output.mkdir()
    record = dict(backend=a.backend, launch_attempts=0, completed=[], module_sha256=sha256(a.module/"manifest.json"),
                  binding_sha256=sha256(a.binding),lock_sha256=sha256(a.lock))
    ctx = None
    sensors = None
    try:
        ctx = Context(a.binding,a.lock,backend=a.backend,run_id=a.output.parent.name)
        record["caps"] = ctx.query_caps()
        bdf = read_json(a.binding)["bdf"]
        snapshot(bdf,a.output,"sensors-before")
        start = CLOCK()
        module = ctx.load(a.module)
        record["load_ns"] = CLOCK()-start
        counts = CounterCapture(ctx,a.output)
        cases = {}
        for spec in plan["cases"]:
            images = load_inputs(a.inputs,spec)
            handles, args, bases = {}, [], {}
            for role in ROLES:
                handle = ctx.alloc(len(images[role]))
                handles[role] = handle
                base = Q()
                ctx.check(ctx.lib.vx_buffer_address(ctx.buffers[handle][0],ctypes.byref(base)),"address")
                bases[role] = base.value
                args.append(BufferSlice(handle,16,spec["access_bytes"][role],"w" if role=="out" else "r"))
            key = spec["id"]
            raw = a.output/key
            raw.mkdir()
            write_json(raw/"bases.json",bases)
            cases[key] = (spec,images,handles,args+[spec["n"]],raw)
        sensors = Sensors(bdf,a.output)
        sensors.thread.start()
        with (a.output/"samples.jsonl").open("x",encoding="utf-8") as stream:
            for item in plan["schedule"]:
                key = item["case"]
                record["current_case"] = key
                spec,images,handles,args,raw = cases[key]
                start = CLOCK()
                for role in ROLES:
                    ctx.write(handles[role],0,images[role])
                uploaded = CLOCK()
                before = counts.before(item)
                require(before is not None,"no readable idle counters")
                record["launch_attempts"] += 1
                submitted = CLOCK()
                event = ctx.launch(module,ENTRY,(spec["grid"],1,1),(32,1,1),args)
                completion = ctx.wait(event)
                retired = CLOCK()
                delta = counts.after(item,before)
                require(delta is not None,"unqualified MPM delta")
                download = CLOCK()
                output = ctx.read(handles["out"],0,len(images["out"]))
                downloaded = CLOCK()
                for role in ("x","sums"):
                    readback = ctx.read(handles[role],0,len(images[role]))
                    if readback != images[role]:
                        (raw/(role+".mismatch.bin")).write_bytes(readback)
                        raise ValueError("input changed: "+key+"/"+role)
                payload = bytes(event.plan.payload)
                if item["scope"] == "fold" or (item["scope"] == "timed" and item["trial"] == 29):
                    (raw/"out.bin").write_bytes(output)
                    (raw/"params.bin").write_bytes(payload)
                elapsed = dict(h2d_ns=uploaded-start, wait_ns=retired-submitted, d2h_ns=downloaded-download)
                sample = dict(item, n=spec["n"], event=completion, counts=delta, total_ns=sum(elapsed.values()),
                              submit_monotonic_ns=submitted, retired_monotonic_ns=retired,
                              payload_sha256=hashlib.sha256(payload).hexdigest(), full_inputs_match=True,
                              output_sha256=hashlib.sha256(output).hexdigest(), **elapsed)
                stream.write(json.dumps(sample)+"\n")
                stream.flush()
                record["completed"].append(key)
        sensors.stop()
        sensors = None
        snapshot(bdf,a.output,"sensors-after")
        counts.close(len(plan["schedule"])-2)
        require(counts.record["status"] == "PASS","counter qualification failed")
        for _,_,handles,_,_ in cases.values():
            for handle in handles.values():
                ctx.free(handle)
        ctx.unload(module)
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
        if sensors is not None and sensors.thread.is_alive():
            sensors.stop()
        record["final_state"] = ctx.state if ctx is not None else None
        write_json(a.output/"capture.json",record)


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    for arg in ("inputs","module","binding","lock","output"):
        cli.add_argument("--"+arg,type=Path,required=True)
    cli.add_argument("--backend",choices=["u280-xrt"],required=True)
    measure(cli.parse_args())
