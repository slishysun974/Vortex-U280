"""Compile bound host libraries in a fresh directory; never open a device."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shlex
import shutil
import signal
import subprocess
import sys
import time


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate(source):
    names = set()
    for item in json.loads((source / "manifest.json").read_text()):
        name = item["path"]
        path = PurePosixPath(name)
        if (path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name or
                name in names or path.as_posix() != name):
            raise ValueError("unsafe/duplicate input path")
        names.add(name)
        target = source / name
        current = target
        while current != source:
            if current.is_symlink():
                raise ValueError("symlink input")
            current = current.parent
        if target.stat().st_size != item["bytes"] or sha(target) != item["sha256"]:
            raise ValueError("input hash mismatch: " + name)
    actual = {p.relative_to(source).as_posix() for p in source.rglob("*") if p.is_file()}
    if actual != names | {"manifest.json"}:
        raise ValueError("input inventory mismatch")
    binding = json.loads((source / "binding.json").read_text())
    for name, key in (("target_lock.json", "target_lock_sha256"),
                      ("fpga_build_result.json", "fpga_build_result_sha256"),
                      ("resolved.cflags", "resolved_cflags_sha256")):
        if sha(source / name) != binding[key]:
            raise ValueError("binding mismatch: " + name)
    flags = (source / "resolved.cflags").read_text().strip()
    if "-DVX_CFG_PLATFORM_CLOCK_RATE=200" not in shlex.split(flags):
        raise ValueError("200 MHz binding required")
    return binding, flags


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cxx", required=True)
    parser.add_argument("--stub-only", action="store_true", help="preparation check only, not XRT or server acceptance")
    args = parser.parse_args()
    source = args.input.resolve()
    binding, flags = validate(source)
    output = args.output.absolute()
    if output == source or source in output.parents:
        raise ValueError("output must not modify input package")
    output.mkdir(parents=True, exist_ok=False)
    shutil.copytree(source / "build", output / "build")
    result = dict(schema_version="u280-host-runtime-build-v1", status="RUNNING", argv=sys.argv,
        scope="host shared-library compilation and dependency inspection only", commands=[],
        board_load="NOT_RUN", board_execution="NOT_RUN", host_configuration="NOT_RUN", binding=binding,
        stub_only=args.stub_only, cpu_affinity=sorted(os.sched_getaffinity(0))[:2])

    def command(label, argv, timeout=300):
        start = time.monotonic()
        rec = dict(label=label, argv=argv, cwd=str(output), timed_out=False)
        def limits():
            os.sched_setaffinity(0, result["cpu_affinity"])
            os.nice(10)
        with (output / (label + ".stdout")).open("xb") as out, (output / (label + ".stderr")).open("xb") as err:
            p = subprocess.Popen(argv, cwd=str(output), stdout=out, stderr=err, preexec_fn=limits,
                start_new_session=True, env=dict(os.environ, XILINX_XRT="/opt/xilinx/xrt", CCACHE_DISABLE="1"))
            try:
                p.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                rec["timed_out"] = True
                os.killpg(p.pid, signal.SIGKILL)
                p.wait()
        rec.update(exit_code=p.returncode, elapsed_seconds=round(time.monotonic() - start, 3))
        result["commands"].append(rec)
        if p.returncode or rec["timed_out"]:
            raise ValueError(label + " failed")

    try:
        command("compiler", [args.cxx, "--version"])
        command("glibc", ["getconf", "GNU_LIBC_VERSION"])
        common = ["-j2", "VORTEX_HOME=" + str(source / "source"), "XLEN=64", "XCONFIGS=" + flags,
                  "CONFIGS=", "CXX=" + args.cxx, "TARGET=hw", "DESTDIR=" + str(output / "lib")]
        for backend in (("stub",) if args.stub_only else ("stub", "xrt")):
            command(backend, ["make", "-C", str(output / "build/sw/runtime" / backend)] + common)
        result["artifacts"] = []
        for lib in sorted((output / "lib").glob("*.so")):
            command("ldd_" + lib.stem, ["ldd", str(lib)])
            if "not found" in (output / ("ldd_" + lib.stem + ".stdout")).read_text():
                raise ValueError("unresolved runtime dependency")
            result["artifacts"].append(dict(path=str(lib.relative_to(output)), sha256=sha(lib), bytes=lib.stat().st_size))
        validate(source)
        result.update(status="PASS", xrt_backend="NOT_RUN" if args.stub_only else "PASS")
    except Exception as exc:
        result.update(status="FAIL", error=repr(exc))
    result["exit_code"] = 0 if result["status"] == "PASS" else 1
    (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(dict(status=result["status"], error=result.get("error"))))
    return result["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
