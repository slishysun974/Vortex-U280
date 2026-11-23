"""Run the Iris module and save full readbacks. Only execution inputs are used."""
import argparse
import ctypes
from pathlib import Path
import struct
import sys

HERE = Path(__file__).resolve().parent
if sys.version_info[:2] == (3, 6):
    sys.path.insert(0, str(HERE.parent / "vendor/dataclasses-0.8"))
sys.path.insert(0, str(HERE.parents[1] / "scripts") if HERE.name != "scripts" else str(HERE))
from ptx_module import ModuleError
from ptx_runtime import BufferSlice, Context, Q
from run_native_smoke import sha256
from run_ptx_copy import read_json, require, write_json

ROLES = ("x", "sums", "out")
ENTRY = "iris_nearest_centroid_u32"


def load_inputs(inputs, spec):
    n, block, grid = spec["n"], spec["block"], spec["grid"]
    require(type(n) is int and 0 <= n <= 0xffffffff and block == 32 and grid == max(1, (n+31)//32),
            "invalid Iris geometry")
    require(spec["offset"] == 16 and spec["access_bytes"] == dict(x=16*n, sums=48, out=16*n), "invalid slice")
    images = {r:(inputs / spec["id"] / (r + ".input.bin")).read_bytes() for r in ROLES}
    for role in ROLES:
        capacity = 48 if role == "sums" else grid * block * 16
        require(len(images[role]) == 32+capacity, "invalid allocation size for " + role)
    for role, limit in (("x",100), ("sums",3500)):
        length = spec["access_bytes"][role]
        require(all(v <= limit for (v,) in struct.iter_unpack("<I", images[role][16:16+length])),
                "invalid input value in " + role)
    return images


def capture(a):
    specs = read_json(a.inputs / "manifest.json")["cases"]
    a.output.mkdir()
    record = dict(backend=a.backend, binding_sha256=sha256(a.binding), module_sha256=sha256(a.module/"manifest.json"),
                  lock_sha256=sha256(a.lock), launch_attempts=0, completed=[])
    ctx = None
    try:
        ctx = Context(a.binding, a.lock, backend=a.backend, run_id=a.output.parent.name)
        record["initial_caps"] = ctx.query_caps()
        module = ctx.load(a.module)
        require(module.manifest["entry"] == ENTRY, "wrong entry")
        for spec in specs:
            cid = spec["id"]
            record["current_case"] = cid
            images = load_inputs(a.inputs, spec)
            raw = a.output / cid
            raw.mkdir()
            handles, bases, args = {}, {}, []
            for role in ROLES:
                handle = ctx.alloc(len(images[role]))
                handles[role] = handle
                base = Q()
                ctx.check(ctx.lib.vx_buffer_address(ctx.buffers[handle][0], ctypes.byref(base)), "address")
                bases[role] = base.value
                ctx.write(handle, 0, images[role])
                args.append(BufferSlice(handle, 16, spec["access_bytes"][role], "w" if role == "out" else "r"))
            write_json(raw/"bases.json", bases)
            for role, handle in handles.items():
                before = ctx.read(handle, 0, len(images[role]))
                (raw/(role+".before.bin")).write_bytes(before)
                require(before == images[role], "H2D round-trip differs for " + cid + "/" + role)
            record["launch_attempts"] += 1
            print("launch", cid, spec["n"], flush=True)
            event = ctx.launch(module, ENTRY, (spec["grid"],1,1), (spec["block"],1,1), args+[spec["n"]])
            (raw/"params.bin").write_bytes(ctypes.string_at(event.payload, len(event.plan.payload)))
            write_json(raw/"event.json", ctx.wait(event))
            for role, handle in handles.items():
                (raw/(role+".after.bin")).write_bytes(ctx.read(handle, 0, len(images[role])))
                ctx.free(handle)
            record["completed"].append(cid)
            del record["current_case"]
        ctx.unload(module)
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
        write_json(a.output/"capture.json", record)


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    for arg in ("inputs","module","binding","lock","output"):
        cli.add_argument("--"+arg, type=Path, required=True)
    cli.add_argument("--backend", required=True, choices=("simx","rtlsim","xrtsim","u280-xrt"))
    capture(cli.parse_args())
