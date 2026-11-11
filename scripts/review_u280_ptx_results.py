"""Review a three-case PTX suite or 15-case regression against raw captures."""
import argparse
import base64
import datetime
import json
from pathlib import Path
import shutil
import sys

from ptx_frontend import pack_arguments
from run_ptx_copy import CORPUS_HASHES
from u280_board_smoke import PTX_REGRESSION, PTX_SUITE, RUNTIME_SHAS, XCLBIN_SHA, XCLBIN_UUID, idle, require, sha

ROOT = Path(__file__).resolve().parents[1]
AFU = ROOT / "results/ptx-noxrt-afu-20261110-v1"
FROZEN = ROOT / "results/ptx-frontend-host-20261108-v3"


def read(path):
    return json.loads(path.read_bytes())


def verify(board_dir, result):
    board, transport, prep = [read(board_dir / name) for name in ("result.json", "transport.json", "preparation.json")]
    mode = prep["mode"]
    require(mode in ("ptx-suite", "ptx-regression", "ptx-boundaries"), "unsupported review mode")
    boundaries = mode == 'ptx-boundaries'
    plan = [tuple(item) for item in prep['boundary_plan']] if boundaries else (PTX_REGRESSION if mode == "ptx-regression" else PTX_SUITE)
    keys = [entry + "-" + case if mode != "ptx-suite" else entry for _, entry, case in plan]
    require(transport["ssh_exit_code"] == transport["exit_code"] == 0 and transport["status"] == board["status"] == "PASS"
            and board["passed_cases"] == board["planned_cases"] == len(prep["jobs"]) == len(plan)
            and set(board["jobs"]) == set(keys), "incomplete or failed board batch")
    require(board["run_id"] == transport["run_id"] == prep["run_id"] == board_dir.name
            and board["mode"] == transport["mode"] == mode and board["nonce"] == prep["nonce"]
            and board["script_sha256"] == prep["script_sha256"] == sha((board_dir / "u280_board_smoke.py").read_bytes())
            and prep["payload_sha256"] == sha((board_dir / "payload.py").read_bytes()), "run identity mismatch")
    require([(job["ptx"]["source_run"], job["ptx"]["entry"], job["ptx"]["case"]["id"]) for job in prep["jobs"]]
            == list(plan), "case plan changed")
    afu_root = ROOT / 'results' / prep['source_run'] if boundaries else AFU
    afu = read(afu_root / "summary.json")
    require(afu["status"] == "PASS", "NOXRT run did not pass")
    if boundaries:
        from verify_ab_closeout import check_boundaries
        check_boundaries(afu_root)
        require(sha((afu_root / 'summary.json').read_bytes()) == prep['source_summary_sha256'] and
                list(plan) == [(prep['source_run'], e, c['id']) for e in ('copy_u32', 'vadd_u32', 'affine_u32')
                              for c in afu['kernels'][e]['cases']], 'boundary source/plan changed')
    bdf = board["selected_bdf"]
    result.update(selected_bdf=bdf, mode=mode, evidence_sha256={
        str(path.relative_to(ROOT)): sha(path.read_bytes()) for path in
        [board_dir / name for name in ("result.json", "transport.json", "preparation.json")] + [afu_root / "summary.json"]})
    for key, spec in zip(keys, prep["jobs"]):
        contract, job = spec["ptx"], board["jobs"][key]
        entry, case = contract["entry"], contract["case"]
        case_id = case["id"]
        require(all(job[phase] == "PASS" for phase in
                    ("status", "host_compile", "card_preflight", "device_open", "readback", "board_execution"))
                and job["selected_bdf"] == bdf and job["captured_cases"] == [case_id]
                and job["case_results"] == {case_id: "PASS"} and not job["unexpected_outputs"], "board gate failed: " + key)
        require(job["host_capacity"][bdf]["bytes"] >= 256 * 1024 * 1024
                and job["sysfs"]["loaded"]["xclbinuuid"] == XCLBIN_UUID
                and int(job["clock_readback"]["freq_mhz"]) == 200
                and idle(job["sysfs"]["after"]["kdsstat"]), "HOST/UUID/clock/idle mismatch: " + key)
        artifacts = {Path(path).name: digest for path, digest in job["artifact_sha256"].items()}
        require(artifacts == dict(RUNTIME_SHAS, **{"vortex_afu.xclbin": XCLBIN_SHA}), "runtime/xclbin mismatch")
        for label in ("host_compile", entry, "loaded"):
            commands = [cmd for cmd in job["commands"] if cmd["label"] == label]
            require(len(commands) == 1 and commands[0]["exit_code"] == 0 and not commands[0].get("timed_out"),
                    "board command failed: " + key + "/" + label)
        source = ROOT / "results" / contract["source_run"]
        module = source / ("module" if entry == "copy_u32" and not boundaries else entry)
        case_dir = (source if entry == "copy_u32" and not boundaries else module) / case_id
        ir = read(module / "frontend/ir.json")
        corpus_raw = (FROZEN / entry / "corpus.json").read_bytes()
        corpus = json.loads(corpus_raw)
        require(sha(corpus_raw) == CORPUS_HASHES[entry] == contract["corpus_sha256"]
                and case in corpus["cases"], "frozen corpus mismatch")
        require(sha((module / "kernel.vxbin").read_bytes()) == contract["image_sha256"], "device images differ")
        if boundaries:
            require(afu['kernels'][entry]['image_sha256'] == contract['image_sha256'] and
                    any(c['id'] == case_id and c['status'] == 'PASS' for c in afu['kernels'][entry]['backends']['xrtsim']),
                    'boundary AFU image/case mismatch')
            noxrt_output = case_dir / 'xrtsim/actual'
        else:
            require(contract['image_sha256'] == sha((AFU / entry / case_id / 'kernel.vxbin').read_bytes()), 'AFU image mismatch')
            afu_cases = [item for item in afu["cases"] if item["entry"] == entry and item["case"] == case]
            require(len(afu_cases) == 1 and afu_cases[0]["image_sha256"] == contract["image_sha256"]
                    and afu_cases[0]["status"] == "PASS", "AFU image/case mismatch")
            for suffix in ("compile", "run"):
                commands = [cmd for cmd in afu["commands"] if cmd["label"] == entry + "_" + case_id + "_" + suffix]
                require(len(commands) == 1 and commands[0]["returncode"] == 0 and not commands[0]["timed_out"]
                        and sha((AFU / commands[0]["log"]).read_bytes()) == commands[0]["log_sha256"], "AFU command/log mismatch")
            noxrt_output = AFU / entry / case_id / 'output'
        captures = dict(simx=case_dir / "simx/actual", rtlsim=case_dir / "rtlsim/actual", noxrt=noxrt_output)
        files = {}
        for name, item in job["outputs"].items():
            raw = base64.b64decode(item["base64"], validate=True)
            require(raw == (FROZEN / entry / "expected" / name).read_bytes()
                    and sha(raw) == item["sha256"] == spec["expected"][name] == corpus["files"]["expected/" + name]
                    and all(raw == (folder / name).read_bytes() for folder in captures.values()), "captured bytes differ: " + key + "/" + name)
            files[name] = dict(sha256=sha(raw), bytes=len(raw), four_way_match=True)
        require(set(files) == set(spec["expected"]), "output set mismatch")
        launch = job["ptx_launch"]
        payload = base64.b64decode(launch["payload_base64"], validate=True)
        require(launch["status"] == "PASS" and launch["entry_pc"] == contract["runtime_entry_pc"]
                and launch["image_sha256"] == contract["image_sha256"] and sha(payload) == launch["payload_sha256"]
                and payload == pack_arguments(ir, tuple(launch["args"][p["name"]] for p in ir["params"])), "board parameter ABI mismatch")
        params = {name: payload == (folder / (case_id + "_params.bin")).read_bytes() for name, folder in captures.items()}
        require(all(params.values()), "four-way parameter bytes differ: " + key)
        result["cases"][key] = dict(case=case, image_sha256=contract["image_sha256"],
                                   params_sha256=sha(payload), params_match=params, outputs=files)
    result.update(passed_cases=len(result["cases"]), array_files=sum(len(case["outputs"]) for case in result["cases"].values()),
                  parameter_files=len(result["cases"]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board-run", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(Path(args.board_run).name == args.board_run, "board run must be a directory name")
    args.output.mkdir(parents=True, exist_ok=False)
    shutil.copy2(__file__, args.output / Path(__file__).name)
    result = dict(schema_version="u280-ptx-four-way-review-v1", status="FAIL", cases={}, command=sys.argv,
                  started_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  scope="Archived U280/SimX/processor RTL/NOXRT raw captures; author review, not independent E acceptance")
    try:
        verify(ROOT / "results" / args.board_run, result)
        result["status"] = "PASS"
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        result["error"] = str(exc)
    result["exit_code"] = int(result["status"] != "PASS")
    (args.output / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(result["status"], len(result["cases"]), result.get("error", ""))
    return result["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
