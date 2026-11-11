"""Build the frozen P0 vadd/affine samples and check SimX/RTL LSU traces."""
import argparse
import os
import re
import shutil
import struct

from run_native_smoke import Recorder, sha256, utc_now
from run_ptx_copy import (BUILDS, FRONTEND_RUN, PROJECT, SIM_LOCK, VORTEX, capture_comparison,
                          read_json, require, run_stage, stage_case, vxbin_entry, write_json)
from run_ptx_copy_trace import IMAGE_RUN, TRACE_RUNS, analyze_trace, trace_libraries


CASES = {"vadd_u32": ("0010", "0058", "0070", "0106"),
         "affine_u32": ("0034", "0176", "0210", "0250", "0322")}


def instruction_sites(dump, entry, n_offset):
    functions = re.split(r"(?m)^\s*[0-9a-f]+ <([^>]+)>:\s*$", dump)
    body = dict(zip(functions[1::2], functions[2::2]))[entry].split("Disassembly of section", 1)[0]
    instructions = [(int(pc, 16), op, operands) for pc, op, operands in
                    re.findall(r"(?m)^\s*([0-9a-f]+):\s+[0-9a-f]+[ \t]+([a-z0-9._]+)[ \t]+(.*)$", body)]
    loads = [pc for pc, op, _ in instructions if op in ("lw", "lwu")]
    stores = [pc for pc, op, _ in instructions if op == "sw"]
    params = [pc for pc, op, operands in instructions if op == "lbu" and
              re.search(r",\s*0x{:x}\([a-z0-9]+\)$".format(n_offset), operands)]
    require(len(loads) == 2 and len(stores) == 1 and len(params) == 1,
            "unexpected load/store or n parameter instructions for " + entry)
    # The generated body sequences the volatile x load before the y load.
    return dict(x=(loads[0], "LD"), y=(loads[1], "LD"), z=(stores[0], "ST")), params[0]


def build_module(run, recorder, entry):
    module = run / entry
    module.mkdir()
    src = PROJECT / "native/ptx_copy"
    for name in ("kernel.cpp", "main.cpp", "Makefile"):
        shutil.copy2(src / name, module)
    run_stage(recorder, entry + "_frontend", ["python3", "-B", PROJECT / "scripts/ptx_frontend.py",
              PROJECT / "ptx/samples" / (entry + ".ptx"), "--target-lock", SIM_LOCK,
              "--output", module / "frontend"], run)
    frontend = read_json(module / "frontend/manifest.json")
    frozen = read_json(FRONTEND_RUN / entry / "module/manifest.json")
    for name in ("source.ptx", "kernel_body.hpp"):
        require(sha256(module / "frontend" / name) == frontend["files"][name] == frozen["files"][name],
                "frontend artifact differs from frozen " + name)
    shutil.copy2(module / "frontend/kernel_body.hpp", module)
    sim_build = BUILDS / "ab-d5-block32-20261108-v1-simx"
    config = read_json(SIM_LOCK.with_name("native_smoke.json"))
    defines = " ".join("-D{}={}".format(name, value) for name, value in config["defines"].items())
    run_stage(recorder, entry + "_device_build", ["make", "ROOT_DIR=" + str(sim_build), "CONFIGS=" + defines,
              "PTX_ENTRY=" + entry, "kernel.vxbin", "kernel.dump"], module, timeout=180)
    ir = read_json(module / "frontend/ir.json")
    require(ir["entry"] == entry, "unexpected frontend entry")
    n_offset = next(p["offset"] for p in ir["params"] if p["name"] == "n")
    sites, param_pc = instruction_sites((module / "kernel.dump").read_text(), entry, n_offset)
    entry_pc = vxbin_entry(module / "kernel.vxbin", entry)
    artifacts = ("kernel.cpp", "main.cpp", "Makefile", "kernel_body.hpp", "kernel.vxbin", "kernel.elf", "kernel.dump")
    manifest = dict(schema_version="ptx-vx-arithmetic-sim-package-v1", entry=entry, runtime_entry_pc=entry_pc,
                    target_lock_sha256=sha256(SIM_LOCK), profile=frontend["profile"], abi_version=frontend["abi_version"],
                    params=ir["params"], params_size=ir["params_size"], files={name: sha256(module / name) for name in artifacts},
                    array_sites={name: dict(pc=hex(pc), op=op) for name, (pc, op) in sites.items()}, n_read_pc=hex(param_pc))
    write_json(module / "manifest.json", manifest)
    return ir, manifest, sites, param_pc


def validate(run, recorder):
    summary = recorder.summary
    lock = read_json(SIM_LOCK)
    require(run_stage(recorder, "source_commit", ["git", "-C", VORTEX, "rev-parse", "HEAD"], run).strip() ==
            lock["vortex"]["commit"], "fixed Vortex commit mismatch")
    sim_build = BUILDS / "ab-d5-block32-20261108-v1-simx"
    summary["kernel_lib_sha256"] = sha256(sim_build / "sw/kernel/libvortex2.a")
    require(summary["kernel_lib_sha256"] == read_json(IMAGE_RUN / "module/manifest.json")["kernel_lib_sha256"] and
            sha256(sim_build / "tests/regression/common.mk") == sha256(PROJECT / "upstream/vortex/tests/regression/common.mk"),
            "fixed device link library or build rule mismatch")
    libraries = {backend: trace_libraries(backend) for backend in TRACE_RUNS}
    summary["debug_artifact_sha256"] = {backend: hashes for backend, (_, hashes) in libraries.items()}
    for entry, case_ids in CASES.items():
        ir, manifest, sites, param_pc = build_module(run, recorder, entry)
        module = run / entry
        kernel = dict(device_build="PASS", image_sha256=manifest["files"]["kernel.vxbin"],
                      manifest=entry + "/manifest.json", backends={})
        summary["kernels"][entry] = kernel
        for case_id in case_ids:
            case_dir = module / case_id
            case_dir.mkdir()
            case, corpus_sha = stage_case(case_dir, ir, case_id)
            kernel["corpus_sha256"] = corpus_sha
            require(case["block"] == 32, "unexpected block size in frozen case")
            shutil.copy2(module / "main.cpp", case_dir)
            for backend, (lib, _) in libraries.items():
                stage = case_dir / backend
                actual = stage / "actual"
                actual.mkdir(parents=True)
                host = stage / "ptx_sample"
                label = "_".join((entry, case_id, backend))
                run_stage(recorder, label + "_compile", ["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-O2",
                          "-I" + str(VORTEX / "sw/runtime/include"), case_dir / "main.cpp", "-L" + str(lib),
                          "-lvortex", "-o", host], stage)
                stdout = run_stage(recorder, label + "_run", ["env", "VORTEX_DRIVER=" + backend, "LD_LIBRARY_PATH=" + str(lib),
                                   "VORTEX_PROFILING=0", host, case_dir / "inputs", actual], module, timeout=120)
                require("CAPTURE_COMPLETE 1" in stdout.splitlines() and
                        "CAPTURED {id} n={n} block={block} grid={grid}".format(**case) in stdout.splitlines(),
                        "missing capture completion for " + label)
                comparison = capture_comparison(case_dir, actual, stdout, case, ir, manifest["runtime_entry_pc"])
                trace = analyze_trace(stdout, backend, case, comparison["device_addresses"], sites, param_pc)
                write_json(stage / "comparison.json", comparison)
                write_json(stage / "trace.json", trace)
                status = "PASS" if comparison["status"] == trace["status"] == "PASS" else "FAIL"
                kernel["backends"].setdefault(backend, []).append(dict(case=case, status=status,
                    loads=trace["observed_loads"], stores=trace["observed_stores"], evidence=str(stage.relative_to(run))))
                recorder.save()
    require(all(case["status"] == "PASS" for kernel in summary["kernels"].values()
                for records in kernel["backends"].values() for case in records), "PTX arithmetic capture/trace mismatch")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"ptx-arithmetic-[A-Za-z0-9_.-]{1,64}", args.run_id):
        parser.error("invalid arithmetic run id")
    run = PROJECT / "results" / args.run_id
    run.mkdir()
    summary = dict(schema_version="ptx-vx-arithmetic-sim-v1", run_id=args.run_id, status="FAIL",
                   kernels={}, commands=[], u280="NOT_RUN", independent_acceptance="NOT_RUN", started_at=utc_now())
    recorder = Recorder(run, summary, dict(os.environ))
    try:
        for name in ("run_ptx_arithmetic.py", "run_ptx_copy.py", "run_ptx_copy_trace.py", "native_predicate_trace.py"):
            shutil.copy2(PROJECT / "scripts" / name, run)
        validate(run, recorder)
        summary["status"] = "PASS"
    except (RuntimeError, OSError, ValueError, KeyError, struct.error) as exc:
        summary["error"] = str(exc)
    finally:
        summary["finished_at"] = utc_now()
        recorder.save()
    print(summary["status"], run, summary.get("error", ""))
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
