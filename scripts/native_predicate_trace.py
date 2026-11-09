"""Native LSU issue observations; same-author reference, not PTX acceptance."""
from collections import Counter
import json
import re
import shutil

from native_boundary import make_vectors, encode, compare_captures
from run_native_smoke import PROJECT, sha256


def create_corpus(root, profile):
    block = 32 if profile == "block32-v1" else 16
    inputs, expected = root / "inputs", root / "expected"
    inputs.mkdir()
    expected.mkdir()
    cases, lines = [], []
    # Positive controls, zero-size, all false, partial warp, partial second CTA.
    for op in range(3):
        for label, n, pred in (("all_true", block * 2, 0), ("zero", 0, 0),
                               ("all_false", block * 2, 1), ("mixed_tail", block + 1, 2),
                               ("tail", 7, 0)):
            seq = len(cases)
            case = dict(id=f"{seq:03d}", sequence=seq, repeat=0, operation=op,
                        n=n, predicate=pred, alpha=0xffffffff, block=block, grid=2,
                        words=block * 2 + 16, audit_words=block * 8 + 16, label=label)
            src, ref = make_vectors(case)
            for group, values in (("inputs", src), ("expected", ref)):
                case[group] = {}
                for name, words in values.items():
                    filename = case["id"] + "_" + name + ".bin"
                    path = root / group / filename
                    path.write_bytes(encode(words))
                    case[group][filename] = sha256(path)
            lines.append("\t".join(str(case[k]) for k in
                ("id", "operation", "n", "block", "grid", "alpha", "predicate", "words", "audit_words")))
            cases.append(case)
    (inputs / "cases.tsv").write_text("\n".join(lines) + "\n", encoding="ascii")
    corpus = dict(schema_version="ab-native-predicate-trace-v1", cases=cases,
                  target_profile=profile, case_table_sha256=sha256(inputs / "cases.tsv"),
                  reference_owner="A/B author; not independent E acceptance", pointer_offset_bytes=32)
    (root / "corpus.json").write_text(json.dumps(corpus, indent=2) + "\n", encoding="utf-8")
    return corpus


def parse_request(line, backend):
    """Return active (operation, byte address) lanes, before cache coalescing.

    SimX prints both mask and addresses lane 0 first (BitVector::operator<<);
    RTL prints both high lane first. Pair the displayed characters directly.
    Never count masked addresses even if RTL prints a valid address there.
    Unknown candidate request lines fail closed instead of silently disappearing.
    """
    if backend == "simx":
        if not re.search(r"\blsu\S* mem-req:", line):
            return None
        match = re.search(r"mem-req: op=(LD|ST), mask=([01]+), addr=\{([^}]+)\}", line)
    else:
        if not re.search(r"\blsu\S* (?:Rd|Wr) Req:", line):
            return None
        match = re.search(r"(Rd|Wr) Req: .*tmask=([01]+), addr=\{([^}]+)\}", line)
    if not match:
        raise ValueError("unparsed LSU request: " + line[:240])
    op, bits, text = match.groups()
    op = {"Rd": "LD", "Wr": "ST"}.get(op, op)
    addresses = [v.strip() for v in text.split(",")]
    if len(addresses) != len(bits):
        raise ValueError("mask/address width mismatch")
    masks = list(bits)
    lanes = []
    for bit, address in zip(masks, addresses):
        if bit == "1":
            if not re.fullmatch(r"0x[0-9a-fA-F]+", address):
                raise ValueError("invalid active lane address")
            lanes.append((op, int(address, 16)))
        elif backend == "simx" and address != "-":
            raise ValueError("SimX masked lane must print a hole")
    return lanes


def expected_accesses(case, buffers):
    expected = Counter()
    for i in range(case["n"]):
        if case["predicate"] == 1 or (case["predicate"] == 2 and i % 2):
            continue
        expected[("LD", buffers[0] + 32 + 4 * i)] += 1
        if case["operation"] != 0:
            expected[("LD", buffers[1] + 32 + 4 * i)] += 1
        expected[("ST", buffers[2] + 32 + 4 * i)] += 1
    return expected


def counter_rows(counter):
    return [dict(op=op, address=hex(address), count=count)
            for (op, address), count in sorted(counter.items())]


def analyze(output, corpus, backend):
    buffers, observations, cases = {}, Counter(), []
    total_requests, case_requests = 0, 0
    for line in output.splitlines():
        match = re.fullmatch(r"BUFFER ([0-3]) address=(\d+)", line)
        if match:
            index, address = map(int, match.groups())
            if index in buffers:
                raise ValueError("duplicate buffer declaration")
            buffers[index] = address
        lanes = parse_request(line, backend)
        if lanes is not None:
            total_requests += 1
            case_requests += 1
            for op, address in lanes:
                if any(base <= address < base + 1056 * 4 for j, base in buffers.items() if j < 3):
                    observations[(op, address)] += 1
        match = re.fullmatch(r"CAPTURED (\d+) n=(\d+) block=(\d+) grid=(\d+)", line)
        if match:
            if len(buffers) != 4 or len(cases) >= len(corpus["cases"]):
                raise ValueError("missing buffers or extra capture")
            case = corpus["cases"][len(cases)]
            if list(match.groups()) != [case["id"], str(case["n"]), str(case["block"]), str(case["grid"])]:
                raise ValueError("capture order/parameters differ from frozen corpus")
            expected = expected_accesses(case, buffers)
            cases.append(dict(id=case["id"], label=case["label"], operation=case["operation"],
                status="PASS" if case_requests and observations == expected else "FAIL",
                lsu_requests=case_requests, expected_data_lanes=sum(expected.values()),
                observed_data_lanes=sum(observations.values()), observed=counter_rows(observations),
                missing=counter_rows(expected - observations), unexpected=counter_rows(observations - expected)))
            observations.clear()
            case_requests = 0
    passed = (len(cases) == len(corpus["cases"]) and total_requests > 0 and not observations
              and all(c["status"] == "PASS" for c in cases))
    return dict(status="PASS" if passed else "FAIL", backend=backend, cases=cases,
                observed_launches=len(cases), lsu_requests=total_requests,
                trailing_data_accesses=counter_rows(observations), buffers=buffers,
                scope="active LSU request lane addresses in full allocated x/y/z buffers, not cache-line fills; native kernel only")


def run_trace(recorder, args, configs):
    root = recorder.directory / "predicate_trace"
    root.mkdir()
    corpus = create_corpus(root, args.target_profile)
    corpus_hash = sha256(root / "corpus.json")
    (root / "actual").mkdir()
    app = args.build_dir / "tests/regression/boundary"
    if not getattr(args, "reuse_native_app", False):
        shutil.copytree(PROJECT / "native/boundary", app)
    shutil.copytree(PROJECT / "native/boundary", root / "source")
    info = dict(status="NOT_RUN", corpus_sha256=corpus_hash, planned_launches=len(corpus["cases"]),
                debug_level=3, observation="LSU issue before cache", backend=args.backend,
                not_verified=["PTX", "arbitrary invalid-pointer behavior", "whole-program exactly-once", "safe abort/recovery", "AFU", "U280", "independent E acceptance"])
    recorder.summary["native_predicate_trace"] = info
    make = ["make", "-j" + str(args.jobs), "CONFIGS=" + configs, "XLEN=64", "DEBUG=3",
            "THREADS=" + str(args.jobs), "THIRD_PARTY_DIR=" + str(args.build_dir / "third_party"), "-C", app]
    rec, _ = recorder.command("predicate_trace_build", make, args.build_dir, args.timeout)
    if rec["returncode"] != 0 or rec["timed_out"]:
        info["status"] = "FAIL"
        return False, "predicate_trace_build"
    rec, output = recorder.command("predicate_trace_run", make + ["run-" + args.backend,
        "OPTS=" + str(root / "inputs") + " " + str(root / "actual")], args.build_dir, args.timeout)
    comparison = compare_captures(root, corpus)
    trace = analyze(output, corpus, args.backend)
    # Tamper positive control: inject an extra real-format read into the first
    # all-false capture interval; the verifier must reject the mutated log.
    false_case = next(c for c in corpus["cases"] if c["label"] == "all_false")
    address = trace["buffers"][0] + 32
    injected = (f"DEBUG 0: lsu0 mem-req: op=LD, mask=1000, addr={{0x{address:x}, -, -, -}}, tag=0x0, cid=0 (#0)"
                if args.backend == "simx" else
                f"0: lsu0 Rd Req: wid=0, cta_id=0, PC=0x0, tmask=0001, addr={{0x0, 0x0, 0x0, 0x{address:x}}}, attr={{0}}")
    marker = "CAPTURED " + false_case["id"] + " "
    mutant = output.replace(marker, injected + "\n" + marker, 1)
    negative = analyze(mutant, corpus, args.backend)
    (root / "injected_fault.log").write_text(injected + "\n", encoding="utf-8")
    (root / "fault_detection.json").write_text(json.dumps(negative, indent=2) + "\n", encoding="utf-8")
    (root / "comparison.json").write_text(json.dumps(comparison, indent=2) + "\n", encoding="utf-8")
    (root / "trace_analysis.json").write_text(json.dumps(trace, indent=2) + "\n", encoding="utf-8")
    ok = (rec["returncode"] == 0 and not rec["timed_out"] and comparison["status"] == "PASS"
          and trace["status"] == "PASS" and negative["status"] == "FAIL"
          and sha256(root / "corpus.json") == corpus_hash
          and re.search(r"(?m)^CAPTURE_COMPLETE 15\s*$", output))
    info.update(status="PASS" if ok else "FAIL", exit_code=rec["returncode"],
                captures_passed=comparison["passed"], trace=trace["status"],
                synthetic_extra_read_detected=negative["status"] == "FAIL",
                kernel_sha256=sha256(app / "kernel.vxbin"))
    recorder.save()
    return bool(ok), "predicate_trace_run"
