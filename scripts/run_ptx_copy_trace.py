"""Replay the verified PTX copy image with frozen B=32 cases and LSU tracing."""
import argparse
from collections import Counter
import os
from pathlib import Path
import re
import shutil

from native_predicate_trace import parse_request
from run_native_smoke import Recorder, sha256, utc_now
from run_ptx_copy import (PROJECT, SIM_LOCK, VORTEX, capture_comparison, read_json,
                          require, run_stage, stage_case, vxbin_entry, write_json)


IMAGE_RUN = PROJECT / "results/ptx-copy-20261110-v2"
TRACE_RUNS = {"simx": "ab-d6-trace-simx-20261108-v2", "rtlsim": "ab-d6-trace-rtlsim-20261108-v1"}
CASE_IDS = ("0010", "0058", "0070", "0082", "0094", "0106")
# Reviewed against kernel.dump and applicable only to this exact image.
IMAGE_SHA = "78fdf5306a53d78e81420a85b26d913adc52333b9f5e580441b9c9abd0fb25c0"
LOAD_PC, STORE_PC, PARAM_PC = 0x180000140, 0x180000154, 0x18000008C
SIMX_CTA = re.compile(r"dispatch CTA warp: .*cta_id=(\d+),.*blockIdx=\((\d+),0\)")
RTL_CTA = re.compile(r"\bkmu cta-fire: cta_id=(\d+), block_idx=\[(\d+),0,0\]")
SIMX_DECODE = re.compile(r"pipeline decode: .*cta_id=(\d+),.*PC=0x([0-9a-fA-F]+),.*ex=LSU.* \(#(\d+)\)$")
RTL_CONTEXT = re.compile(r"cta_id=(\d+), PC=0x([0-9a-fA-F]+),")


def trace_rows(accesses):
    return [dict(cta_id=cta, pc=hex(pc), op=op, address=hex(address), count=count)
            for (cta, pc, op, address), count in sorted(accesses.items())]


def analyze_trace(stdout, backend, case, addresses, sites=None, param_pc=PARAM_PC):
    """Count active LSU lanes at copy PCs and catch other accesses to either buffer."""
    if sites is None:
        sites = {"x": (LOAD_PC, "LD"), "z": (STORE_PC, "ST")}
    array_pcs = {pc for pc, _ in sites.values()}
    cta_pattern = SIMX_CTA if backend == "simx" else RTL_CTA
    blocks = {}
    decoded = {}
    array_accesses, parameter_lanes = Counter(), Counter()
    requests = 0
    ranges = sorted((ptr - 32, ptr - 32 + case["words"] * 4) for ptr in addresses.values())
    require(all(left[1] <= right[0] for left, right in zip(ranges, ranges[1:])), "overlapping buffers")

    for line in stdout.splitlines():
        if match := cta_pattern.search(line):
            cta, block = map(int, match.groups())
            require(blocks.setdefault(cta, block) == block, "reused CTA ID in copy trace")
        if backend == "simx" and (match := SIMX_DECODE.search(line)):
            cta, pc, uuid = match.groups()
            decoded[uuid] = (int(cta), int(pc, 16))
        lanes = parse_request(line, backend)
        if lanes is None:
            continue
        requests += 1
        if backend == "simx":
            match = re.search(r" \(#(\d+)\)$", line)
            require(match and match[1] in decoded, "SimX LSU request has no matching decoded instruction")
            cta, pc = decoded[match[1]]
        else:
            match = RTL_CONTEXT.search(line)
            require(match, "RTL LSU request lacks CTA or PC")
            cta, pc = int(match[1]), int(match[2], 16)
        require(cta in blocks, "LSU request has no dispatched block")
        for op, address in lanes:
            if pc == param_pc and op == "LD":
                parameter_lanes[cta] += 1
            if pc in array_pcs or any(start <= address < end for start, end in ranges):
                array_accesses[(cta, pc, op, address)] += 1

    expected = Counter()
    for cta, block in blocks.items():
        for i in range(block * case["block"], min((block + 1) * case["block"], case["n"])):
            for name, (pc, op) in sites.items():
                expected[(cta, pc, op, addresses[name] + 4 * i)] = 1
    missing, unexpected = expected - array_accesses, array_accesses - expected
    geometry_ok = sorted(blocks.values()) == list(range(case["grid"])) and all(
        parameter_lanes[cta] == case["block"] for cta in blocks)
    return dict(status="PASS" if requests and geometry_ok and not (missing or unexpected) else "FAIL",
                cta_blocks=blocks, parameter_lanes=parameter_lanes, geometry_match=geometry_ok,
                lsu_requests=requests, expected_loads=case["expected_loads"],
                expected_stores=case["expected_stores"],
                observed_loads=sum(n for (_, _, op, _), n in array_accesses.items() if op == "LD"),
                observed_stores=sum(n for (_, _, op, _), n in array_accesses.items() if op == "ST"),
                array_accesses=trace_rows(array_accesses), missing=trace_rows(missing),
                unexpected=trace_rows(unexpected))


def trace_libraries(backend):
    parent = PROJECT / "results" / TRACE_RUNS[backend]
    evidence = read_json(parent / "summary.json")
    require(evidence["status"] == "PASS" and evidence["debug_level"] == 3 and
            evidence["backend"] == backend and evidence["config_file_sha256"]["target_lock.json"] == sha256(SIM_LOCK),
            "incompatible D6 trace build: " + backend)
    build = Path(evidence["build_path"])
    lib = build / "sw/runtime"
    paths = ["config.mk", "sw/VX_config.h", "hw/VX_config.vh"]
    paths += ["sw/runtime/" + name for name in ("libvortex.so", "libvortex-" + backend + ".so", "lib" + backend + ".so")]
    hashes = {name: sha256(build / name) for name in paths}
    require(all(digest == evidence["build_artifacts"][name]["sha256"] for name, digest in hashes.items()),
            "D6 simulator/runtime artifact mismatch: " + backend)
    return lib, hashes


def validate(run, recorder):
    summary = recorder.summary
    module = run / "module"
    module.mkdir()
    origin = IMAGE_RUN / "module"
    manifest = read_json(origin / "manifest.json")
    frontend = read_json(origin / "frontend/manifest.json")
    require(read_json(IMAGE_RUN / "summary.json")["status"] == "PASS" and
            manifest["target_lock_hash"] == sha256(SIM_LOCK) and manifest["image_sha256"] == IMAGE_SHA and
            manifest["source_sha256"] == sha256(PROJECT / "ptx/samples/copy_u32.ptx"), "copy image identity mismatch")
    for name in ("kernel.vxbin", "kernel.dump", "main.cpp", "frontend/ir.json"):
        digest = frontend["files"]["ir.json"] if name == "frontend/ir.json" else manifest["files"][name]
        require(sha256(origin / name) == digest, "copy artifact mismatch: " + name)
        path = module / name
        path.parent.mkdir(exist_ok=True)
        shutil.copy2(origin / name, path)
    require(sha256(module / "kernel.vxbin") == IMAGE_SHA, "unexpected copy image")
    entry_pc = vxbin_entry(module / "kernel.vxbin")
    require(entry_pc == manifest["runtime_entry_pc"], "unexpected packaged entry PC")
    ir = read_json(module / "frontend/ir.json")
    require(ir["params"] == manifest["params"] and ir["params_size"] == manifest["params_size"], "ABI mismatch")
    summary.update(image_sha256=IMAGE_SHA, runtime_entry_pc=entry_pc, target_lock_sha256=sha256(SIM_LOCK),
                   image_origin=IMAGE_RUN.name, copy_pcs=dict(load=hex(LOAD_PC), store=hex(STORE_PC),
                                                             parameter_read=hex(PARAM_PC)))
    require(run_stage(recorder, "source_commit", ["git", "-C", VORTEX, "rev-parse", "HEAD"], run).strip() ==
            read_json(SIM_LOCK)["vortex"]["commit"], "fixed Vortex commit mismatch")
    for case_id in CASE_IDS:
        case_dir = run / case_id
        case_dir.mkdir()
        case, corpus_sha = stage_case(case_dir, ir, case_id)
        require(case["block"] == 32 and corpus_sha == manifest["corpus_sha256"], "unexpected frozen case")
        summary["cases"].append(case)
        shutil.copy2(module / "main.cpp", case_dir / "main.cpp")

    for backend in TRACE_RUNS:
        lib, hashes = trace_libraries(backend)
        result = dict(status="FAIL", debug_build=TRACE_RUNS[backend], debug_artifact_sha256=hashes, cases=[])
        summary["backends"][backend] = result
        for case in summary["cases"]:
            case_id = case["id"]
            case_dir = run / case_id
            stage = case_dir / backend
            actual = stage / "actual"
            actual.mkdir(parents=True)
            host = stage / "ptx_copy"
            label = backend + "_" + case_id
            run_stage(recorder, label + "_compile", ["g++", "-std=c++17", "-Wall", "-Wextra",
                      "-Werror", "-O2", "-I" + str(VORTEX / "sw/runtime/include"),
                      case_dir / "main.cpp", "-L" + str(lib), "-lvortex", "-o", host], stage)
            stdout = run_stage(recorder, label + "_run", ["env", "VORTEX_DRIVER=" + backend,
                               "LD_LIBRARY_PATH=" + str(lib), "VORTEX_PROFILING=0", host,
                               case_dir / "inputs", actual], module, timeout=120)
            require("CAPTURE_COMPLETE 1" in stdout.splitlines() and
                    "CAPTURED {id} n={n} block={block} grid={grid}".format(**case) in stdout.splitlines(),
                    "missing capture completion for " + label)
            comparison = capture_comparison(case_dir, actual, stdout, case, ir, entry_pc)
            write_json(stage / "comparison.json", comparison)
            trace = analyze_trace(stdout, backend, case, comparison["device_addresses"])
            write_json(stage / "trace.json", trace)
            passed = comparison["status"] == trace["status"] == "PASS"
            result["cases"].append(dict(id=case_id, status="PASS" if passed else "FAIL",
                                        comparison=str((stage / "comparison.json").relative_to(run)),
                                        trace=str((stage / "trace.json").relative_to(run)),
                                        observed_loads=trace["observed_loads"], observed_stores=trace["observed_stores"]))
            recorder.save()
        result["status"] = "PASS" if all(case["status"] == "PASS" for case in result["cases"]) else "FAIL"
        recorder.save()
    require(all(summary["backends"][name]["status"] == "PASS" for name in TRACE_RUNS), "copy capture/trace mismatch")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"ptx-copy-trace-[A-Za-z0-9_.-]{1,64}", args.run_id):
        parser.error("invalid trace run id")
    run = PROJECT / "results" / args.run_id
    run.mkdir()
    summary = dict(schema_version="ptx-vx-copy-trace-v1", run_id=args.run_id, status="FAIL",
                   cases=[], backends={name: {"status": "NOT_RUN"} for name in (*TRACE_RUNS, "u280")},
                   independent_acceptance="NOT_RUN", commands=[], started_at=utc_now())
    recorder = Recorder(run, summary, dict(os.environ))
    try:
        for name in ("run_ptx_copy_trace.py", "run_ptx_copy.py", "native_predicate_trace.py"):
            shutil.copy2(PROJECT / "scripts" / name, run / name)
        validate(run, recorder)
        summary["status"] = "PASS"
    except (RuntimeError, OSError, ValueError) as exc:
        summary["error"] = str(exc)
    finally:
        summary["finished_at"] = utc_now()
        recorder.save()
    print("{} {}".format(summary["status"], run))
    if "error" in summary:
        print(summary["error"])
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
