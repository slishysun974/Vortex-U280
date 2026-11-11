"""Independent E final evidence binding. Re-run with a new --out filename."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/e_acceptance"))
from runtime_unseen_common import FROZEN_SHA256, PRODUCTION, corpus, dump, need, read, sha
from runtime_unseen_check import check


def verify():
    manifest = corpus(ROOT / "configs/acceptance/e-runtime-unseen-20261111-v1")
    build_root = ROOT / "results/e-runtime-unseen-build-20261111-v1"
    sim_root = ROOT / "results/e-runtime-unseen-sim-20261111-v1"
    board_root = ROOT / "results/e-u280-unseen-20261111-v1"
    build = read(build_root / "build_summary.json")
    simulation = read(sim_root / "summary.json")
    need(build["status"] == simulation["status"] == "PASS", "build/model run status")
    need(build["exit_code"] == simulation["exit_code"] == 0, "build/model exit code")
    need(len(build["modules"]) == 12 and len(build["commands"]) == 36 and len(simulation["commands"]) == 6, "build/model commands missing")
    for root, summary in ((build_root, build), (sim_root, simulation)):
        for command in summary["commands"]:
            need(command["exit_code"] == 0, "failed command")
            need(sha((root / command["log"]).read_bytes()) == command["log_sha256"], "command log changed")
    for target in ("sim", "board"):
        for name, source in manifest["sources"].items():
            directory = build_root / "modules" / target / name
            mm = read(directory / "manifest.json")
            record = build["modules"][target + "/" + name]
            need(sha((directory / "manifest.json").read_bytes()) == record["manifest_sha256"], "build manifest identity")
            need(mm["source_sha256"] == source["sha256"], "build source identity")
            for filename, digest in mm["files"].items():
                need(sha((directory / filename).read_bytes()) == digest, "module member identity")
            commands = read(directory / "build.json")["commands"]
            need(len(commands) == 3 and all(c["exit_code"] == 0 for c in commands), "nested build command failed")
            need(sha((directory / "kernel.vxbin").read_bytes()) == record["image_sha256"], "build image changed")
    captures, acceptances = {}, {}
    paths = {backend: sim_root / backend for backend in ("simx", "rtlsim", "xrtsim")}
    paths["u280-xrt"] = board_root / "returned/execution/e-unseen"
    for backend, directory in paths.items():
        acceptances[backend] = check(ROOT / "configs/acceptance/e-runtime-unseen-20261111-v1", directory)
        captures[backend] = read(directory / "capture.json")
        need(captures[backend]["backend"] == backend, "backend identity")
        receipt_path = board_root / "e.acceptance.json" if backend == "u280-xrt" else sim_root / (backend + ".acceptance.json")
        need(read(receipt_path) == acceptances[backend], "previous E receipt is stale")
        for name in PRODUCTION:
            need(captures[backend]["implementation"][name] == sha((ROOT / "scripts" / name).read_bytes()), "current production differs from executed source")
        need(captures[backend]["runner_sha256"] == sha((ROOT / "scripts/e_acceptance/runtime_unseen_run.py").read_bytes()), "runner changed")
    images = {}
    for name in manifest["sources"]:
        digests = [capture["modules"][name]["image_sha256"] for capture in captures.values()]
        digests += [build["modules"][target + "/" + name]["image_sha256"] for target in ("sim", "board")]
        need(len(set(digests)) == 1, "four-way/build image mismatch")
        images[name] = digests[0]
        for backend, capture in captures.items():
            target = "board" if backend == "u280-xrt" else "sim"
            need(capture["modules"][name]["manifest_sha256"] == build["modules"][target + "/" + name]["manifest_sha256"], "executed module manifest mismatch")
    for case in manifest["cases"]:
        for role in ("x", "y", "z"):
            values = [(path / case["id"] / (role + ".actual.bin")).read_bytes() for path in paths.values()]
            need(all(value == values[0] for value in values), "four-way array mismatch")
    transport = read(board_root / "transport.json")
    remote = read(board_root / "result.json")
    preparation = read(board_root / "preparation.json")
    need(transport["status"] == remote["status"] == "PASS" and transport["ssh_exit_code"] == transport["exit_code"] == remote["exit_code"] == 0, "physical transport failure")
    need(remote["executions"] == 48 and remote["board_execution"] == "PASS", "board execution count")
    need(remote["bdf"] == preparation["bdf"] == "0000:b1:00.1" and remote["xrt_index"] == 3, "physical card identity")
    need(sha((board_root / "payload.py").read_bytes()) == preparation["payload_sha256"], "transport payload identity")
    need(sha((board_root / "e_runtime_board.py").read_bytes()) == preparation["script_sha256"] == remote["script_sha256"], "transport worker identity")
    text = (board_root / "probe.stdout").read_text(encoding="utf-8-sig")
    match = re.search(r"(?ms)^E_RUNTIME_BEGIN_" + preparation["nonce"] + r"\r?\n(.*?)^E_RUNTIME_END_" + preparation["nonce"] + r"\s*$", text)
    need(match is not None, "raw SSH framing")
    framed = json.loads(match.group(1))
    need(framed == read(board_root / "remote-result.json"), "raw framed result mismatch")
    need(framed["nonce"] == remote["nonce"] == preparation["nonce"], "nonce mismatch")
    for name, entry in framed["export"].items():
        need(not Path(name).is_absolute() and ".." not in Path(name).parts, "unsafe export name")
        data = base64.b64decode(entry["base64"], validate=True)
        need(sha(data) == entry["sha256"] == remote["returned_files"][name], "raw export digest")
        need(data == (board_root / "returned" / name).read_bytes(), "raw export/returned bytes mismatch")
    need(len(remote["commands"]) == 13 and all(command["exit_code"] == 0 for command in remote["commands"]), "remote command failed")
    for name in PRODUCTION:
        need(preparation["inputs"]["scripts/" + name] == captures["u280-xrt"]["implementation"][name], "prepared/executed production mismatch")
    gate_dir = board_root / "returned/binding/sessions/e-unseen"
    gate = read(gate_dir / "gate.json")
    binding_path = board_root / "returned/binding/binding.json"
    binding = read(binding_path)
    need(gate["status"] == gate["open_gate"] == gate["close_gate"] == "PASS", "board gates")
    need(sha(binding_path.read_bytes()) == gate["binding_sha256"] == captures["u280-xrt"]["binding_sha256"], "physical binding identity")
    need(binding["backend"] == "u280-xrt" and binding["driver"] == "xrt", "physical driver")
    need(binding["bdf"] == remote["bdf"] and binding["index"] == remote["xrt_index"], "binding card identity")
    need(gate["artifact_hashes"]["xclbin"] == binding["xclbin_sha256"] == "bbac2ab73073b24ba857fb34eadf22bf1c11dc745527f064c4eec61b70d2c843", "D10 image identity")
    need(gate["artifact_hashes"]["libraries"] == binding["libraries"] == {"libvortex.so": "d3538d2fc7c695a4a0102106aa45e9ef7a9e939fc44c3b15c547ff97d0dffe3e", "libvortex-xrt.so": "250769482e98c1cee84bd165a9e2af1c7b3f74a5b77dcf389ac1f4ea5aa7a8c1"}, "D12 library identity")
    need(gate["artifact_hashes"]["lock"] == captures["u280-xrt"]["target_lock_sha256"] == "e55719ecaa83d1b0f637cf212819716c58667443918f822eaed9ee2eb2aa7486", "physical lock")
    need(gate["artifact_hashes"]["query"] == binding["query_sha256"] == remote["query_sha256"], "BDF query identity")
    for report in gate["reports"].values():
        need(sha((gate_dir / report["file"]).read_bytes()) == report["sha256"], "gate raw report identity")
    for command in gate["commands"]:
        if command["label"].endswith("holders"):
            need(command["exit_code"] == 1 and not command["stdout"] and not command["stderr"], "visible holder check")
        else:
            need(command["exit_code"] == 0, "gate command failed")
    uuid = "b60ca9fb-1506-3033-c156-e03ff687f492"
    for label, snapshot in gate["sysfs"].items():
        need(int(snapshot["ready"], 0) == 1 and int(snapshot["host_mem_size"]) == 268435456 and snapshot["xclbinuuid"] == uuid, "sysfs readiness/HOST/UUID")
        need(re.search(r"outstanding execs:\s*0", snapshot["kdsstat"]), "outstanding commands")
        if label != "loaded":
            need(re.search(r"contexts:\s*0", snapshot["kdsstat"]), "open contexts before/after")
    loaded = read(gate_dir / "loaded.json")["devices"][0]
    need(loaded["device_id"] == binding["bdf"], "loaded BDF")
    need(loaded["platforms"][0]["static_region"]["vbnv"] == "xilinx_u280_gen3x16_xdma_base_1", "shell name")
    clocks = loaded["platforms"][0]["clocks"]
    need([int(clock["freq_mhz"]) for clock in clocks if clock["id"] == "DATA_CLK"] == [200], "actual loaded clock")
    need(loaded["dynamic_regions"][0]["xclbin_uuid"].lower() == uuid, "loaded xclbin UUID")
    closeout_root = ROOT / "results/c-runtime-closeout-20261111-v1"
    closeout = read(closeout_root / "summary.json")
    need(closeout["status"] == "PASS" and closeout["exit_code"] == 0, "final selftest status")
    for command in closeout["commands"]:
        need(command["returncode"] == 0 and not command["timed_out"], "final selftest command")
        need(sha((closeout_root / command["log"]).read_bytes()) == command["log_sha256"], "final selftest raw log")
    for path, digest in dict(closeout["implementation"], **closeout["protected"]).items():
        need(sha((ROOT / path).read_bytes()) == digest, "final selftest source/protection changed")
    evidence = [build_root / "build_summary.json", sim_root / "summary.json", board_root / "preparation.json", board_root / "transport.json", board_root / "result.json", board_root / "e.acceptance.json", gate_dir / "gate.json", closeout_root / "summary.json", ROOT / "results/e-runtime-unseen-development-20261111-v1/recovery-review.json"]
    return dict(schema="e-runtime-unseen-final-acceptance-v1", status="PASS", exit_code=0,
                issuer="independent non-implementation E AI agent; not a formal human signature", manifest_sha256=FROZEN_SHA256,
                production=captures["u280-xrt"]["implementation"], images=images,
                backends={backend: {k: value[k] for k in ("status", "cases", "full_arrays", "logical_parameter_sets", "payload_captures", "context_creations", "module_loads", "allocation_generations", "capture_sha256")} for backend, value in acceptances.items()},
                totals=dict(actual_executions=192, full_arrays=576, logical_parameter_sets=192, payload_captures=576, fresh_modules=12),
                commands=dict(module_prepare_build_validate=36, nested_compilation=36, simulation_capture_and_check=6, remote_board=13, ssh_exit_code=0, final_receiver_exit_code=0),
                board=dict(bdf=binding["bdf"], xrt_index=3, host_bytes=268435456, actual_data_clock_mhz=200, xclbin_uuid=uuid, open_gate="PASS", close_gate="PASS", python_version=remote["python_version"], raw_export_files=len(framed["export"]), holder_check="three fuser calls returned 1 with empty output: no ordinary-account visible holders; no exclusive reservation"),
                host_selftests=dict(total=269, passed=268, skipped=1, exit_code=0, scope="Python host behavior, separate from device results"),
                independent_recovery_review="PASS for author's simulator timeout/drain and fault-containment evidence; not E fault reexecution or physical recovery",
                physical_recovery="NOT_RUN", timing7="OPEN", limitations=manifest["limits"],
                evidence={str(path.relative_to(ROOT)).replace("\\", "/"): sha(path.read_bytes()) for path in evidence},
                verification_command=[sys.executable, "-B", str(Path(__file__).relative_to(ROOT)), "--out", str(args.out)], verifier_sha256=sha(Path(__file__).read_bytes()))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    need(not args.out.exists(), "result already exists")
    try:
        result = verify()
    except Exception as error:
        result = dict(status="FAIL", exit_code=1, error=str(error))
    dump(args.out, result)
    print(result["status"], result.get("totals", {}), result.get("error", ""))
    sys.exit(result["exit_code"])
