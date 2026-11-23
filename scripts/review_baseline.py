"""Recheck the 2026-11-23 baseline using archived data from a public checkout."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
IRIS = ROOT / "experiments/iris-u280-perf"
sys.path.insert(0, str(ROOT / "scripts/e_acceptance"))
sys.path.insert(0, str(IRIS))

from analyze import check, read, sha
from comparison import compare
from paired import input_plan, verify_samples
from ptx_u280 import RUNTIME_SHAS, XCLBIN_SHA
from runtime_unseen_check import check as check_operators


def board_return(run_id):
    return RESULTS / run_id / "returned" / run_id


def review_pair(corpus):
    run_id = "iris-board-pair-20261123-v2"
    returned = board_return(run_id)
    raw = returned / "u280-xrt"
    result = read(RESULTS / run_id / "result.json")
    check(result["run_id"] == run_id and result["status"] == "PASS"
          and result["exit_code"] == result["worker_exit_code"] == 0, "board receipt differs")
    expected_files = {name: digest for name, digest in result["returned_files"].items() if name.startswith("u280-xrt/")}
    actual_files = {p.relative_to(returned).as_posix(): sha(p) for p in raw.rglob("*") if p.is_file()}
    check(expected_files == actual_files, "paired capture file set or hash differs")

    gate = read(returned / "binding/sessions" / run_id / "gate.json")
    capture = read(raw / "capture.json")
    native = RESULTS / "iris-native-build-20261123-v1/board"
    ptx = RESULTS / "iris-build-20261123-v1/modules/board"
    proof = read(native / "native.json")
    artifacts = gate["artifact_hashes"]
    check(gate["run_id"] == run_id and gate["status"] == gate["open_gate"] == gate["close_gate"] == "PASS"
          and artifacts["libraries"] == RUNTIME_SHAS and artifacts["xclbin"] == XCLBIN_SHA,
          "board identity differs")
    lock = ROOT / "configs/candidates/u280-hbm32-v1/target_lock.json"
    check(sha(lock) == artifacts["lock"] == proof["lock_sha256"] == capture["lock_sha256"],
          "board target lock differs")
    check(sha(IRIS / "vortex_kernel.cpp") == proof["native_source_sha256"]
          and sha(native / "kernel.dump") == proof["native_disassembly_sha256"]
          and sha(ptx / "manifest.json") == proof["ptx_manifest_sha256"] == capture["ptx_manifest_sha256"]
          and sha(ROOT / "ptx/samples/iris_nearest_centroid_u32.ptx") == read(ptx / "manifest.json")["source_sha256"],
          "Iris source or build identity differs")
    images = {"native": sha(native / "kernel.vxbin"), "ptx": sha(ptx / "kernel.vxbin")}
    check(images == capture["images"] and all(proof[key + "_image_sha256"] == value for key, value in images.items()),
          "measured images differ")
    report = verify_samples(corpus, raw, input_plan(corpus, True), "u280-xrt")
    check(capture["backend"] == report["backend"] and capture["final_state"] == "CLOSED"
          and capture["launch_attempts"] == report["launches"], "incomplete Iris capture")
    receipt = read(RESULTS / "iris-pair-review-20261123-v1/receipt.json")
    check(all(receipt[key] == value for key, value in report.items()) and receipt["image_sha256"] == images
          and gate["clock_readback"]["id"] == "DATA_CLK" and int(gate["clock_readback"]["freq_mhz"]) == receipt["clock_mhz"] == 200,
          "recomputed paired measurements differ from the archived receipt")
    return report


def main():
    frozen = ROOT / "configs/acceptance/e-runtime-unseen-20261111-v1"
    models = RESULTS / "e-runtime-unseen-sim-20261111-v1"
    runs = {backend: models / backend for backend in ("simx", "rtlsim", "xrtsim")}
    runs["u280-xrt"] = RESULTS / "e-u280-unseen-20261111-v1/returned/execution/e-unseen"
    counts = {}
    for backend, directory in runs.items():
        review = check_operators(frozen, directory)
        check(review["backend"] == backend, "unexpected backend: " + backend)
        counts[backend] = review["cases"]

    corpus = RESULTS / "iris-perf-freeze-20261123-v1/corpus"
    pair = review_pair(corpus)
    performance = compare(corpus, board_return("iris-board-perf-20261123-v2") / "u280-xrt",
                          RESULTS / "iris-perf-cpu-20261123-v1")
    check(performance == read(RESULTS / "iris-perf-comparison-20261123-v1/comparison.json"),
          "recomputed CPU and board statistics differ")
    return {"status": "PASS", "scope": "archived measurements", "operator_cases": counts,
            "iris_pair_launches": pair["launches"], "iris_pair_counter_reads": pair["counter_reads"],
            "iris_timed_pairs": pair["timed_pairs"], "iris_sizes": sorted(map(int, pair["groups"])),
            "iris_65533_cycle_ratio": pair["groups"]["65533"]["cycles"]["ptx_over_native"],
            "iris_65533_warp_instruction_ratio": pair["groups"]["65533"]["instret"]["ptx_over_native"],
            "iris_five_fold_correct": performance["folds"]["correct"],
            "iris_five_fold_total": performance["folds"]["total"]}


if __name__ == "__main__":
    print(json.dumps(main(), indent=2))
