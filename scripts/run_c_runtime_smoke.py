"""Execute the integrated C API with full captures and an explicit backend.

Only valid kernels and synchronous API rejections; no timeout/fault injection.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import traceback

def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def write(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")

def worker(args):
    from ptx_runtime import Context
    from ptx_module import ModuleError
    from ptx_launch import BufferSlice

    args.output.mkdir(parents=True, exist_ok=False)
    os.chdir(args.output)
    module_path = args.module
    result = dict(status="RUNNING", backend=args.backend, kernel=args.kernel,
                  cases=[], rejections=[], u280="NOT_RUN", independent_E="NOT_RUN",
                  scope="integrated project runtime functional smoke; author oracle, no fault recovery",
                  module_manifest_sha256=sha256(module_path / "manifest.json"),
                  image_sha256=sha256(module_path / "kernel.vxbin"))
    ctx = None
    try:
        ctx = Context(args.binding, args.target_lock, backend=args.backend, run_id=args.output.name)
        result["caps"] = ctx.query_caps()
        module = ctx.load(module_path)
        count, offset, capacity = (2 if args.kernel == "copy" else 3), 8, 1048
        buffers = [ctx.alloc(capacity * 4) for _ in range(count)]
        geometries = [(n, 32, 0xffffffff) for n in (0, 1, 31, 32, 33, 63, 64, 65, 257, 1024)]
        geometries += [(65, b, 0xffffffff) for b in (1, 7, 31)]
        if args.kernel == "affine":
            geometries += [(65, 32, a) for a in (0, 1)]
        pack = lambda values: struct.pack("<%dI" % len(values), *values)

        def reject(code, label, call):
            try:
                call()
            except ModuleError as error:
                if error.code != code:
                    raise AssertionError((label, code, error.code))
                result["rejections"].append(dict(label=label, code=error.code))
            else:
                raise AssertionError("accepted invalid operation: " + label)

        for index, (n, block, alpha) in enumerate(geometries):
            case_dir = args.output / ("case-%02d" % index)
            case_dir.mkdir()
            x = [((i * 0x9e3779b1) ^ 0xffffffff) & 0xffffffff for i in range(capacity)]
            y = [((i * 0x85ebca6b) + 0x80000001) & 0xffffffff for i in range(capacity)]
            z = [0xa5a5a5a5 ^ index] * capacity
            expected = list(z)
            for i in range(offset, offset + n):
                expected[i] = (x[i] if args.kernel == "copy" else
                               x[i] + y[i] if args.kernel == "vadd" else alpha * x[i] + y[i]) & 0xffffffff
            arrays = [x, z] if count == 2 else [x, y, z]
            names = ["x", "z"] if count == 2 else ["x", "y", "z"]
            raw = [pack(a) for a in arrays]
            for name, handle, data in zip(names, buffers, raw):
                (case_dir / (name + ".bin")).write_bytes(data)
                ctx.write(handle, 0, data)
            (case_dir / "expected_z.bin").write_bytes(pack(expected))
            params = [BufferSlice(b, offset * 4, n * 4, "w" if i == count - 1 else "r")
                      for i, b in enumerate(buffers)] + [n]
            if args.kernel == "affine":
                params.append(alpha)
            grid = (max(1, (n + block - 1) // block), 1, 1)
            if index == 0:
                for bad in (33, 64):
                    reject("E_LAUNCH_LIMIT", "block-%d" % bad,
                           lambda bad=bad: ctx.launch(module, module.manifest["entry"], grid, (bad, 1, 1), params))
            event = ctx.launch(module, module.manifest["entry"], grid, (block, 1, 1), params)
            (case_dir / "payload.bin").write_bytes(event.plan.payload)
            if index == 0:
                reject("E_BUSY", "in-flight-free", lambda: ctx.free(buffers[0]))
                reject("E_BUSY", "in-flight-close", ctx.close)
            params[:] = []  # launch must own a copied payload
            completion = ctx.wait(event, 60000)
            observed = [ctx.read(b, 0, capacity * 4) for b in buffers]
            for name, data in zip(names, observed):
                (case_dir / ("observed_" + name + ".bin")).write_bytes(data)
            if observed != raw[:-1] + [pack(expected)]:
                raise AssertionError("array/guard mismatch: " + str(case_dir))
            result["cases"].append(dict(n=n, block=block, grid=grid[0], alpha=alpha,
                offset_bytes=offset*4, status="PASS", completion=completion,
                files={p.name: sha256(p) for p in sorted(case_dir.iterdir())}))
            write(args.output / "result.json", result)
        ctx.close()
        result.update(status="PASS", exit_code=0, passed=len(result["cases"]),
                      u280="PASS" if args.backend == "u280-xrt" else "NOT_RUN")
    except Exception as error:
        result.update(status="FAIL", exit_code=1, error=str(error), traceback=traceback.format_exc())
        # Do not release an uncompleted or unisolated context on error.
        if ctx and ctx.state == "READY":
            ctx.close()
    write(args.output / "result.json", result)
    print(json.dumps({k: result.get(k) for k in ("status", "backend", "kernel", "passed", "error")}))
    return result["exit_code"]

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kernel", choices=("copy", "vadd", "affine"), required=True)
    parser.add_argument("--backend", choices=("simx", "rtlsim", "xrtsim", "u280-xrt"), required=True)
    for name in ("module", "binding", "target-lock", "output"):
        parser.add_argument("--"+name, type=Path, required=True)
    args = parser.parse_args()
    for name in ("module", "binding", "target_lock", "output"):
        setattr(args, name, getattr(args, name).resolve())
    sys.exit(worker(args))
