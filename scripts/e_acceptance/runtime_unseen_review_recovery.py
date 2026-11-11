"""E review of recorded simulator recovery: recompute canaries from input bytes.

This reviews independently the author's recorded experiment; it is not a new run.
"""
import argparse
from pathlib import Path
import sys

from runtime_unseen_common import dump, need, read, sha

ROOT = Path(__file__).resolve().parents[2]


def verify_canary(folder, label):
    x = (folder / (label + "-input_x.bin")).read_bytes()
    z = (folder / (label + "-input_z.bin")).read_bytes()
    actual_x = (folder / (label + "-actual_x.bin")).read_bytes()
    actual_z = (folder / (label + "-actual_z.bin")).read_bytes()
    need(len(x) == len(z) == 224, "canary allocation size")
    need(actual_x == x, "canary input modified")
    # copy PTX i < 37 with pointer offset 20 bytes, preserve all remaining bytes.
    need(actual_z == z[:20] + x[20:168] + z[168:], "canary array/guard mismatch")
    return {name: sha((folder / (label + "-" + name + ".bin")).read_bytes()) for name in ("input_x", "input_z", "actual_x", "actual_z")}


def review(source):
    summary = read(source / "summary.json")
    need(summary["status"] == "PASS" and summary["exit_code"] == 0, "parent execution status")
    for command in summary["commands"]:
        need(command["returncode"] == 0 and not command["timed_out"], "failed original command")
        need(sha((source / command["log"]).read_bytes()) == command["log_sha256"], "original log changed")
    for path, digest in summary["implementation"].items():
        need(sha((source / "implementation" / path).read_bytes()) == digest, "original implementation snapshot changed")
    runtime_hash = summary["implementation"]["scripts/ptx_runtime.py"]
    need(sha((ROOT / "scripts/ptx_runtime.py").read_bytes()) == runtime_hash, "current runtime differs")
    results = []
    for receipt in summary["runs"]:
        path = ROOT / receipt["result"]
        need(sha(path.read_bytes()) == receipt["sha256"], "original result changed")
        item = read(path)
        need(item["status"] == "PASS" and item["exit_code"] == 0 and item["runtime_sha256"] == runtime_hash, "worker status/source")
        calls = [(call["name"], call["status"]) for call in item["native_calls"]]
        row = dict(backend=item["backend"], mode=item["mode"], source_result_sha256=receipt["sha256"], native_calls=len(calls))
        if item["mode"] == "timeout":
            need(calls.count(("vx_event_wait_value", 7)) == 2 and calls.count(("vx_queue_finish", 7)) == 2, "real timeout counts")
            for index, call in enumerate(calls):
                if call == ("vx_event_wait_value", 7):
                    need(calls[index:index+5] == [("vx_event_wait_value", 7), ("vx_queue_finish", 7), ("vx_queue_finish", 0), ("vx_event_wait_value", 0), ("vx_event_release", 0)], "drain/event/release order")
            drains = [cycle["result"] for cycle in item["cycles"] if cycle["label"].startswith("drain-")]
            need([cycle["generation"] for cycle in drains] == [1, 2], "drain generations")
            need(all(cycle["isolated"] and not cycle["safe_abort"] and cycle["mechanism"] == "successful-queue-and-event-drain" for cycle in drains), "drain scope")
            expected_stale = {"stale-event": "E_EVENT", "stale-buffer": "E_INVALID_BUFFER", "stale-module": "E_MODULE_CORRUPT"}
            for label, code in expected_stale.items():
                checks = [check for check in item["checks"] if check["label"] == label]
                need(len(checks) == 2 and all(check["error"]["code"] == code and check["error"]["native_status"] is None for check in checks), "stale handle rejection")
            row["canaries"] = [verify_canary(path.parent, "after-drain-%d" % cycle) for cycle in range(2)]
            need(item["diagnostic"]["device_state"] == "CLOSED", "successful close")
        elif item["mode"] == "cp-fault":
            need(calls[-1] == ("vx_event_wait_value", 6), "fault should be last native call")
            need(not any(name.endswith("release") for name, status in calls), "uncertain resources released")
            retries = [check for check in item["checks"] if check["label"].startswith("recover-retry-")]
            need(len(retries) == 3 and all(check["error"]["code"] == "E_UNAVAILABLE" for check in retries), "fault retry refusal")
            diagnostic = item["diagnostic"]
            need(diagnostic["device_state"] == "NEEDS_RECOVERY" and diagnostic["generation"] == 0 and diagnostic["device_fault"]["native_status"] == 6, "fault latch")
            need(item["in_context_recovery"] == "UNAVAILABLE (expected)", "fault recovery overclaim")
        elif item["mode"] == "canary":
            row["canaries"] = [verify_canary(path.parent, "fresh-process")]
            need(all(status == 0 for name, status in calls), "fresh process canary failure")
        results.append(row)
    need(len(results) == 9, "worker completeness")
    return dict(status="PASS", scope="independent audit of source/commands/logs/native statuses and 9 raw canaries; not independent fault reexecution", runtime_sha256=runtime_hash,
                summary_sha256=sha((source / "summary.json").read_bytes()), workers=results, raw_canary_arrays_checked=18,
                source_review="TraceNative calls real functions and preserves statuses. Sticky non-timeout fault gate precedes native recovery; timeout-only drain checks original event before resource release. Physical branch rejects before any drain.",
                limitations=["No physical fault/timeout injection, reset, DMA isolation or U280 recovery acceptance.", "Successful separate process canary demonstrates only simulator process disposal; no claim that original faulted context recovered.", "The author supplied recovery inputs/results; this evidence review is separate from E pre-frozen unseen-input execution."])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "results/c-runtime-recovery-20261111-v1")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    need(not args.out.exists(), "review output already exists")
    try:
        result, code = review(args.source), 0
    except Exception as error:
        result, code = dict(status="FAIL", error=str(error)), 1
    dump(args.out, result)
    print(result["status"], result.get("error", ""))
    return code


if __name__ == "__main__":
    sys.exit(main())
