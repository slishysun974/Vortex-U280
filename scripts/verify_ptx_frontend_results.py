"""Verify frontend run evidence metadata without repeating semantic execution."""
import argparse
import json
from pathlib import Path
import re
import sys

from run_native_smoke import PROJECT, sha256, utc_now


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,70}", args.run_id):
        parser.error("invalid run ID")
    args.output.mkdir(parents=True, exist_ok=False)
    checks = []
    def check(name, ok):
        checks.append(dict(name=name, ok=bool(ok)))
    root = PROJECT / "results" / args.run_id
    try:
        report = json.loads((root / "summary.json").read_text(encoding="utf-8"))
        check("run_passed", report["status"] == "PASS")
        check("implementation_unchanged_at_run_completion", report["implementation_unchanged"])
        for backend in ("simx", "rtlsim", "afu", "u280", "independent_acceptance"):
            check(backend + "_not_claimed", report[backend] == "NOT_RUN")
        check("all_sixteen_commands_present", len(report["commands"]) == 16)
        for command in report["commands"]:
            expected = 1 if command["label"] == "fault_eager_load_run" else 0
            check(command["label"] + "_exit", command["returncode"] == expected and not command["timed_out"])
            check(command["label"] + "_log", sha256(root / command["log"]) == command["log_sha256"])
        for name, digest in report["implementation_sha256"].items():
            check("current_source:" + name, sha256(PROJECT / name) == digest)
            check("snapshot:" + name, sha256(root / "implementation" / name) == digest)
        expected_modules = {"copy_u32": 132, "vadd_u32": 132, "affine_u32": 396, "semantics_probe": 1}
        check("expected_modules", {m["sample"]: m["cases"] for m in report["modules"]} == expected_modules)
        for module in report["modules"]:
            name = module["sample"]
            directory = root / name
            check(name + "_passed", module["status"] == "PASS" and module["passed"] == module["cases"])
            for file, key in (("corpus.json", "corpus_sha256"), ("module/manifest.json", "manifest_sha256"),
                              ("host_audit", "executable_sha256"), ("comparison.json", "comparison_sha256")):
                check(name + ":" + file, sha256(directory / file) == module[key])
            manifest = json.loads((directory / "module/manifest.json").read_text())
            check(name + "_not_loadable", manifest["loadable"] is False and manifest["image_file"] is None and manifest["backend_execution"] == "NOT_RUN")
            for file, digest in manifest["files"].items():
                check(name + ":bundle:" + file, sha256(directory / "module" / file) == digest)
            comparison = json.loads((directory / "comparison.json").read_text())
            check(name + "_trace", sha256(directory / "actual/trace.tsv") == comparison["trace_sha256"])
            check(name + "_comparison", comparison["status"] == "PASS" and comparison["corpus_unchanged"] and comparison["corpus_manifest_unchanged"] and comparison["completion_marker"])
        fault = report["fault_injection"]
        check("fault_detected", fault["status"] == "PASS" and fault["actual_exit_code"] == 1)
        check("fault_copy_hash", sha256(root / "fault_eager_load/kernel_body.hpp") == fault["mutated_header_sha256"])
        check("original_header_preserved", sha256(root / "copy_u32/module/kernel_body.hpp") == fault["original_header_sha256"])
        for name, digest in {
            "configs/target_lock.json": "924b17abadbbda710ead2053ac0873fb0698161c983f8ff1feb9b96a16a19ffe",
            "configs/target_caps.json": "b48d0e940a27ff53bf0708320067c31b7560c7fc489b9ad52319b1a0adf126ec",
            "configs/native_smoke.json": "046ca59d289390bc1d0424fc35df0d552cc7a2f92c6c649d8c318d284c433b87",
            "configs/candidates/block32-v1/target_lock.json": "9bf1ecd89852e54dd402e669becbfd0910752ffd16ad9e7a9f9b20e77b6c4649",
        }.items():
            check("pre_frontend_baseline_preserved:" + name, sha256(PROJECT / name) == digest)
    except Exception as exc:
        checks.append(dict(name="verification_exception", ok=False, error=str(exc)))
    passed = bool(checks) and all(c["ok"] for c in checks)
    result = dict(schema_version="ptx-frontend-closeout-v1", status="PASS" if passed else "FAIL", exit_code=0 if passed else 1,
                  command=[sys.executable, "-B", *sys.argv], timestamp=utc_now(), run_id=args.run_id,
                  scope="command/log/implementation/bundle/trace/summary integrity; no re-execution; raw captures compared by validation run",
                  checks=checks, passed=sum(c["ok"] for c in checks), total=len(checks), verifier_sha256=sha256(__file__))
    (args.output / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    (args.output / "verify_ptx_frontend_results.py").write_bytes(Path(__file__).read_bytes())
    print(json.dumps(dict(status=result["status"], passed=result["passed"], total=result["total"], exit_code=result["exit_code"])))
    return result["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
