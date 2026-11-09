"""Run harness checks then three isolated block32 candidate builds in parallel."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shutil
import sys

from run_native_smoke import PROJECT, Recorder, sha256, utc_now


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    import re
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,70}", args.run_id):
        parser.error("unsafe run id")
    if sys.platform != "linux":
        parser.error("requires the prepared Linux host")
    root = PROJECT / "results" / args.run_id
    root.mkdir(exist_ok=False)
    snapshot = root / "implementation"
    snapshot.mkdir()
    paths = list((PROJECT / "scripts").glob("*.py")) + list((PROJECT / "tests").glob("*.py"))
    paths += [p for p in (PROJECT / "native/boundary").iterdir() if p.is_file()]
    for path in paths:
        target = snapshot / path.relative_to(PROJECT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    summary = dict(schema_version="ab-block32-validation-v1", status="RUNNING", started_at=utc_now(),
                   commands=[], implementation_sha256={str(p.relative_to(PROJECT)): sha256(p) for p in paths},
                   scope="A/B native self-test; no PTX, E acceptance or board execution")
    recorder = Recorder(root, summary, dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    check, output = recorder.command("runner_tests", [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-v"], PROJECT, 180)
    print(output, flush=True)
    if check["returncode"] != 0 or check["timed_out"]:
        summary.update(status="FAIL", finished_at=utc_now())
        recorder.save()
        return 1

    def run_backend(backend):
        run_id = args.run_id + "-" + backend
        log_dir = root / backend
        log_dir.mkdir()
        sub = dict(backend=backend, status="RUNNING", commands=[], run_id=run_id)
        record = Recorder(log_dir, sub, recorder.env)
        command = [sys.executable, "-B", str(PROJECT / "scripts/run_native_smoke.py"),
                   "--target-profile", "block32-v1", "--backend", backend, "--native-boundary",
                   "--source", "/opt/vortex-ab/sources/vortex-7fe19369587c-v1",
                   "--tooldir", "/opt/vortex-ab/toolchains/8c64cf921d3c6c456e80f00d24482d0aa2153a82-rtlsim-d3-v1",
                   "--ramulator-deps", str(PROJECT / "results/ab-d2-ramulator-deps-20261108-v1/dependencies"),
                   "--build-dir", "/opt/vortex-ab/builds/" + run_id,
                   "--run-id", run_id, "--jobs", "4", "--timeout", "1800"]
        result, output = record.command("native_validation", command, PROJECT, 5400)
        sub.update(status="PASS" if result["returncode"] == 0 and not result["timed_out"] else "FAIL",
                   evidence="results/" + run_id + "/summary.json")
        record.save()
        print(backend + ": " + output.strip(), flush=True)
        return sub

    with ThreadPoolExecutor(max_workers=3) as pool:
        summary["backends"] = list(pool.map(run_backend, ("simx", "rtlsim", "xrtsim")))
    unchanged = all(sha256(PROJECT / p) == digest for p, digest in summary["implementation_sha256"].items())
    summary.update(status="PASS" if unchanged and all(b["status"] == "PASS" for b in summary["backends"]) else "FAIL",
                   implementation_unchanged=unchanged, finished_at=utc_now())
    recorder.save()
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
