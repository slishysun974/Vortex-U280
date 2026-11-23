"""Capture the nine Iris cases on a gated D10/D12 card. Compare after return."""
import argparse
import os
from pathlib import Path
import sys

if sys.version_info[:2] == (3, 6):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "vendor/dataclasses-0.8"))
from c_v03_board import bind, review_gate
from run_native_smoke import Recorder, sha256, utc_now
from run_ptx_copy import read_json, require


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("action", choices=["run"])
    cli.add_argument("--bundle", type=Path, required=True)
    cli.add_argument("--output", type=Path, required=True)
    cli.add_argument("--bdf", required=True)
    a = cli.parse_args()
    root, run = a.bundle.resolve(), a.output.resolve()
    run.mkdir()
    report = dict(run_id=run.name, status="RUNNING", board_execution="NOT_RUN", commands=[],
                  argv=[sys.executable,"-B",*sys.argv], started_at=utc_now())
    rec = Recorder(run, report, dict(os.environ))
    try:
        plan = read_json(root/"plan.json")
        files = {p.relative_to(root).as_posix():sha256(p) for p in root.rglob("*") if p.is_file() and p != root/"plan.json"}
        require(files == plan["files"], "Iris board kit member differs")
        report["plan_sha256"] = sha256(root/"plan.json")
        bind(root, run, a.bdf, rec)
        raw = run / "u280-xrt"
        cmd, _ = rec.command("capture", [sys.executable, "-B", root/"scripts/capture.py", "--inputs", root/"inputs",
            "--module", root/"module", "--binding", run/"binding/binding.json", "--lock", root/"target_lock.json",
            "--backend", "u280-xrt", "--output", raw], run, 900)
        if (raw/"capture.json").is_file():
            result = read_json(raw/"capture.json")
            report.update(launch_attempts=result["launch_attempts"], completed=result["completed"],
                          last_phase=result.get("current_case"), capture_error=result.get("error"))
            if result["launch_attempts"]:
                report["board_execution"] = "FAIL"
        require(cmd["returncode"] == 0 and not cmd["timed_out"], "physical capture failed")
        require(result["completed"] == plan["cases"] and result["launch_attempts"] == len(plan["cases"])
                and result["final_state"] == "CLOSED", "incomplete capture")
        report.update(status="PASS", board_execution="PASS", scope="events and readback capture",
                      gate_sha256=review_gate(run), exit_code=0)
    except Exception as error:
        report.update(status="FAIL", exit_code=1, error=str(error))
    report["finished_at"] = utc_now()
    rec.save()
    print(report["status"], report.get("error",""))
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
