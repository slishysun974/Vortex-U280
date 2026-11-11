"""Receive a pinned C snapshot against existing A/B simulators, without merging it.

This is an integrator smoke, not E acceptance, a device rebuild or board execution.
The C source and its archived modules remain untouched. Each run is new.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
import traceback

from run_native_smoke import PROJECT, Recorder, sha256, utc_now

C_COMMIT = "7f3575db67888c03d1c2c4dc3743051c735519dd"
BACKENDS = ("simx", "rtlsim", "xrtsim")
KERNELS = ("copy", "vadd", "affine")
LOCK = PROJECT / "configs/candidates/block32-v1/target_lock.json"


def write(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def worker(args):
    sys.path.insert(0, str(args.source / "scripts"))
    from ptx_runtime import Context
    from ptx_module import ModuleError
    from ptx_launch import BufferSlice

    args.output.mkdir(parents=True, exist_ok=False)
    os.chdir(args.output)
    module_path = args.source / "results/c-runtime-suite-20261111/modules" / (args.kernel + "-block32-v1-v1")
    result = dict(status="RUNNING", backend=args.backend, kernel=args.kernel,
                  cases=[], rejections=[], u280="NOT_RUN", independent_E="NOT_RUN",
                  scope="C archived module/runtime on A/B D5 libraries; new integrator execution",
                  module_manifest_sha256=sha256(module_path / "manifest.json"),
                  image_sha256=sha256(module_path / "kernel.vxbin"))
    ctx = None
    try:
        ctx = Context(args.binding, LOCK, backend=args.backend, run_id=args.output.name)
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
        result.update(status="PASS", exit_code=0, passed=len(result["cases"]))
    except Exception as error:
        result.update(status="FAIL", exit_code=1, error=str(error), traceback=traceback.format_exc())
        # Do not release an uncompleted or unisolated context on error.
        if ctx and ctx.state == "READY":
            ctx.close()
    write(args.output / "result.json", result)
    print(json.dumps({k: result.get(k) for k in ("status", "backend", "kernel", "passed", "error")}))
    return result["exit_code"]


def receive(args):
    args.output.mkdir(parents=True, exist_ok=False)
    summary = dict(status="RUNNING", started_at=utc_now(), commands=[],
                   c_repository="https://github.com/LiuZeheng123/GPGPU-runtime",
                   c_commit=C_COMMIT, scope="isolated C/A/B compatibility receipt",
                   board_execution="NOT_RUN", device_rebuild="NOT_RUN", independent_E="NOT_RUN")
    summary["host_and_archive_checks"] = "NOT_RUN" if args.execution_only else "RUNNING"
    env = os.environ.copy()
    env.update(PYTHONDONTWRITEBYTECODE="1", VORTEX_PROFILING="0")
    env.pop("XCLBIN_PATH", None)
    env.pop("XCL_EMULATION_MODE", None)
    recorder = Recorder(args.output, summary, env)

    def command(label, argv, cwd=PROJECT, timeout=240):
        item, output = recorder.command(label, argv, cwd, timeout=timeout)
        if item["returncode"] != 0 or item["timed_out"]:
            raise RuntimeError("failed: " + label)
        return output

    try:
        commit = command("c_commit", ["git", "-C", args.source, "rev-parse", "HEAD"]).strip()
        if commit != C_COMMIT:
            raise ValueError("C snapshot differs from reviewed commit")
        if command("c_clean_before", ["git", "-C", args.source, "status", "--porcelain"]).strip():
            raise ValueError("C snapshot is modified")
        identical = ("configs/target_lock.json", "configs/target_caps.json",
            "configs/candidates/block32-v1/target_lock.json", "configs/candidates/block32-v1/target_caps.json",
            "configs/candidates/block32-v1/native_smoke.json", "configs/candidates/u280-hbm32-v1/target_lock.json",
            "configs/candidates/u280-hbm32-v1/fpga.json", "configs/ptx_frontend/v1/abi.json",
            "configs/ptx_frontend/v1/profile.json", "ptx/samples/copy_u32.ptx",
            "ptx/samples/vadd_u32.ptx", "ptx/samples/affine_u32.ptx")
        summary["contract_identity"] = {}
        for relative in identical:
            left, right = sha256(PROJECT / relative), sha256(args.source / relative)
            summary["contract_identity"][relative] = dict(ab=left, c=right, match=left == right)
            if left != right:
                raise ValueError("contract mismatch: " + relative)
        inventory = []
        for group in ("scripts", "tests", "configs", "native", "ptx"):
            for path in sorted((args.source / group).rglob("*")):
                if not path.is_file() or "__pycache__" in path.parts:
                    continue
                rel = path.relative_to(args.source)
                local = PROJECT / rel
                c_hash, ab_hash = sha256(path), sha256(local) if local.is_file() else None
                inventory.append(dict(path=rel.as_posix(), c=c_hash, ab=ab_hash,
                    classification="C_ONLY" if ab_hash is None else "IDENTICAL" if ab_hash == c_hash else "DIFFERENT"))
        write(args.output / "file_comparison.json", inventory)
        summary["file_comparison"] = {key: sum(x["classification"] == key for x in inventory)
                                      for key in ("C_ONLY", "IDENTICAL", "DIFFERENT")}
        (args.output / "check_c_ab_integration.py").write_bytes(Path(__file__).read_bytes())
        summary["runner_sha256"] = sha256(Path(__file__))
        # C's own archive checker is useful corroboration, not independent execution.
        # Sequential decompression avoids thousands of repeated gzip seeks on
        # /mnt/d. The unchanged checker validates every extracted byte/hash.
        summary["archive_inputs"] = {}
        with tempfile.TemporaryDirectory(prefix="c-ab-receive-") as scratch:
            for kernel in (() if args.execution_only else KERNELS):
                roots = []
                for backend in BACKENDS:
                    original = args.source / "results/c-runtime-rtl-20261111" / ("c-" + kernel + "-" + backend + "-v1")
                    staged = Path(scratch) / original.name
                    staged.mkdir()
                    shutil.copyfile(original / "result.json", staged / "result.json")
                    inputs = {"result.json": sha256(original / "result.json")}
                    for archive in sorted(original.glob("cases-*.tgz")):
                        inputs[archive.name] = sha256(archive)
                        with tarfile.open(archive, "r|gz") as bundle:
                            for member in bundle:
                                if not member.isfile() or not re.fullmatch(r"cases/[0-9]{4}/[a-z_]+\.bin", member.name):
                                    raise ValueError("unexpected capture archive member: " + member.name)
                                path = staged / member.name
                                path.parent.mkdir(parents=True, exist_ok=True)
                                with path.open("xb") as stream:
                                    shutil.copyfileobj(bundle.extractfile(member), stream)
                    summary["archive_inputs"][original.name] = inputs
                    roots.append(staged)
                recorder.save()
                command("c_archive_" + kernel, [sys.executable, "-B", args.source / "scripts/compare_ptx_backends.py", *roots])
        test_env_source = "/opt/vortex-ab/sources/vortex-7fe19369587c-v1"
        env["VORTEX_SOURCE"] = test_env_source
        if not args.execution_only:
            command("c_python_tests", [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-v"], args.source)
            # The A/B suite is run independently; C's frontend is not installed over it.
            command("ab_python_tests", [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-v"], PROJECT)
            summary["host_and_archive_checks"] = "PASS"
        summary["runs"] = []
        for backend in BACKENDS:
            native = PROJECT / "results" / ("ab-d5-block32-20261108-v1-" + backend) / "summary.json"
            binding_dir = args.output / ("binding-" + backend)
            # ldd in the binder must also resolve this backend's dependencies,
            # before a binding exists. Never inherit the previous backend path.
            native_summary = json.loads(native.read_text())
            env["VORTEX_DRIVER"] = "xrt" if backend == "xrtsim" else backend
            env["LD_LIBRARY_PATH"] = str(Path(native_summary["build_path"]) / "sw/runtime")
            command("bind_" + backend, [sys.executable, "-B", args.source / "scripts/bind_simx_runtime.py",
                "--summary", native, "--target-lock", LOCK, "--hardware", LOCK.with_name("native_smoke.json"),
                "--output", binding_dir])
            binding = json.loads((binding_dir / "binding.json").read_text())
            env["VORTEX_DRIVER"] = "xrt" if backend == "xrtsim" else backend
            env["LD_LIBRARY_PATH"] = binding["library_dir"]
            for kernel in KERNELS:
                destination = args.output / (backend + "-" + kernel)
                command(backend + "_" + kernel, [sys.executable, "-B", Path(__file__).resolve(),
                    "--source", args.source, "--output", destination, "--worker", "--backend", backend,
                    "--kernel", kernel, "--binding", binding_dir / "binding.json"], timeout=240)
                result = json.loads((destination / "result.json").read_text())
                if result["status"] != "PASS":
                    raise AssertionError("worker result is not PASS")
                summary["runs"].append(dict(backend=backend, kernel=kernel, passed=result["passed"],
                    rejections=len(result["rejections"]), result=str(destination.relative_to(args.output) / "result.json"),
                    result_sha256=sha256(destination / "result.json")))
        # Device addresses may vary; compare full arrays and input geometry across backends.
        for kernel in KERNELS:
            runs = [json.loads((args.output / (b + "-" + kernel) / "result.json").read_text()) for b in BACKENDS]
            if len({r["image_sha256"] for r in runs}) != 1:
                raise AssertionError("cross-backend image mismatch")
            captures = [[{k: v for k, v in case["files"].items() if k != "payload.bin"}
                         for case in r["cases"]] for r in runs]
            if any(c != captures[0] for c in captures[1:]):
                raise AssertionError("cross-backend input/output mismatch")
        if command("c_clean_after", ["git", "-C", args.source, "status", "--porcelain"]).strip():
            raise ValueError("C snapshot changed during receipt")
        for rel, item in summary["contract_identity"].items():
            if sha256(PROJECT / rel) != item["ab"]:
                raise AssertionError("A/B contract changed during receipt")
        summary.update(status="PASS", exit_code=0, cross_backend_arrays="PASS",
                       new_executions=sum(r["passed"] for r in summary["runs"]))
    except Exception as error:
        summary.update(status="FAIL", exit_code=1, error=str(error), traceback=traceback.format_exc())
    summary["finished_at"] = utc_now()
    recorder.save()
    print(json.dumps({k: summary.get(k) for k in ("status", "exit_code", "new_executions", "error")}), flush=True)
    return summary["exit_code"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--execution-only", action="store_true",
                        help="skip archive/unit checks and label them NOT_RUN in this receipt")
    parser.add_argument("--backend", choices=BACKENDS)
    parser.add_argument("--kernel", choices=KERNELS)
    parser.add_argument("--binding", type=Path)
    args = parser.parse_args()
    args.source, args.output = args.source.resolve(), args.output.resolve()
    if args.binding:
        args.binding = args.binding.resolve()
    return worker(args) if args.worker else receive(args)


if __name__ == "__main__":
    sys.exit(main())
