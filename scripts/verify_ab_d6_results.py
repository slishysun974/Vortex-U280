"""Offline closeout for native LSU observations and authenticated host inventory."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
from datetime import datetime, timezone

from native_predicate_trace import analyze


ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--simx", required=True)
    parser.add_argument("--rtlsim", required=True)
    parser.add_argument("--inventory", required=True)
    parser.add_argument("--tests", required=True)
    args = parser.parse_args()
    import re
    for value in vars(args).values():
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", value):
            parser.error("all arguments must be safe run directory names")
    output = ROOT / "results" / args.run_id
    output.mkdir(exist_ok=False)
    checks = []
    def check(name, ok, detail=None):
        checks.append(dict(name=name, status="PASS" if ok else "FAIL", detail=detail))
    kernels = []
    evidence = {}
    try:
        for backend in ("simx", "rtlsim"):
            directory = ROOT / "results" / getattr(args, backend)
            summary = json.loads((directory / "summary.json").read_text())
            check(backend + ": completed", summary["status"] == "PASS")
            check(backend + ": debug profile", summary["debug_level"] == 3 and summary["target_profile"] == "block32-v1")
            check(backend + ": source unchanged", summary["source"]["manifest_mismatches"] == [])
            if "reused_build" in summary:
                reuse = summary["reused_build"]
                original = ROOT / "results" / reuse["parent"]
                check(backend + ": parent unchanged", digest(original / "summary.json") == reuse["parent_summary_sha256"])
                check(backend + ": reused artifacts unchanged", reuse["unchanged"] is True and reuse["before_sha256"] == reuse["after_sha256"])
                inherited = json.loads((original / "summary.json").read_text())
                for command in inherited["commands"]:
                    check(backend + ": inherited " + command["label"], command["returncode"] == 0 and not command["timed_out"]
                          and digest(original / command["log"]) == command["log_sha256"])
            for command in summary["commands"]:
                check(backend + ": command " + command["label"], command["returncode"] == 0 and not command["timed_out"]
                      and digest(directory / command["log"]) == command["log_sha256"])
            for relative, artifact in summary["build_artifacts"].items():
                check(backend + ": artifact " + relative, digest(directory / artifact["review_copy"]) == artifact["sha256"])
            root = directory / "predicate_trace"
            corpus = json.loads((root / "corpus.json").read_text())
            check(backend + ": corpus hash", digest(root / "corpus.json") == summary["native_predicate_trace"]["corpus_sha256"])
            for case in corpus["cases"]:
                for group in ("inputs", "expected"):
                    check(backend + ": " + case["id"] + " " + group,
                          all(digest(root / group / name) == sha for name, sha in case[group].items()))
                check(backend + ": " + case["id"] + " actual",
                      all((root / "actual" / name).read_bytes() == (root / "expected" / name).read_bytes()
                          for name in case["expected"]))
            run = next(c for c in summary["commands"] if c["label"] == "predicate_trace_run")
            raw = (directory / run["log"]).read_text(errors="replace")
            replay = analyze(raw, corpus, backend)
            saved = json.loads((root / "trace_analysis.json").read_text())
            check(backend + ": replay native trace", replay["status"] == "PASS" and replay["cases"] == saved["cases"])
            injection = (root / "injected_fault.log").read_text()
            marker = "CAPTURED " + next(c["id"] for c in corpus["cases"] if c["label"] == "all_false") + " "
            negative = analyze(raw.replace(marker, injection + marker, 1), corpus, backend)
            check(backend + ": reject injected read", negative["status"] == "FAIL")
            kernels.append(summary["native_predicate_trace"]["kernel_sha256"])
            evidence[backend] = dict(run_id=directory.name, launches=replay["observed_launches"],
                data_lanes=sum(c["observed_data_lanes"] for c in replay["cases"]), summary_sha256=digest(directory / "summary.json"))
        check("same native kernel", len(set(kernels)) == 1, kernels)
        directory = ROOT / "results" / args.inventory
        result = json.loads((directory / "result.json").read_text(encoding="utf-8-sig"))
        inventory = json.loads((directory / "inventory.json").read_text())
        check("inventory collection", result["status"] == "PASS" and result["exit_code"] == 0)
        for name, field in (("inventory.json", "inventory_sha256"), ("inventory.stdout", "stdout_sha256"),
                            ("payload.py", "payload_sha256"), ("platform_inventory.py", "collector_sha256")):
            check("inventory integrity " + name, digest(directory / name) == result[field])
        check("inventory identity", inventory["transport_identity"]["username"] == "u280user" and inventory["nonce"] == result["nonce"])
        check("no device operations", inventory["device_query_requested"] is False and inventory["device_mutations_performed"] is False)
        check("allocation remains unconfirmed", inventory["card_allocation"] == "UNCONFIRMED")
        tools = inventory.get("tool_checks", {})
        check("tool queries completed", tools.get("status") == "PASS" and len(tools.get("commands", {})) == 4
              and all(c["status"] == "PASS" and c["exit_code"] == 0 and not c["truncated"] for c in tools.get("commands", {}).values()))
        check("license not inferred", tools.get("license_acceptance") == "NOT_RUN")
        evidence["inventory"] = dict(run_id=directory.name, result_sha256=digest(directory / "result.json"),
                                     tool_checks=inventory.get("tool_checks", {}).get("status", "NOT_RUN"))
        directory = ROOT / "results" / args.tests
        result = json.loads((directory / "result.json").read_text(encoding="utf-8-sig"))
        check("Python tests command exit", result["exit_code"] == 0)
        check("Python tests complete", "Ran 73 tests" in (directory / "tests.log").read_text(encoding="utf-8-sig"))
        evidence["tests"] = dict(run_id=directory.name, log_sha256=digest(directory / "tests.log"))
        for relative, expected in (
            ("configs/target_lock.json", "924b17abadbbda710ead2053ac0873fb0698161c983f8ff1feb9b96a16a19ffe"),
            ("configs/target_caps.json", "b48d0e940a27ff53bf0708320067c31b7560c7fc489b9ad52319b1a0adf126ec"),
            ("configs/native_smoke.json", "046ca59d289390bc1d0424fc35df0d552cc7a2f92c6c649d8c318d284c433b87")):
            check("default unchanged " + relative, digest(ROOT / relative) == expected)
    except Exception as exc:
        check("closeout exception", False, repr(exc))
    shutil.copy2(__file__, output / Path(__file__).name)
    implementation = output / "implementation"
    implementation.mkdir()
    for relative in ("scripts/native_predicate_trace.py", "scripts/rerun_native_trace.py",
                     "scripts/run_native_smoke.py", "scripts/Collect-U280Inventory.ps1",
                     "tests/test_native_predicate_trace.py"):
        shutil.copy2(ROOT / relative, implementation / Path(relative).name)
    result = dict(schema_version="ab-d6-closeout-v1", status="PASS" if all(c["status"] == "PASS" for c in checks) else "FAIL",
                  checks=checks, passed=sum(c["status"] == "PASS" for c in checks), total=len(checks), evidence=evidence,
                  finished_at=datetime.now(timezone.utc).isoformat(), argv=sys.argv,
                  scope="Evidence integrity and same-author verifier replay; not independent E acceptance or U280 operation")
    result["exit_code"] = 0 if result["status"] == "PASS" else 1
    (output / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("status", "passed", "total", "exit_code")}))
    return result["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
