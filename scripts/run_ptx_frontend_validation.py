"""Reproduce frontend author tests and instrumented HOST C++ semantics.

Uses prepared Linux g++; never claims SimX/RTL/AFU/U280 execution.
All source, inputs, expectations, captures, access traces and commands are saved.
"""
import argparse
import json
import os
from pathlib import Path
import random
import re
import shutil
import struct
import sys

import ptx_frontend as ptx
from run_native_smoke import PROJECT, Recorder, sha256, utc_now

BASE = 0x123400000000
N_VALUES = (0, 1, 7, 31, 32, 33, 63, 64, 65, 257, 1024)
BLOCKS = (1, 4, 7, 16, 31, 32)
EDGES = (0, 0xffffffff, 0x80000000, 0x7fffffff, 1, 2, 0xfffffffe, 0x55555555)


def encode(words):
    return struct.pack("<" + "I" * len(words), *words)


def corpus(directory, ir, operation):
    for name in ("inputs", "expected", "actual"):
        (directory / name).mkdir()
    cases = []
    specs = [(n, b, a, repeat) for n in N_VALUES for b in BLOCKS
             for a in ((0, 1, 0xffffffff) if operation == "affine" else (1,)) for repeat in range(2)]
    if operation == "probe":
        specs = [(16, 1, 1, 0)]
    for n, block, alpha, repeat in specs:
        case_id = "%04d" % len(cases)
        grid = max(1, (n + block - 1) // block) if operation != "probe" else 1
        size = max(1, n) + 16
        rng = random.Random(0xCD060000 + len(cases))
        arrays = {key: [rng.getrandbits(32) for _ in range(size)] for key in "xyz"}
        for i in range(min(n, len(EDGES))):
            arrays["x"][8 + i] = EDGES[(i + repeat) % len(EDGES)]
            arrays["y"][8 + i] = EDGES[(-1 - i + repeat) % len(EDGES)]
        expected = {key: list(value) for key, value in arrays.items()}
        for i in range(n):
            x, y = arrays["x"][8 + i], arrays["y"][8 + i]
            value = x if operation == "copy" else x + y if operation == "vadd" else alpha * x + y
            expected["z"][8 + i] = value % (1 << 32)
        if operation == "probe":
            expected["z"] = list(arrays["z"])
            expected["z"][8:19] = [0, 0xffffffff, 1, 0x12345678, 78, 0xfffffffc,
                                      1, 0xabcd, arrays["x"][8], 2, arrays["x"][8]]
        parameters = {key: BASE + i * 0x100000 + 32 if n else 0xfffffffffffffff0
                      for i, key in enumerate("xyz")}
        parameters.update(n=n, alpha=alpha)
        payload = ptx.pack_arguments(ir, [parameters[p["name"]] for p in ir["params"]])
        (directory / "inputs" / (case_id + "_params.bin")).write_bytes(payload)
        for group, contents in (("inputs", arrays), ("expected", expected)):
            for key, words in contents.items():
                (directory / group / (case_id + "_" + key + ".bin")).write_bytes(encode(words))
        loads = n if operation == "copy" else 2 * n
        stores = n
        if operation == "probe":
            loads, stores = 2, 11
        cases.append(dict(id=case_id, n=n, block=block, grid=grid, alpha=alpha,
                          repeat=repeat, words=size, expected_loads=loads, expected_stores=stores))
    table = "".join("%s\t%d\t%d\t%d\t%d\n" % (c["id"], c["n"], c["block"], c["grid"], c["words"]) for c in cases)
    (directory / "cases.tsv").write_text(table, encoding="ascii")
    files = {str(p.relative_to(directory)): sha256(p)
             for group in ("inputs", "expected") for p in sorted((directory / group).iterdir())}
    files["cases.tsv"] = sha256(directory / "cases.tsv")
    document = dict(schema_version="ptx-host-semantics-corpus-v1", operation=operation, cases=cases, files=files,
                    reference_owner="frontend implementation author; not independent E acceptance",
                    address_model="instrumented virtual addresses above 2^32; not physical device addresses",
                    n_zero="one block executes; all pointer arguments deliberately unmapped")
    (directory / "corpus.json").write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return document


def compare(directory, data):
    integrity = all((directory / name).is_file() and sha256(directory / name) == digest for name, digest in data["files"].items())
    count_path, trace_path = directory / "actual/counts.tsv", directory / "actual/trace.tsv"
    problems, counts, traces = [], {}, {}
    if count_path.is_file():
        for line in count_path.read_text().splitlines():
            key, *numbers = line.split("\t")
            if key in counts:
                problems.append("duplicate counts: " + key)
            counts[key] = list(map(int, numbers))
    if trace_path.is_file():
        with trace_path.open() as stream:
            for line in stream:
                key, bid, tid, kind, addr, value = line.rstrip().split("\t")
                traces.setdefault(key, []).append((int(bid), int(tid), kind, int(addr), int(value)))
    else:
        problems.append("missing access trace")
    expected_ids = {case["id"] for case in data["cases"]}
    if set(counts) != expected_ids or not set(traces) <= expected_ids:
        problems.append("unknown or missing case IDs")
    results = []
    for case in data["cases"]:
        case_errors, hashes = [], {}
        name = case["id"]
        for key in "xyz":
            filename = name + "_" + key + ".bin"
            actual = directory / "actual" / filename
            if not actual.is_file() or actual.read_bytes() != (directory / "expected" / filename).read_bytes():
                case_errors.append("mismatch/missing: " + filename)
            if actual.is_file():
                hashes[filename] = sha256(actual)
        expected_counts = [case["block"] * case["grid"], case["expected_loads"], case["expected_stores"]]
        if counts.get(name) != expected_counts:
            case_errors.append("invocation/access count mismatch")
        trace = traces.get(name, [])
        if sum(row[2] == "load" for row in trace) != case["expected_loads"] or sum(row[2] == "store" for row in trace) != case["expected_stores"]:
            case_errors.append("trace count mismatch")
        if data["operation"] != "probe":
            # Match the full per-thread order, addresses and values, not just totals.
            inputs = {key: struct.unpack("<" + "I" * case["words"], (directory / "inputs" / (name + "_" + key + ".bin")).read_bytes()) for key in "xy"}
            outputs = struct.unpack("<" + "I" * case["words"], (directory / "expected" / (name + "_z.bin")).read_bytes())
            expected_trace = []
            for i in range(case["n"]):
                bid, tid = divmod(i, case["block"])
                expected_trace.append((bid, tid, "load", BASE + 32 + 4 * i, inputs["x"][8 + i]))
                if data["operation"] != "copy":
                    expected_trace.append((bid, tid, "load", BASE + 0x100000 + 32 + 4 * i, inputs["y"][8 + i]))
                expected_trace.append((bid, tid, "store", BASE + 0x200000 + 32 + 4 * i, outputs[8 + i]))
            if trace != expected_trace:
                case_errors.append("per-thread memory trace mismatch")
        results.append(dict(id=name, status="FAIL" if case_errors else "PASS", problems=case_errors, actual_sha256=hashes))
    return dict(status="PASS" if integrity and not problems and results and all(c["status"] == "PASS" for c in results) else "FAIL",
                corpus_unchanged=integrity, problems=problems, passed=sum(c["status"] == "PASS" for c in results),
                cases=results, trace_sha256=sha256(trace_path) if trace_path.is_file() else None)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)
    if sys.platform != "linux" or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,70}", args.run_id):
        parser.error("requires Linux and safe new run ID")
    root = PROJECT / "results" / args.run_id
    root.mkdir(exist_ok=False)
    paths = list((PROJECT / "scripts").glob("*.py")) + list((PROJECT / "tests").glob("*.py"))
    paths += list((PROJECT / "ptx/samples").glob("*.ptx"))
    paths += list((PROJECT / "configs/ptx_frontend/v1").glob("*.json"))
    paths += [PROJECT / "native/ptx_host_check/main.cpp", PROJECT / "configs/target_lock.json", PROJECT / "configs/target_caps.json", PROJECT / "configs/candidates/block32-v1/target_lock.json"]
    snapshot = root / "implementation"
    for path in paths:
        target = snapshot / path.relative_to(PROJECT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    summary = dict(schema_version="ptx-frontend-validation-v1", status="RUNNING", started_at=utc_now(),
                   commands=[], scope="frontend author tests plus HOST C++ instrumented semantics only",
                   simx="NOT_RUN", rtlsim="NOT_RUN", afu="NOT_RUN", u280="NOT_RUN", independent_acceptance="NOT_RUN",
                   implementation_sha256={str(p.relative_to(PROJECT)): sha256(p) for p in paths}, modules=[])
    recorder = Recorder(root, summary, dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    def command(label, argv, timeout=180):
        result, output = recorder.command(label, argv, PROJECT, timeout)
        if result["returncode"] != 0 or result["timed_out"]:
            raise RuntimeError(label + " failed; see " + result["log"])
        return output
    try:
        command("python_tests", [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-v"])
        command("host_compiler", ["g++", "--version"])
        for sample, operation in (("copy_u32", "copy"), ("vadd_u32", "vadd"), ("affine_u32", "affine"), ("semantics_probe", "probe")):
            directory = root / sample
            directory.mkdir()
            source_path = PROJECT / "ptx/samples" / (sample + ".ptx")
            command(sample + "_frontend", [sys.executable, "-B", PROJECT / "scripts/ptx_frontend.py", source_path,
                    "--output", directory / "module"])
            ir = json.loads((directory / "module/ir.json").read_text())
            data = corpus(directory, ir, operation)
            frozen_corpus = sha256(directory / "corpus.json")
            command(sample + "_host_compile", ["g++", "-std=c++17", "-O2", "-Wall", "-Wextra", "-Wno-unused-variable",
                    "-Wno-unused-parameter", "-fsanitize=undefined", "-fno-sanitize-recover=all", "-I", directory / "module",
                    PROJECT / "native/ptx_host_check/main.cpp", "-o", directory / "host_audit"])
            output = command(sample + "_host_run", [directory / "host_audit", directory / "cases.tsv", directory / "inputs", directory / "actual"])
            comparison = compare(directory, data)
            comparison["corpus_manifest_unchanged"] = sha256(directory / "corpus.json") == frozen_corpus
            comparison["completion_marker"] = bool(re.search(r"(?m)^HOST_SEMANTICS_COMPLETE " + str(len(data["cases"])) + r"\s*$", output))
            comparison["status"] = "PASS" if comparison["status"] == "PASS" and comparison["corpus_manifest_unchanged"] and comparison["completion_marker"] else "FAIL"
            (directory / "comparison.json").write_text(json.dumps(comparison, indent=2) + "\n", encoding="utf-8")
            summary["modules"].append(dict(sample=sample, status=comparison["status"], cases=len(data["cases"]), passed=comparison["passed"],
                corpus_sha256=frozen_corpus, manifest_sha256=sha256(directory / "module/manifest.json"),
                executable_sha256=sha256(directory / "host_audit"), comparison_sha256=sha256(directory / "comparison.json")))
            print(sample + ": " + comparison["status"] + " " + str(comparison["passed"]), flush=True)
            recorder.save()
            if comparison["status"] != "PASS":
                raise RuntimeError("host comparison failed: " + sample)
        # Mutate a separate copy of emitted code to demonstrate that an eager
        # load is detected. The original generated bundle/reference stays intact.
        fault = root / "fault_eager_load"
        fault.mkdir()
        (fault / "actual").mkdir()
        original = (root / "copy_u32/module/kernel_body.hpp").read_text()
        broken, count = re.subn(r"if \([^\n]+\) \{ (v[0-9]+ = memory\.load32\([^\n]+); \}", r"\1;", original, count=1)
        if count != 1:
            raise RuntimeError("eager-load fault injection did not match exactly once")
        (fault / "kernel_body.hpp").write_text(broken, encoding="utf-8")
        (fault / "cases.tsv").write_text((root / "copy_u32/cases.tsv").read_text().splitlines()[0] + "\n")
        command("fault_eager_load_compile", ["g++", "-std=c++17", "-O2", "-I", fault,
                PROJECT / "native/ptx_host_check/main.cpp", "-o", fault / "host_audit"])
        record, output = recorder.command("fault_eager_load_run", [fault / "host_audit", fault / "cases.tsv", root / "copy_u32/inputs", fault / "actual"], PROJECT, 30)
        detected = record["returncode"] == 1 and not record["timed_out"] and "out-of-range or unaligned active memory access" in output
        summary["fault_injection"] = dict(status="PASS" if detected else "FAIL", expected_exit_code=1,
                                         actual_exit_code=record["returncode"], mutation="remove first predicated load guard in a separate generated-code copy",
                                         original_header_sha256=sha256(root / "copy_u32/module/kernel_body.hpp"),
                                         mutated_header_sha256=sha256(fault / "kernel_body.hpp"))
        if not detected:
            raise RuntimeError("eager-load fault not detected")
        summary["implementation_unchanged"] = all(sha256(PROJECT / path) == digest for path, digest in summary["implementation_sha256"].items())
        summary["status"] = "PASS" if summary["implementation_unchanged"] else "FAIL"
    except Exception as exc:
        summary.update(status="FAIL", error=str(exc))
        print(str(exc), file=sys.stderr)
    finally:
        summary["finished_at"] = utc_now()
        recorder.save()
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
