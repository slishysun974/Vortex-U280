"""Independent acceptance: full frozen arrays and explicit PTX-derived ABI.

No imports from the production frontend/runtime or development oracle.
"""
import argparse
from pathlib import Path
import struct
import sys

from runtime_unseen_common import FROZEN_SHA256, corpus, dump, need, read, sha


def payload(case, bases):
    ptr = {role: bases[role] + 4 * case["offsets_words"][role] for role in ("x", "y", "z")}
    if case["semantics"] == "copy":
        return struct.pack("<QQI4x", ptr["x"], ptr["z"], case["n"])
    if case["semantics"] == "vadd":
        return struct.pack("<QQQI4x", ptr["x"], ptr["y"], ptr["z"], case["n"])
    return struct.pack("<QQQII", ptr["x"], ptr["y"], ptr["z"], case["n"], case["alpha"])


def check_case(root, case, actual):
    need(actual["id"] == case["id"] and actual["module"] == case["module"], "case identity")
    need(actual["allocation_generation"] == case["allocation_generation"], "allocation generation")
    need(actual["status"] == "CAPTURED", "not captured")
    need(actual["phases"] == dict(load="PASS", H2D="PASS", launch="PASS", wait="PASS", D2H="PASS"), "phase status")
    need(actual["grid"] == [case["grid"], 1, 1] and actual["block"] == [case["block"], 1, 1], "launch geometry")
    for key, wanted in (("before", "READY"), ("launched", "RUNNING"), ("after", "READY")):
        need(actual[key]["device_state"] == wanted and actual[key]["generation"] == 0, "state/generation " + key)
        need(actual[key].get("first_error") is None and actual[key].get("device_fault") is None, "unexpected runtime error")
    need(actual["wait"]["status"] == "COMPLETE" and actual["event_completed"] is True, "completion")
    need(actual["wait"]["event_id"] == actual["event_id"] and actual["wait"]["generation"] == 0, "event identity")
    for role in ("x", "y", "z"):
        data = (root / case["id"] / (role + ".actual.bin")).read_bytes()
        reference = case["files"][role + (".expected.bin" if role == "z" else ".input.bin")]
        need(sha(data) == reference, "full array/guard mismatch " + case["id"] + "/" + role)
        need(len(data) == case["allocation_words"] * 4, "array length")
    wanted_payload = payload(case, actual["bases"])
    for name in ("params.plan.bin", "params.before_mutation.bin", "params.after_mutation.bin"):
        need((root / case["id"] / name).read_bytes() == wanted_payload, "ABI/padding/snapshot mismatch " + case["id"] + "/" + name)
    for name, digest in actual["files"].items():
        need(sha((root / case["id"] / name).read_bytes()) == digest, "capture hash mismatch")


def check(corpus_dir, run_dir):
    manifest = corpus(corpus_dir)
    actual = read(run_dir / "capture.json")
    need(actual["manifest_sha256"] == FROZEN_SHA256, "capture corpus mismatch")
    need(actual["status"] == "COMPLETE" and actual["exit_code"] == 0, "incomplete run")
    need(actual["context_creations"] == 1 and actual["final_state"] == "CLOSED", "context lifecycle")
    need(actual["module_loads"] == actual["module_unloads"] == 41, "module switching count")
    need(len(actual["cases"]) == len(manifest["cases"]) == 48, "case completeness")
    need([a["generation"] for a in actual["allocations"]] == [0, 1], "buffer reuse/reallocation")
    need(actual["caps_initial"]["device_state"] == "READY" and actual["caps_before_close"]["device_state"] == "READY", "initial/final state")
    need(actual["implementation_after"] == actual["implementation"], "production changed during run")
    need(set(actual["modules"]) == set(manifest["sources"]), "module completeness")
    for name, source in manifest["sources"].items():
        need(actual["modules"][name]["source_sha256"] == source["sha256"], "module source identity")
    for name, digest in actual["implementation"].items():
        need(sha((run_dir / "implementation" / name).read_bytes()) == digest, "runtime source identity")
    for index, (case, capture) in enumerate(zip(manifest["cases"], actual["cases"])):
        need(capture["event_id"] == index + 1, "event sequence")
        need(capture["queue_native"] == actual["queue_native"], "queue changed")
        need(capture["bases"] == actual["allocations"][case["allocation_generation"]]["bases"], "buffer allocation changed")
        need(capture["wait"]["backend"] == actual["backend"], "backend changed")
        check_case(run_dir, case, capture)
    return dict(status="PASS", scope="independent E frozen unseen C API functional acceptance", backend=actual["backend"],
                cases=48, full_arrays=144, payload_captures=144, logical_parameter_sets=48,
                context_creations=1, module_loads=41, allocation_generations=2,
                manifest_sha256=FROZEN_SHA256, capture_sha256=sha((run_dir / "capture.json").read_bytes()),
                implementation=actual["implementation"], limitations=manifest["limits"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", required=True, type=Path)
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    need(not args.out.exists(), "acceptance output already exists")
    try:
        result = check(args.corpus, args.run)
        code = 0
    except Exception as error:
        result, code = dict(status="FAIL", error=str(error)), 1
    dump(args.out, result)
    print(result["status"], result.get("cases", 0), result.get("error", ""))
    return code


if __name__ == "__main__":
    sys.exit(main())
