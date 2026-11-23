"""Build an isolated LSU-tracing variant of the fixed NOXRT AFU simulator."""

import argparse
from pathlib import Path
import shutil
import sys

from afu_contract import (BACKEND, FIXED_BINDING, PROJECT, SIM_LOCK, TOOLCHAIN, VORTEX, Recorder, check_binding,
                          clean_env, driver_env, require, run_stage, sha256, source_audit, utc_now)
from bind_simx_runtime import bind
from run_native_smoke import demo_passed
from ptx_module import write_json


def build(out, rec, jobs):
    binding, native = check_binding(FIXED_BINDING, fixed=True)
    source_audit(rec, out)
    lock = SIM_LOCK.with_name("native_smoke.json")
    origin = Path(native["build_path"])
    libraries = origin / "sw/runtime"
    third_party = origin / "third_party"
    root = PROJECT / "build" / out.name
    root.mkdir()
    destination = root / "sw/runtime"
    rec.summary.update(build_path=str(root), backend=BACKEND, check_only=False,
                       source=native["source"], config_file_sha256=native["config_file_sha256"],
                       effective_backend_configuration=native["effective_backend_configuration"],
                       fixed_binding_sha256=sha256(FIXED_BINDING), debug_level=2)
    tools = {name: sha256(TOOLCHAIN / name) for name in ("verilator/bin/verilator", "verilator/bin/verilator_bin")}
    require(all(value == native["toolchain_file_sha256"][name] for name, value in tools.items()), "pinned Verilator differs")
    ramulator = third_party / "ramulator/libramulator.so"
    require(binding["dependencies"][str(ramulator)] == sha256(ramulator), "fixed Ramulator library differs")
    rec.summary["read_only_dependencies"] = {str(path): sha256(path) for path in (
        ramulator, third_party / "softfloat/build/Linux-x86_64-GCC/softfloat.a")}
    rec.summary["tool_sha256"] = tools
    rec.env.update(CONFIGS=native["configs"], CCACHE_DISABLE="1")
    run_stage(rec, "configure", ["bash", VORTEX / "configure", "--xlen=64", "--tooldir=" + str(TOOLCHAIN)], root, 120)
    for name in ("sw/VX_config.h", "hw/VX_config.vh"):
        require(sha256(root / name) == native["build_artifacts"][name]["sha256"], "generated hardware config differs: " + name)
    destination.mkdir(exist_ok=True)
    for name in (*binding["libraries"], "xrt_config.stamp"):
        if name == "libxrtsim.so":
            continue
        require(sha256(libraries / name) == native["build_artifacts"]["sw/runtime/" + name]["sha256"], "fixed runtime file differs")
        shutil.copyfile(libraries / name, destination / name)
    run_stage(rec, "build_trace_afu", ["make", f"-j{jobs}", "-C", root / "sim/xrtsim", "XLEN=64",
              "CONFIGS=" + native["configs"], "THREADS=" + str(jobs), "THIRD_PARTY_DIR=" + str(third_party),
              "DEBUG=2", "DBG_TRACE_FLAGS=-DDBG_TRACE_PIPELINE -DDBG_TRACE_MEM", "DESTDIR=" + str(destination),
              destination / "libxrtsim.so"], root, 900)
    stamps = (destination / "xrtsim_config.stamp").read_text().split()
    require({"-DNOXRT", "-DSV_DPI", "-DSIMULATION", "-DVX_DBG_DEBUG_LEVEL=2", "-DDBG_TRACE_PIPELINE", "-DDBG_TRACE_MEM"}
            <= set(stamps), "trace model does not have required compile flags")
    driver_env(rec, {"library_dir": str(destination)})
    demo = origin / "tests/regression/demo"
    files = {"tests/regression/demo/" + name: demo / name for name in ("demo", "kernel.vxbin")}
    require(all(sha256(path) == native["build_artifacts"][name]["sha256"] for name, path in files.items()), "fixed demo differs")
    # The demo is a native control for the instrumented simulator only.
    command, output = rec.command("demo_run", [demo / "demo", "-n1", "-k", demo / "kernel.vxbin"], out, 120)
    require(demo_passed(command["returncode"], command["timed_out"], output), "AFU debug native demo failed")
    require(" Rd Req:" in output and " cta-fire:" in output and " kmu-accept:" in output,
            "AFU debug demo lacks pre-cache lane and CTA trace records")
    files.update({"sw/runtime/" + name: destination / name for name in
                  (*binding["libraries"], "xrt_config.stamp", "xrtsim_config.stamp")})
    rec.summary["build_artifacts"] = {name: dict(path=str(path), sha256=sha256(path)) for name, path in files.items()}
    rec.summary.update(status="PASS", exit_code=0, demo_execution="PASS")
    rec.save()
    # Keep the native report separate from its consumer's receipt so the
    # bound summary remains byte-identical after the debug binding is made.
    native_report = out / "native.json"
    shutil.copyfile(out / "summary.json", native_report)
    bound = bind(native_report, SIM_LOCK, lock, out / "binding")
    require(str(ramulator) in (out / "binding/ldd.log").read_text(), "debug simulator did not link fixed Ramulator")
    bound["dependencies"][str(ramulator)] = sha256(ramulator)
    write_json(out / "binding/binding.json", bound)
    rec.summary["binding_sha256"] = sha256(out / "binding/binding.json")


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--jobs", type=int, default=4)
    cli.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()
    out = args.output.resolve()
    require(out.parent == PROJECT / "results" and out.name.startswith("local-ptx-same-predicate-afu-trace-build-")
            and args.jobs > 0, "choose a fresh trace build run and positive jobs")
    out.mkdir()
    report = dict(status="RUNNING", commands=[], started_at=utc_now(), argv=[sys.executable, "-B", *sys.argv],
                  board_execution="NOT_RUN")
    rec = Recorder(out, report, clean_env())
    try:
        build(out, rec, args.jobs)
    except Exception as error:
        report.update(status="FAIL", exit_code=1, error=str(error))
    report["finished_at"] = utc_now()
    rec.save()
    print(report["status"], out, report.get("error", ""))
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
