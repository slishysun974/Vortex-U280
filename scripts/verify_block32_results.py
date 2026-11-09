"""Recheck saved D5 evidence without rewriting runs or changing expected answers."""
import argparse
import json
from pathlib import Path
import re
import sys

from native_boundary import compare_captures
from run_native_smoke import PROJECT, sha256, utc_now


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,70}", args.run_id):
        parser.error("unsafe run id")
    args.output.mkdir(parents=True, exist_ok=False)
    checks = []
    def check(name, ok, detail=None):
        checks.append(dict(name=name, ok=bool(ok), detail=detail))

    candidate = PROJECT / "configs/candidates/block32-v1"
    candidate_lock = sha256(candidate / "target_lock.json")
    lock = json.loads((candidate / "target_lock.json").read_text())
    baseline_hashes = {
        "target_lock.json": "924b17abadbbda710ead2053ac0873fb0698161c983f8ff1feb9b96a16a19ffe",
        "target_caps.json": "b48d0e940a27ff53bf0708320067c31b7560c7fc489b9ad52319b1a0adf126ec",
        "native_smoke.json": "046ca59d289390bc1d0424fc35df0d552cc7a2f92c6c649d8c318d284c433b87",
    }
    for name, digest in baseline_hashes.items():
        check("baseline_unchanged/" + name, sha256(PROJECT / "configs" / name) == digest)
    root = PROJECT / "results" / args.run_id
    coordinator = json.loads((root / "summary.json").read_text())
    check("coordinator_pass", coordinator["status"] == "PASS")
    check("implementation_unchanged", coordinator["implementation_unchanged"])
    for relative, digest in coordinator["implementation_sha256"].items():
        check("executed_snapshot/" + relative, sha256(root / "implementation" / relative) == digest)
    for command in coordinator["commands"]:
        check("harness_tests", command["returncode"] == 0 and not command["timed_out"])
        check("harness_tests_log", sha256(root / command["log"]) == command["log_sha256"])
    runs = []
    def flags(path):
        return dict(token[2:].split("=", 1) if "=" in token else (token[2:], True)
                    for token in path.read_text().split())
    for backend in ("simx", "rtlsim", "xrtsim"):
        run = PROJECT / "results" / (args.run_id + "-" + backend)
        summary = json.loads((run / "summary.json").read_text())
        prefix = backend + "/"
        check(prefix + "status", summary["status"] == summary["upstream_smoke"] == summary["native_boundary"]["status"] == "PASS")
        check(prefix + "scope", summary["p0_three_kernels"] == summary["hardware_verification"] == "NOT_RUN")
        check(prefix + "profile", summary["target_profile"] == "block32-v1")
        check(prefix + "source", not summary["source"]["manifest_mismatches"] and not summary["source"]["source_changes"])
        check(prefix + "lock", summary["config_file_sha256"]["target_lock.json"] == candidate_lock)
        check(prefix + "config_snapshot", all(sha256(run / "configs" / name) == digest for name, digest in summary["config_file_sha256"].items()))
        check(prefix + "tools", all(lock["toolchain"]["observed_file_sha256"].get(name) == digest
                                     for name, digest in summary["toolchain_file_sha256"].items()))
        check(prefix + "commands", all(c["returncode"] == 0 and not c["timed_out"] for c in summary["commands"]))
        check(prefix + "logs", all(sha256(run / c["log"]) == c["log_sha256"] for c in summary["commands"]))
        check(prefix + "artifacts", all(sha256(run / a["review_copy"]) == a["sha256"] for a in summary["build_artifacts"].values()))
        before = flags(PROJECT / "results" / ("ab-d4-" + backend + "-20261108-v1") / "resolved_backend.cflags")
        after = flags(run / "resolved_backend.cflags")
        delta = {k: {"before": before.get(k), "after": after.get(k)}
                 for k in sorted(before.keys() | after.keys()) if before.get(k) != after.get(k)}
        check(prefix + "config_delta", delta == {
            "VX_CFG_NUM_WARPS": {"before": "4", "after": "8"},
            "VX_CFG_NUM_OPCS": {"before": "1", "after": "2"},
            "VX_CFG_LSU_PENDING_SIZE": {"before": "8", "after": "16"},
            "VX_CFG_AMO_RS_SIZE": {"before": "4", "after": "8"},
        }, delta)
        boundary = run / "boundary"
        corpus = json.loads((boundary / "corpus.json").read_text())
        corpus_hash = sha256(boundary / "corpus.json")
        check(prefix + "corpus", corpus_hash == summary["native_boundary"]["corpus_sha256"])
        check(prefix + "boundary_sources", all(sha256(boundary / "source" / name) == digest
                                               for name, digest in summary["native_boundary"]["source_sha256"].items()))
        check(prefix + "generator", sha256(boundary / "native_boundary.py") == corpus["generator_sha256"])
        comparison = compare_captures(boundary, corpus)
        saved = json.loads((boundary / "comparison.json").read_text())
        check(prefix + "152_captures", comparison == saved and comparison["status"] == "PASS" and comparison["passed"] == 152)
        check(prefix + "matrix", {c["block"] for c in corpus["cases"]} == {1, 4, 7, 16, 31, 32})
        execution = next(c for c in summary["commands"] if c["label"] == "boundary_run")
        output = (run / execution["log"]).read_text()
        check(prefix + "physical_caps", bool(re.search(r"(?m)^CAPS threads=4 warps=8 cores=1$", output)))
        check(prefix + "oversize_rejected", all(re.search(r"(?m)^BLOCK_REJECTION block=" + str(b) + r" actual=3 expected=3$", output) for b in (33, 64)))
        runs.append(dict(backend=backend, summary=str(run.relative_to(PROJECT) / "summary.json"),
                         summary_sha256=sha256(run / "summary.json"), corpus_sha256=corpus_hash,
                         kernel_sha256=summary["native_boundary"]["kernel_sha256"],
                         captures=[c["actual_sha256"] for c in saved["cases"]], launches=comparison["passed"]))
    for key in ("corpus_sha256", "kernel_sha256", "captures"):
        check("three_backend_same/" + key, all(r[key] == runs[0][key] for r in runs))
    for run in runs:
        run.pop("captures")
    passed = all(c["ok"] for c in checks)
    result = dict(schema_version="ab-d5-closeout-v1", status="PASS" if passed else "FAIL",
                  scope="native block32 self-test and evidence integrity only; not independent acceptance or PTX/U280",
                  exit_code=0 if passed else 1, argv=sys.argv, finished_at=utc_now(),
                  candidate_lock_sha256=candidate_lock, checks=checks, runs=runs,
                  u280_access="BLOCKED", network_evidence="results/ab-d5-u280-network-20261108-v2/probe.json",
                  board="NOT_RUN", independent_acceptance="NOT_RUN", p0="NOT_RUN")
    (args.output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "checks": len(checks), "failed": [c for c in checks if not c["ok"]],
                      "result": str(args.output / "result.json")}))
    return result["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
