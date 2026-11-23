"""Exercise the P0 opcode witnesses through the production V03/V04 entry points."""
import argparse
import os
from pathlib import Path
import re
import shutil
import struct
import sys
import tempfile

import ptx_frontend_v12 as frontend
from ptx_module import inspect_vxbin, validate
from run_d_guarded_wide import BACKENDS, GUARD, HARDWARE, TOOLCHAIN, libraries, word_bytes
from run_native_smoke import PROJECT, Recorder, sha256, utc_now
from run_ptx_copy import (BOARD_LOCK, SIM_LOCK, VORTEX, capture_comparison, case_header,
                          read_json, require, run_stage, write_json)

SOURCE = PROJECT / "ptx/probes/p0_form_witness.ptx"
OPS = ("mov.u32", "mov.u64", "add.u32", "sub.u32", "mul.lo.u32", "mul.wide.u32",
       "add.u64", "cvta.to.global.u64", "setp.lt.u32", "setp.ge.u32", "setp.eq.u32",
       "selp.u32", "ld.global.u32", "st.global.u32")
MODES = ("plain", "positive", "negative")
MANDATORY = ("ld.param.u32", "ld.param.u64", "ret")
CASES = ("unsigned_edges", "rotated_edges")
EDGES = (0, 0x7fffffff, 0x80000000, 0xffffffff)
SEED = 0x5a5a5a5a


def expected_word(op, value, alternate, enabled):
    if op in ("mov.u64", "mul.wide.u32", "add.u64", "cvta.to.global.u64"):
        return value if enabled else alternate
    if op.startswith("setp."):
        result = {"setp.lt.u32": value < 2**31, "setp.ge.u32": value >= 2**31,
                  "setp.eq.u32": value == 0xffffffff}[op]
        return int(result if enabled else not result)
    if not enabled:
        return SEED
    if op in ("mov.u32", "ld.global.u32", "st.global.u32"):
        return value
    if op == "selp.u32":
        return 0x52 if value < 2**31 else 0x61
    return {"add.u32": value + 1, "sub.u32": value - 1, "mul.lo.u32": value * 3}[op] & 0xffffffff


def stage(root, ir, native_entry, rotation):
    words = GUARD + 4 * len(OPS) * len(MODES) + 1
    case = dict(id=root.name, block=4, grid=1, words=words, n=4, bias=1 << 30)
    x = [0xcdcdcdcd] * words
    for lane in range(4):
        x[GUARD + lane] = EDGES[(lane + rotation) % 4]
        x[GUARD + 4 + lane] = 0x12349870 + lane
    initial = [SEED] * words
    expected = initial.copy()
    for op_index, op in enumerate(OPS):
        for mode_index, mode in enumerate(MODES):
            start = GUARD + 4 * (3 * op_index + mode_index)
            for lane in range(4):
                enabled = mode == "plain" or (lane < 2) == (mode == "positive")
                expected[start + lane] = expected_word(op, x[GUARD + lane], x[GUARD + 4 + lane], enabled)
    for group, z in (("inputs", initial), ("expected", expected)):
        (root / group).mkdir(parents=True)
        for role, data in (("x", x), ("z", z)):
            (root / group / (root.name + "_" + role + ".bin")).write_bytes(word_bytes(data))
    write_json(root / "case.json", case)
    (root / "copy_case.hpp").write_text(case_header(case, dict(ir, entry=native_entry)), encoding="ascii")
    return case


def source_checks(module, report, codegen=frontend):
    ir = read_json(module / "ir.json")
    lines = (module / "source.ptx").read_text().splitlines()
    mapping = read_json(module / "source_map.json")
    require(len(ir["instructions"]) == len(mapping), "incomplete V03 map")
    profile = set(read_json(module / "profile.json")["instruction_forms"])
    require(set(OPS + MANDATORY) == profile, "profile differs from witness matrix")
    manifest = read_json(module / "frontend_manifest.json")
    require(manifest["validation_revision"] == frontend.VALIDATION_REVISION and
            manifest["compiler_id"] == codegen.COMPILER and
            manifest["compiler_sha256"] == sha256(Path(codegen.__file__)), "frontend identity mismatch")
    forms = {}
    for ins, mapped in zip(ir["instructions"], mapping):
        line = ins["source_location"]["line"]
        require(mapped["line"] == line, "source mapping mismatch")
        op = ins["opcode"]
        if op not in MANDATORY and not lines[line - 1].endswith("// witness"):
            continue
        guard = ins["predicate"]
        mode = "plain" if not guard else "negative" if guard["negated"] else "positive"
        require(not guard or guard["name"] == "active", "unexpected predicate")
        forms.setdefault(op, {}).setdefault(mode, []).append(dict(line=line, generated=mapped["generated_line"]))
    require(set(forms) == profile and all(set(forms[op]) == set(MODES) and
            all(len(locations) == 1 for locations in forms[op].values()) for op in OPS), "missing witness")
    report["forms"] = forms
    # Each negative uses the same just-built source and a single localized change.
    rejected = {}
    for op in OPS + MANDATORY:
        source = lines.copy()
        line = forms[op]["plain"][0]["line"]
        if op.startswith("ld.param"):
            source[line - 1] = re.sub(r"\[[^\]]+\]", "[z+4]", source[line - 1])
            code = "E_PARAM_LAYOUT"
        elif op == "ret":
            source[line - 1] = "    @active ret;"
            code = "E_UNSUPPORTED"
        elif op == "st.global.u32":
            source[line - 1] = "    st.global.u32 [dst+2], a;"
            code = "E_TYPE"
        else:
            # Predicates require a .pred destination, value instructions a .b32/.b64 destination.
            bad_dest = "tid" if op.startswith("setp.") else "flag"
            source[line - 1] = re.sub(r"(\S+\s+)\w+,", r"\g<1>" + bad_dest + ",", source[line - 1], count=1)
            code = "E_TYPE"
        try:
            frontend.parse("\n".join(source) + "\n", "negative.ptx")
        except frontend.PtxError as error:
            require(error.code == code and error.location["line"] == line, "wrong diagnostic for " + op)
            rejected[op] = dict(status="PASS", replacement=source[line - 1].strip(), diagnostic=error.to_dict())
        else:
            raise ValueError("negative accepted for " + op)
    report["rejections"] = rejected
    return ir


def compatibility_report():
    archive = PROJECT / "results/e-runtime-unseen-build-20261111-v1/modules"
    sources = PROJECT / "configs/acceptance/e-runtime-unseen-20261111-v1/sources"
    rows = {}
    for target, lock in (("sim", SIM_LOCK), ("board", BOARD_LOCK)):
        for name in ("copy", "vadd", "affine", "copy_variant", "vadd_variant", "affine_variant"):
            module = archive / target / name
            manifest, _ = validate(module, lock.read_bytes())
            require(sha256(sources / (name + ".ptx")) == manifest["source_sha256"], "frozen PTX differs")
            rows[target + "/" + name] = dict(status="PASS", image_sha256=manifest["image_sha256"],
                    source_sha256=manifest["source_sha256"], target_lock_sha256=sha256(lock))
    return rows


def execute(run, rec):
    report = rec.summary
    module = run / "module"
    driver = [sys.executable, "-B", PROJECT / "scripts/ptx_module.py"]
    for label, args in (("prepare", [SOURCE, "--output", module, "--hardware", HARDWARE]),
                        ("build", [module, "--build-root", PROJECT / "build" / run.name,
                                   "--vortex-source", VORTEX, "--tooldir", TOOLCHAIN]),
                        ("validate", [module])):
        run_stage(rec, label, driver + [label, *args, "--target-lock", SIM_LOCK], run, timeout=360)
    manifest, image = validate(module, SIM_LOCK.read_bytes())
    pc = inspect_vxbin(image)["entry_pc"]
    ir = source_checks(module, report)
    report.update(source_sha256=sha256(SOURCE), image_sha256=manifest["image_sha256"],
                  target_lock_sha256=sha256(SIM_LOCK), archived_modules=compatibility_report())
    paths = libraries()
    report["libraries"] = {backend: hashes for backend, (_, hashes) in paths.items()}
    cases = [stage(run / cid, ir, manifest["native_entry"], rotation)
             for cid, rotation in zip(CASES, (0, 2))]
    corpus = {p.relative_to(run).as_posix(): sha256(p) for cid in CASES
              for p in (run / cid).rglob("*") if p.is_file()}
    write_json(run / "corpus.json", corpus)
    for case in cases:
        root = run / case["id"]
        host = root / "capture"
        run_stage(rec, "host_" + root.name, ["g++", "-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror",
                  "-I" + str(root), "-I" + str(VORTEX / "sw/runtime/include"), PROJECT / "native/ptx_copy/main.cpp",
                  "-L" + str(paths["simx"][0]), "-lvortex", "-o", host], root)
        for backend, (lib, _) in paths.items():
            actual = root / backend / "actual"
            actual.mkdir(parents=True)
            shutil.copyfile(module / "kernel.vxbin", actual.parent / "kernel.vxbin")
            stdout = run_stage(rec, backend + "_" + root.name, ["env", "-u", "XCLBIN_PATH", "-u", "XCL_EMULATION_MODE",
                    "VORTEX_DRIVER=" + ("xrt" if backend == "xrtsim" else backend), "LD_LIBRARY_PATH=" + str(lib),
                    "VORTEX_PROFILING=0", "XRT_DEVICE_INDEX=0", host, root / "inputs", actual], actual.parent, 150)
            require(stdout.splitlines().count("CAPTURE_COMPLETE 1") == 1 and
                    stdout.splitlines().count("CAPTURED {id} n={n} block={block} grid={grid}".format(**case)) == 1,
                    "missing device capture")
            comparison = capture_comparison(root, actual, stdout, case, ir, pc)
            ptr = comparison["device_addresses"]
            comparison["fixed_layout_match"] = (actual / (root.name + "_params.bin")).read_bytes() == struct.pack(
                "<QQI4x", ptr["x"], ptr["z"], case["bias"])
            filename = root.name + "_z.bin"
            result = (actual / filename).read_bytes()
            answer = (root / "expected" / filename).read_bytes()
            columns = {}
            for index, op in enumerate(OPS):
                for mode_index, mode in enumerate(MODES):
                    start = GUARD * 4 + 16 * (3 * index + mode_index)
                    columns[op + "/" + mode] = result[start:start+16] == answer[start:start+16]
            comparison["columns"] = columns
            write_json(actual.parent / "comparison.json", comparison)
            require(comparison["status"] == "PASS" and comparison["fixed_layout_match"] and all(columns.values()),
                    "capture or ABI mismatch: " + str(actual))
            report["backends"][backend][root.name] = dict(status="PASS", columns=len(columns), lanes=4)
            rec.save()
    require(all(sha256(run / path) == digest for path, digest in corpus.items()), "corpus changed")


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--run-id", required=True)
    args = cli.parse_args()
    if not re.fullmatch(r"d-p0-forms-[A-Za-z0-9_-]{1,64}", args.run_id):
        cli.error("supply a fresh d-p0-forms-* run id")
    run = PROJECT / "results" / args.run_id
    run.mkdir()
    report = dict(run_id=run.name, argv=sys.argv, started_at=utc_now(), scope="D author P0 model witnesses",
                  status="RUNNING", commands=[], backends={b: {} for b in BACKENDS},
                  independent_acceptance="NOT_RUN", u280="NOT_RUN")
    with tempfile.TemporaryDirectory(prefix="d-p0-forms-") as scratch:
        rec = Recorder(run, report, dict(os.environ), scratch_logs=scratch)
        try:
            for path in (SOURCE, Path(__file__).resolve(), Path(frontend.__file__), PROJECT / "native/ptx_copy/main.cpp"):
                dest = run / "implementation" / path.relative_to(PROJECT)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, dest)
            execute(run, rec)
            report.update(status="PASS", exit_code=0)
        except (KeyError, OSError, ValueError, RuntimeError) as exc:
            report.update(status="FAIL", exit_code=1, error=str(exc))
        report["finished_at"] = utc_now()
        rec.save()
    print(report["status"], run, report.get("error", ""))
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
