"""D author verification of the guarded wide-address PTX probe on three models."""
import argparse
from collections import defaultdict
import os
from pathlib import Path
import re
import shutil
import struct
import sys
import tempfile

from native_predicate_trace import parse_request
from ptx_boundary_trace import bind_simx, bind_slots
from ptx_module import inspect_vxbin
from run_native_smoke import PROJECT, Recorder, sha256, utc_now
from run_ptx_copy import (SIM_LOCK, VORTEX, capture_comparison, case_header, read_json,
                          require, run_stage, write_json)
from run_ptx_copy_trace import RTL_CONTEXT, SIMX_DECODE, trace_libraries
from runtime_backends import validate_native

SOURCE = PROJECT / "ptx/probes/guarded_wide_offset.ptx"
HARDWARE = SIM_LOCK.with_name("native_smoke.json")
TOOLCHAIN = Path("/opt/vortex-ab/toolchains/8c64cf921d3c6c456e80f00d24482d0aa2153a82-rtlsim-d3-v1")
BACKENDS = ("simx", "rtlsim", "xrtsim")
# Volatile word access sites reviewed in kernel_main for this exact vxbin.
IMAGE_SHA = "1227ab66936b091f766f81e4b04b3a657467a9c27adb2bdbfdf0f1ddfa0395d2"
LOAD, STORE, AUDIT = 0x1800001d8, 0x1800001f8, 0x180000248
DATA_PCS = {LOAD, STORE, AUDIT}
GUARD = 8  # words before each pointer, as in the native capture host
SEED = 0xa5a55a5a
U32 = 0xffffffff
BASE_BIAS = 1 << 30
# (id, block, grid, n, excluded thread within each block, extra input/output words)
CASES = (
    ("zero", 4, 2, 0, 7, 0), ("full", 4, 2, 8, 7, 0),
    ("interior_hole", 4, 2, 8, 1, 1), ("partial_warp", 3, 3, 7, 2, 0),
    ("single", 1, 1, 1, 3, 1), ("all_excluded", 1, 2, 2, 0, 0),
)


def word_bytes(values):
    return struct.pack("<" + "I" * len(values), *values)


def stage(run, spec, ir, native_entry):
    name, block, grid, n, skip, extra = spec
    total = block * grid
    size = GUARD + total + extra + 1  # full case writes the last allocated word
    case = dict(id=name, block=block, grid=grid, n=n, skip_lane=skip,
                bias=BASE_BIAS + extra, words=size)
    root = run / name
    root.mkdir()
    edge = (0xffffffff, 0, 0x80000000, 0x7fffffff, 2, 0xfffffffe, 11, 0x80000001)
    inputs = dict(x=[edge[i % len(edge)] for i in range(size)],
                  z=[0x31a00000 + i for i in range(size)],
                  audit=[0xda700000 + i for i in range(size)])
    expected = {role: words.copy() for role, words in inputs.items()}
    for i in range(total):
        value = SEED
        if i < n and i % block != skip:
            value = inputs["x"][GUARD + i + extra]
            expected["z"][GUARD + i + extra + 1] = (value + (value >= 2**31)) & U32
        expected["audit"][GUARD + i] = (value + grid) & U32
    for group, arrays in (("inputs", inputs), ("expected", expected)):
        (root / group).mkdir()
        for role, words in arrays.items():
            (root / group / (name + "_" + role + ".bin")).write_bytes(word_bytes(words))
    # V04 exports one native symbol. Its source-level PTX name stays in the IR.
    (root / "copy_case.hpp").write_text(case_header(case, dict(ir, entry=native_entry)), encoding="ascii")
    write_json(root / "case.json", case)
    return case


def lane_rows(view, backend, case, addresses):
    """The six geometries use one physical warp per CTA, so lane equals tid.x."""
    require(1 <= case["block"] <= 4, "probe trace requires one warp per block")
    ranges = sorted((ptr - 4 * GUARD, ptr - 4 * GUARD + 4 * case["words"]) for ptr in addresses.values())
    require(all(a[1] <= b[0] for a, b in zip(ranges, ranges[1:])), "overlapping buffers")
    decoded, observed = {}, defaultdict(list)
    for line in view.splitlines():
        if backend == "simx" and (match := SIMX_DECODE.search(line)):
            block, pc, uid = match.groups()
            decoded[uid] = int(block), int(pc, 16)
        active = parse_request(line, backend)
        if active is None:
            continue
        if backend == "simx":
            uid = re.search(r" \(#(\d+)\)$", line)
            require(uid and uid[1] in decoded, "missing SimX LSU decode")
            block, pc = decoded[uid[1]]
        else:
            match = RTL_CONTEXT.search(line)
            require(match, "missing RTL LSU context")
            block, pc = int(match[1]), int(match[2], 16)
        mask = re.search(r"\b(?:tmask|mask)=([01]{4}), addr=", line)
        require(mask, "expected four physical lanes")
        lanes = [i if backend == "simx" else 3 - i for i, bit in enumerate(mask[1]) if bit == "1"]
        require(len(lanes) == len(active), "active-lane count differs")
        for lane, (op, address) in zip(lanes, active):
            if pc in DATA_PCS or any(lo <= address < hi for lo, hi in ranges):
                observed[block, lane].append((pc, op, address))
    return observed


def check_trace(raw, backend, case, addresses):
    if backend == "simx":
        view, bindings = bind_simx(raw, case)
    else:
        view, bindings = bind_slots(raw, case["grid"])
    observed = lane_rows(view, backend, case, addresses)
    expected = {}
    for i in range(case["grid"] * case["block"]):
        block, lane = divmod(i, case["block"])
        accesses = []
        if i < case["n"] and lane != case["skip_lane"]:
            offset = 4 * (i + case["bias"] - BASE_BIAS)
            accesses.extend([(LOAD, "LD", addresses["x"] + offset),
                             (STORE, "ST", addresses["z"] + offset + 4)])
        accesses.append((AUDIT, "ST", addresses["audit"] + 4 * i))
        expected[block, lane] = accesses
    rows = [dict(block=b, lane=t, expected=expected.get((b, t), []),
                 observed=observed.get((b, t), [])) for b, t in sorted(expected.keys() | observed.keys())]
    return dict(status="PASS" if observed == expected else "FAIL", bindings=bindings, lanes=rows,
                counts={role: sum(pc == site for ops in observed.values() for pc, _, _ in ops)
                        for role, site in (("guarded_load", LOAD), ("guarded_store", STORE), ("audit_store", AUDIT))})


def libraries():
    paths = {backend: trace_libraries(backend) for backend in ("simx", "rtlsim")}
    run = PROJECT / "results/ab-d5-block32-20261108-v1-xrtsim"
    native = read_json(run / "summary.json")
    validate_native(native, "xrtsim", sha256(SIM_LOCK))
    lib = Path(native["build_path"]) / "sw/runtime"
    hashes = {name: sha256(lib / name) for name in
              ("libvortex.so", "libvortex-xrt.so", "libxrtsim.so", "xrt_config.stamp", "xrtsim_config.stamp")}
    require(all(digest == native["build_artifacts"]["sw/runtime/" + name]["sha256"]
                for name, digest in hashes.items()), "NOXRT AFU library/config mismatch")
    paths["xrtsim"] = lib, hashes
    return paths


def execute(run, recorder):
    report = recorder.summary
    module = run / "module"
    cli = [sys.executable, "-B", PROJECT / "scripts/ptx_module.py"]
    for label, args in (
        ("prepare", [SOURCE, "--output", module, "--hardware", HARDWARE]),
        ("build", [module, "--build-root", PROJECT / "build" / run.name,
                   "--vortex-source", VORTEX, "--tooldir", TOOLCHAIN]),
        ("validate", [module]),
    ):
        run_stage(recorder, label, cli + [label, *args, "--target-lock", SIM_LOCK], run, timeout=360)
    image = module / "kernel.vxbin"
    require(sha256(image) == IMAGE_SHA, "review the LSU PCs for the changed image")
    ir = read_json(module / "ir.json")
    manifest = read_json(module / "manifest.json")
    forms = sorted({ins["opcode"] for ins in ir["instructions"]})
    require(forms == sorted(read_json(module / "profile.json")["instruction_forms"]), "source form coverage differs")
    require(sha256(SOURCE) == manifest["source_sha256"], "probe source changed")
    report.update(image_sha256=IMAGE_SHA, source_sha256=sha256(SOURCE), source_forms=forms,
                  target_lock_sha256=sha256(SIM_LOCK), data_pc={k: hex(v) for k, v in
                  (("x", LOAD), ("z", STORE), ("audit", AUDIT))})
    pc = inspect_vxbin(image.read_bytes())["entry_pc"]
    cases = [stage(run, spec, ir, manifest["native_entry"]) for spec in CASES]
    corpus = {p.relative_to(run).as_posix(): sha256(p) for case in cases
              for p in sorted((run / case["id"]).rglob("*")) if p.is_file()}
    write_json(run / "corpus.json", corpus)
    report["corpus_sha256"] = sha256(run / "corpus.json")
    paths = libraries()
    report["libraries"] = {backend: hashes for backend, (_, hashes) in paths.items()}
    host_source = PROJECT / "native/ptx_copy/main.cpp"
    for case in cases:
        root = run / case["id"]
        host = root / "capture"
        run_stage(recorder, "host_" + root.name, ["g++", "-std=c++17", "-O2", "-Wall", "-Wextra",
                  "-Werror", "-I" + str(root), "-I" + str(VORTEX / "sw/runtime/include"), host_source,
                  "-L" + str(paths["simx"][0]), "-lvortex", "-o", host], root)
        for backend, (lib, _) in paths.items():
            report["backends"][backend]["status"] = "RUNNING"
            stage_dir = root / backend
            actual = stage_dir / "actual"
            actual.mkdir(parents=True)
            shutil.copyfile(image, stage_dir / "kernel.vxbin")
            label = backend + "_" + root.name
            stdout = run_stage(recorder, label, ["env", "-u", "XCLBIN_PATH", "-u", "XCL_EMULATION_MODE",
                "VORTEX_DRIVER=" + ("xrt" if backend == "xrtsim" else backend), "LD_LIBRARY_PATH=" + str(lib),
                "VORTEX_PROFILING=0", "XRT_DEVICE_INDEX=0", host, root / "inputs", actual], stage_dir, timeout=150)
            require(stdout.splitlines().count("CAPTURE_COMPLETE 1") == 1 and
                    stdout.splitlines().count("CAPTURED {id} n={n} block={block} grid={grid}".format(**case)) == 1,
                    "missing capture or incorrect geometry")
            comparison = capture_comparison(root, actual, stdout, case, ir, pc)
            pointers = comparison["device_addresses"]
            payload = struct.pack("<QQQIII4x", pointers["x"], pointers["z"], pointers["audit"],
                                  case["n"], case["skip_lane"], case["bias"])
            comparison["fixed_layout_match"] = payload == (actual / (root.name + "_params.bin")).read_bytes()
            write_json(stage_dir / "comparison.json", comparison)
            require(comparison["status"] == "PASS" and comparison["fixed_layout_match"], "array or ABI mismatch")
            row = dict(id=root.name, status="PASS", host_sha256=sha256(host))
            if backend != "xrtsim":
                trace = check_trace(stdout, backend, case, pointers)
                write_json(stage_dir / "trace.json", trace)
                require(trace["status"] == "PASS", label + " lane trace mismatch")
                row["counts"] = trace["counts"]
            report["backends"][backend]["cases"].append(row)
            if len(report["backends"][backend]["cases"]) == len(cases):
                report["backends"][backend]["status"] = "PASS"
            recorder.save()
        print(root.name, "3 backends PASS", flush=True)
    require(all(sha256(run / name) == digest for name, digest in corpus.items()), "case files changed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"d-guarded-wide-[A-Za-z0-9_-]{1,64}", args.run_id):
        parser.error("supply a fresh d-guarded-wide-* run id")
    run = PROJECT / "results" / args.run_id
    run.mkdir()
    summary = dict(run_id=run.name, status="RUNNING", started_at=utc_now(), commands=[],
                   scope="D author probe on RV64 1c/8w/4t models", independent_acceptance="NOT_RUN",
                   u280="NOT_RUN", backends={b: dict(status="NOT_RUN", cases=[]) for b in BACKENDS})
    with tempfile.TemporaryDirectory(prefix="d-guarded-wide-") as spool:
        recorder = Recorder(run, summary, dict(os.environ), scratch_logs=spool)
        try:
            implementation = run / "implementation"
            for path in (SOURCE, PROJECT / "native/ptx_copy/main.cpp", Path(__file__).resolve(),
                         PROJECT / "scripts/ptx_frontend_v12.py", PROJECT / "scripts/ptx_module.py",
                         PROJECT / "scripts/run_ptx_copy_trace.py", PROJECT / "scripts/native_predicate_trace.py",
                         PROJECT / "scripts/ptx_boundary_trace.py", PROJECT / "scripts/run_ptx_copy.py",
                         PROJECT / "scripts/run_native_smoke.py", PROJECT / "scripts/ptx_sequence_trace.py",
                         PROJECT / "scripts/runtime_backends.py", PROJECT / "scripts/ptx_frontend.py"):
                dest = implementation / path.relative_to(PROJECT)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, dest)
            execute(run, recorder)
            summary["status"] = "PASS"
        except (OSError, RuntimeError, ValueError, KeyError) as error:
            summary.update(status="FAIL", error=str(error))
            for record in summary["backends"].values():
                if record["status"] == "RUNNING":
                    record["status"] = "PARTIAL" if record["cases"] else "FAIL"
            print(str(error), file=sys.stderr)
        finally:
            summary.update(finished_at=utc_now(), exit_code=int(summary["status"] != "PASS"))
            recorder.save()
    print(summary["status"], run)
    return summary["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
