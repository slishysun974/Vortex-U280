"""Native A/B u32 regression; Python reference is not E's independent oracle."""
import json
from pathlib import Path
import random
import re
import shutil
import struct

from run_native_smoke import PROJECT, sha256

MASK = (1 << 32) - 1
N_VALUES = (0, 1, 7, 31, 32, 33, 63, 64, 65, 257, 1024)
EDGES = (0, MASK, 0x80000000, 0x7fffffff, 1, 2, 0xfffffffe, 0x55555555)


def encode(words):
    return struct.pack("<" + "I" * len(words), *words)


def make_vectors(case):
    rng = random.Random(0xAB040000 + case["sequence"])
    words, audit_words = case["words"], case["audit_words"]
    x = [rng.getrandbits(32) for _ in range(words)]
    y = [rng.getrandbits(32) for _ in range(words)]
    for i in range(min(case["n"], len(EDGES))):
        x[8 + i] = EDGES[(i + case["repeat"]) % len(EDGES)]
        y[8 + i] = EDGES[(len(EDGES) - 1 - i + case["repeat"]) % len(EDGES)]
    z = [rng.getrandbits(32) for _ in range(words)]
    audit = [0xa5a50000 + case["sequence"]] * audit_words
    expected_z = list(z)
    for i in range(case["n"]):
        if case["predicate"] == 1 or (case["predicate"] == 2 and i % 2):
            continue
        a, b = x[8 + i], y[8 + i]
        op = case["operation"]
        expected_z[8 + i] = (a if op == 0 else a + b if op == 1 else case["alpha"] * a + b) & MASK
    expected_audit = list(audit)
    for bid in range(case["grid"]):
        for tid in range(case["block"]):
            start = 8 + 4 * (bid * case["block"] + tid)
            expected_audit[start:start + 4] = [bid, tid, case["block"], case["grid"]]
    inputs = dict(x=x, y=y, z=z, audit=audit)
    expected = dict(x=x, y=y, z=expected_z, audit=expected_audit)
    return inputs, expected


def create_corpus(root, profile="smoke"):
    if profile not in ("smoke", "block32-v1"):
        raise ValueError("unsupported boundary profile")
    default_block = 32 if profile == "block32-v1" else 16
    inputs, expected = root / "inputs", root / "expected"
    inputs.mkdir(parents=True, exist_ok=False)
    expected.mkdir()
    specs = [(op, n, default_block, alpha, 0) for n in N_VALUES
             for op, alpha in ((0, 1), (1, 1), (2, 0), (2, 1), (2, MASK))]
    blocks = (1, 4, 7, 16, 31) if profile == "block32-v1" else (1, 4, 7)
    specs += [(op, 33, b, MASK, 0) for b in blocks for op in range(3)]
    specs += [(op, 33, default_block, MASK, pred) for pred in (1, 2) for op in range(3)]
    cases, lines = [], []
    for spec in specs:
        op, n, block, alpha, predicate = spec
        grid = max(1, (n + block - 1) // block)
        for repeat in range(2):
            sequence = len(cases)
            case = dict(id=f"{sequence:03d}", sequence=sequence, operation=op, n=n,
                        block=block, grid=grid, alpha=alpha, predicate=predicate, repeat=repeat,
                        words=grid * block + 16, audit_words=4 * grid * block + 16)
            src, ref = make_vectors(case)
            case["inputs"], case["expected"] = {}, {}
            for label in src:
                filename = case["id"] + "_" + label + ".bin"
                (inputs / filename).write_bytes(encode(src[label]))
                (expected / filename).write_bytes(encode(ref[label]))
                case["inputs"][filename] = sha256(inputs / filename)
                case["expected"][filename] = sha256(expected / filename)
            lines.append("\t".join(str(case[key]) for key in
                         ("id", "operation", "n", "block", "grid", "alpha", "predicate", "words", "audit_words")))
            cases.append(case)
    (inputs / "cases.tsv").write_text("\n".join(lines) + "\n", encoding="ascii")
    corpus = dict(schema_version="ab-native-boundary-v2", target_profile=profile, cases=cases,
                  reference_owner="A/B implementation agent; not E independent acceptance",
                  generator_sha256=sha256(__file__), case_table_sha256=sha256(inputs / "cases.tsv"),
                  byte_order="little", pointer_offset_bytes=32,
                  physical_config="RV64/1c/8w/4t" if profile == "block32-v1" else "RV64/1c/4w/4t")
    (root / "corpus.json").write_text(json.dumps(corpus, indent=2) + "\n", encoding="utf-8")
    return corpus


def compare_captures(root, corpus):
    cases = []
    table = root / "inputs/cases.tsv"
    integrity = table.is_file() and sha256(table) == corpus["case_table_sha256"]
    for case in corpus["cases"]:
        problems, hashes = [], {}
        for group in ("inputs", "expected"):
            for filename, digest in case[group].items():
                path = root / group / filename
                if not path.is_file() or sha256(path) != digest:
                    problems.append({"file": group + "/" + filename, "reason": "corpus_changed"})
        for filename in case["expected"]:
            path, reference = root / "actual" / filename, root / "expected" / filename
            if not path.is_file():
                problems.append({"file": filename, "reason": "missing_capture"})
                continue
            raw = path.read_bytes()
            hashes[filename] = sha256(path)
            if not reference.is_file() or raw != reference.read_bytes():
                problems.append({"file": filename, "reason": "byte_mismatch", "actual_bytes": len(raw)})
        cases.append({"id": case["id"], "status": "FAIL" if problems else "PASS",
                      "problems": problems, "actual_sha256": hashes})
    return dict(status="PASS" if integrity and cases and all(c["status"] == "PASS" for c in cases) else "FAIL",
                case_table_unchanged=integrity, launch_count=len(cases),
                passed=sum(c["status"] == "PASS" for c in cases), cases=cases)


def run_boundary(recorder, args, configs):
    directory = recorder.directory / "boundary"
    directory.mkdir()
    profile = getattr(args, "target_profile", "smoke")
    corpus = create_corpus(directory, profile)
    (directory / "actual").mkdir()
    corpus_digest = sha256(directory / "corpus.json")
    app = args.build_dir / "tests/regression/boundary"
    shutil.copytree(PROJECT / "native/boundary", app)
    shutil.copytree(PROJECT / "native/boundary", directory / "source")
    shutil.copy2(__file__, directory / "native_boundary.py")
    summary = recorder.summary
    summary["native_boundary"] = {
        "status": "NOT_RUN", "schema_version": "ab-native-boundary-v2", "planned_launches": len(corpus["cases"]),
        "distinct_case_specs": len(corpus["cases"]) // 2, "corpus_sha256": corpus_digest,
        "source_sha256": {p.name: sha256(p) for p in sorted(app.iterdir()) if p.is_file()},
        "scope": "native u32 copy/vadd/affine; input/output guards, thread-index records, sequential reuse; same-agent Python reference",
        "not_verified": ["PTX translation", "project module/runtime ABI", "independent E acceptance",
                         "false-predicate absence of reads", "exactly-once execution", "safe abort/recovery", "U280"],
    }
    make = ["make", "-j" + str(args.jobs), "CONFIGS=" + configs, "XLEN=64", "THREADS=" + str(args.jobs),
            "THIRD_PARTY_DIR=" + str(args.build_dir / "third_party")]
    if args.backend == "xrtsim":
        make.append("TARGET=xrtsim")
    record, _ = recorder.command("boundary_build", make + ["-C", app], args.build_dir, args.timeout)
    if record["returncode"] != 0 or record["timed_out"]:
        summary["native_boundary"]["build"] = "FAIL"
        return False, "boundary_build"
    summary["native_boundary"]["build"] = "PASS"
    backend = "xrt" if args.backend == "xrtsim" else args.backend
    record, output = recorder.command("boundary_run", make + ["-C", app, "run-" + backend,
        "OPTS=" + str(directory / "inputs") + " " + str(directory / "actual")], args.build_dir, args.timeout)
    comparison = compare_captures(directory, corpus)
    (directory / "comparison.json").write_text(json.dumps(comparison, indent=2) + "\n", encoding="utf-8")
    expected_count = len(corpus["cases"])
    execution_ok = record["returncode"] == 0 and not record["timed_out"] and bool(
        re.search(r"(?m)^CAPTURE_COMPLETE " + str(expected_count) + r"\s*$", output))
    limit = 32 if profile == "block32-v1" else 16
    rejection_ok = all(re.search(r"(?m)^BLOCK_REJECTION block=" + str(block) + r" actual=3 expected=3\s*$", output)
                       for block in (limit + 1, limit * 2))
    unchanged = sha256(directory / "corpus.json") == corpus_digest
    passed = execution_ok and rejection_ok and unchanged and comparison["status"] == "PASS"
    summary["native_boundary"].update(status="PASS" if passed else "FAIL", execution="PASS" if execution_ok else "FAIL",
        native_oversize_rejection="PASS" if rejection_ok else "FAIL", rejected_blocks=[limit + 1, limit * 2],
        corpus_unchanged=unchanged,
        comparison=comparison["status"], passed_captures=comparison["passed"], exit_code=record["returncode"],
        evidence="boundary/comparison.json", kernel_sha256=sha256(app / "kernel.vxbin"))
    recorder.save()
    return passed, "boundary_run"
