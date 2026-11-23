"""Record offline gate regression and actual execution of the diagnostic in SimX."""
import argparse
import os
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "scripts"))

from check_c_v03_receipt import BINDINGS
from ptx_module import read_json, write_json
from ptx_runtime import Context
from ptx_u280_aligned import exercise_probe
from run_native_smoke import Recorder, sha256, utc_now
from run_ptx_copy import SIM_LOCK, run_stage
from u280_aligned_pair import preflight


def model(bundle, compiled, output):
    _, manifests, probe = preflight(bundle, compiled)
    ctx = Context(BINDINGS / "simx/binding.json", SIM_LOCK, run_id=output.name)
    try:
        evidence = exercise_probe(ctx, bundle, manifests, probe, output)
    finally:
        if ctx.state == "READY":
            ctx.close()
    write_json(output / "simx-probe.json", dict(status="PASS", backend="simx", workloads=evidence,
                                                  launches=sum(len(row["attempts"]) for row in evidence)))


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--bundle", required=True, type=Path)
    cli.add_argument("--compiled", required=True, type=Path)
    cli.add_argument("--output", required=True, type=Path)
    cli.add_argument("--model-worker", action="store_true")
    args = cli.parse_args()
    bundle, compiled, output = args.bundle.resolve(), args.compiled.resolve(), args.output.resolve()
    if args.model_worker:
        model(bundle, compiled, output)
        return 0
    output.mkdir(parents=True, exist_ok=False)
    argv = [sys.executable, "-B", *sys.argv]
    summary = dict(status="RUNNING", argv=argv, commands=[], started_at=utc_now(), board_execution="NOT_RUN",
                   physical_cp_vm="NOT_RUN", physical_staging="NOT_RUN", physical_pair="NOT_RUN")
    rec = Recorder(output, summary, dict(os.environ))
    try:
        run_stage(rec, "pair_preflight", [sys.executable, "-B", PROJECT / "scripts/u280_aligned_pair.py", "preflight",
                                         "--bundle", bundle, "--compiled", compiled], PROJECT)
        run_stage(rec, "runner_unittest", [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-v"],
                  PROJECT, 180)
        binding = read_json((BINDINGS / "simx/binding.json").read_bytes())
        rec.env.update(VORTEX_DRIVER="simx", LD_LIBRARY_PATH=binding["library_dir"], VORTEX_PROFILING="0")
        for name in ("XCLBIN_PATH", "XCL_EMULATION_MODE", "LD_PRELOAD", "VORTEX_CP_POLL_TIMEOUT_S"):
            rec.env.pop(name, None)
        run_stage(rec, "simx_field_probe", [*argv, "--model-worker"], PROJECT, 120)
        summary.update(status="PASS", exit_code=0, simx_probe_sha256=sha256(output / "simx-probe.json"))
    except Exception as error:
        summary.update(status="FAIL", exit_code=1, error=str(error))
    summary["finished_at"] = utc_now()
    rec.save()
    print(summary["status"], output, summary.get("error", ""))
    return summary["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
