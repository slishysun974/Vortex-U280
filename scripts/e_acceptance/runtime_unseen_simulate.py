"""Run three actual backends in separate processes and independently accept captures."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import time

from runtime_unseen_common import PRODUCTION, dump, need, read, sha

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--build-run", default="e-runtime-unseen-build-20261111-v1")
    args = parser.parse_args()
    output = ROOT / "results" / args.run_id
    output.mkdir(parents=True, exist_ok=False)
    (output / "logs").mkdir()
    build = ROOT / "results" / args.build_run
    need(read(build / "build_summary.json")["status"] == "PASS", "modules were not built successfully")
    report = dict(status="RUNNING", commands=[], results={}, started=time.time(), build_run=args.build_run,
                  build_summary_sha256=sha((build / "build_summary.json").read_bytes()),
                  implementation={name: sha((ROOT / "scripts" / name).read_bytes()) for name in PRODUCTION})
    dump(output / "summary.json", report)
    corpus = ROOT / "configs/acceptance/e-runtime-unseen-20261111-v1"
    try:
        for backend in ("simx", "rtlsim", "xrtsim"):
            binding_dir = ROOT / "results/c-runtime-merge-20261111-v3/bindings" / backend
            binding = read(binding_dir / "binding.json")
            env = dict(os.environ, VORTEX_DRIVER=binding["driver"], LD_LIBRARY_PATH=binding["library_dir"])
            capture = output / backend
            commands = [[sys.executable, "-B", str(ROOT / "scripts/e_acceptance/runtime_unseen_run.py"),
                         "--corpus", str(corpus), "--modules", str(build / "modules/sim"),
                         "--binding", str(binding_dir / "binding.json"), "--target-lock", str(binding_dir / "target_lock.json"),
                         "--backend", backend, "--out", str(capture)],
                        [sys.executable, "-B", str(ROOT / "scripts/e_acceptance/runtime_unseen_check.py"),
                         "--corpus", str(corpus), "--run", str(capture), "--out", str(output / (backend + ".acceptance.json"))]]
            for command in commands:
                log_path = output / "logs" / ("%02d-%s.log" % (len(report["commands"]), backend))
                row = dict(argv=command, cwd=str(ROOT), environment={k: env[k] for k in ("VORTEX_DRIVER", "LD_LIBRARY_PATH")}, log=str(log_path.relative_to(output)), started=time.time())
                report["commands"].append(row)
                dump(output / "summary.json", report)
                with log_path.open("wb") as stream:
                    result = subprocess.run(command, cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT, timeout=1800)
                row.update(exit_code=result.returncode, finished=time.time(), log_sha256=sha(log_path.read_bytes()))
                dump(output / "summary.json", report)
                need(result.returncode == 0, "failed command " + str(command))
            report["results"][backend] = read(output / (backend + ".acceptance.json"))
            print("ACCEPTED", backend, "48", flush=True)
        report.update(status="PASS", exit_code=0, finished=time.time())
    except Exception as error:
        report.update(status="FAIL", exit_code=1, error=str(error), finished=time.time())
    dump(output / "summary.json", report)
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
