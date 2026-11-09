"""Verify D12 host/runtime evidence; board acceptance remains separate."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--runtime-run", required=True)
    args = parser.parse_args()
    if any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", s) for s in (args.run_id, args.runtime_run)):
        parser.error("unsafe run id")
    output = ROOT / "results" / args.run_id
    output.mkdir(exist_ok=False)
    result = dict(schema_version="ab-d12-closeout-v1", status="RUNNING", argv=sys.argv, checks=[],
        scope="host runtime build and evidence consistency; same author validation",
        board_readiness="BLOCKED", board_execution="NOT_RUN", ptx_device="NOT_RUN",
        processor_rtl_rerun="NOT_RUN", afu_model_rerun="NOT_RUN", independent_acceptance="NOT_RUN")

    def check(label, condition):
        result["checks"].append(dict(check=label, status="PASS" if condition else "FAIL"))
        if not condition:
            raise ValueError(label)

    try:
        run = ROOT / "results" / args.runtime_run
        transport, probe, prep = (read(run / name) for name in ("transport.json", "probe.json", "preparation.json"))
        check("SSH and unpack", transport["ssh_exit_code"] == transport["exit_code"] == 0)
        check("real server runtime and inspection", probe["runtime_status"] == probe["inspection_status"] == "PASS")
        check("payload integrity", sha(run / "payload.py") == prep["payload_sha256"])
        check("request integrity", sha(run / "bundle.json") == prep["bundle_sha256"])
        check("remote collector integrity", sha(run / "u280_remote_runtime.py") == prep["remote_probe_sha256"] == probe["remote_probe_sha256"])
        check("raw SSH stdout integrity", sha(run / "probe.stdout") == probe["raw_stdout_sha256"])
        for name, item in probe["files"].items():
            check("returned " + name, "local_path" in item and sha(run / item["local_path"]) == item["sha256"] and
                  (run / item["local_path"]).stat().st_size == item["bytes"])
        built = probe["runtime_result"]
        check("both libraries", {a["path"] for a in built["artifacts"]} == {"lib/libvortex.so", "lib/libvortex-xrt.so"})
        check("all six commands exited zero", len(built["commands"]) == 6 and all(c["exit_code"] == 0 and not c["timed_out"] for c in built["commands"]))
        check("two CPUs", len(built["cpu_affinity"]) == 2)
        check("no device load or configuration", all(probe[k] == "NOT_RUN" for k in ("board_load", "board_execution", "host_configuration")))
        package = ROOT / "results/u280-runtime-gcc9-prepare-20261109-v2"
        package_result = read(package / "result.json")
        check("candidate package", sha(package / "u280-runtime200-input.tar.gz") == package_result["package"]["sha256"] == probe["package_sha256"])
        check("runtime binding", built["binding"] == read(package / "binding.json"))
        original = ROOT / "results/u280-runtime-prepare-20261109-v1"
        check("original D11 input preserved", sha(original / "u280-runtime200-input.tar.gz") == "9976e187005d38005c1733d0bc5e9f337450109252bb908662fc9c4839c79b84")
        check("identical hardware defines", (package / "resolved.cflags").read_bytes() == (original / "resolved.cflags").read_bytes())
        old, new = ({i["path"]: i["sha256"] for i in read(p / "manifest.json")} for p in (original, package))
        changes = {k for k in set(old) | set(new) if old.get(k) != new.get(k)}
        check("exact patch inventory", changes == {"source/sw/runtime/common/vm.cpp", "source/sw/runtime/common/vm.h", "build/sw/runtime/common.mk", "binding.json"})
        lock = ROOT / "configs/target_lock.json"
        locked = read(lock)
        check("root lock digest retained", sha(lock) == (ROOT / "configs/target_lock.sha256").read_text().split()[0])
        candidate_lock = ROOT / "configs/candidates/u280-hbm32-v1/target_lock.json"
        check("FPGA candidate lock unchanged", sha(candidate_lock) == built["binding"]["target_lock_sha256"])
        inventory = ROOT / locked["evidence"] / "source_manifest.json"
        check("fixed source manifest", sha(inventory) == locked["source_manifest_sha256"])
        entries = read(inventory)
        mismatches = [i["path"] for i in entries if sha(ROOT / "upstream/vortex" / i["path"]) != i["sha256"]]
        check("3329 fixed source files unchanged", len(entries) == 3329 and not mismatches)
        result["source_files_verified"] = len(entries)
        result["root_lock_sha256"] = sha(lock)
        result["root_caps_sha256"] = sha(ROOT / "configs/target_caps.json")
        tests = ROOT / "results/ab-d12-script-checks-20261109-v3"
        tested = read(tests / "result.json")
        check("Python self-tests", tested["status"] == "PASS" and tested["exit_code"] == 0)
        for name, digest in tested["files"].items():
            check("test log " + name, sha(tests / name) == digest)
        review = ROOT / "results/u280-timing-review-20261109-v2/result.json"
        timing = read(review)
        check("warning review retains all nine open items", timing["status"] == "PASS" and len(timing["critical_warnings"]) == 9 and all(w["disposition"] == "OPEN" for w in timing["critical_warnings"]))
        check("rule tables are nonempty and complete", sum(r["count"] for r in timing["methodology_rules"]) == 100 and
              sum(r["count"] for r in timing["drc_rules"]) == 343)
        result.update(status="PASS", server_runtime="PASS", runtime_run=args.runtime_run,
            runtime_artifacts=built["artifacts"], warning_review_sha256=sha(review),
            remaining=["HOST configuration permission and allocation", "platform clock/constraint warning closure",
                       "controlled xclbin load and actual 200 MHz observation", "native board regression", "PTX device integration and independent acceptance"])
    except Exception as exc:
        result.update(status="FAIL", error=repr(exc))
    result["exit_code"] = 0 if result["status"] == "PASS" else 1
    shutil.copy2(__file__, output / Path(__file__).name)
    implementation = output / "implementation"
    implementation.mkdir()
    for name in ("prepare_u280_runtime_remote.py", "u280_remote_runtime.py", "prepare_u280_runtime_gcc9.py",
                 "Invoke-U280Runtime.ps1", "review_u280_timing.py"):
        shutil.copy2(ROOT / "scripts" / name, implementation / name)
    for path in (ROOT / "tests").glob("test_u280_*runtime*.py"):
        shutil.copy2(path, implementation / path.name)
    shutil.copy2(ROOT / "tests/test_u280_timing_review.py", implementation / "test_u280_timing_review.py")
    (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(dict(status=result["status"], checks=len(result["checks"]), error=result.get("error"), board_readiness=result["board_readiness"])))
    return result["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
