"""Build independent frozen E sources through the actual pinned production tools."""
import argparse
from pathlib import Path
import subprocess
import sys
import time

from runtime_unseen_common import PRODUCTION, corpus, dump, sha

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    output = ROOT / "results" / args.run_id
    output.mkdir(parents=True, exist_ok=False)
    logs = output / "logs"
    logs.mkdir()
    manifest = corpus(ROOT / "configs/acceptance/e-runtime-unseen-20261111-v1")
    report = dict(status="RUNNING", scope="12 fresh modules, six PTX programs times sim/board", commands=[], started=time.time(),
                  implementation={name: sha((ROOT / "scripts" / name).read_bytes()) for name in PRODUCTION}, modules={})
    dump(output / "build_summary.json", report)
    source = "/opt/vortex-ab/sources/vortex-7fe19369587c-v1"
    tools = "/opt/vortex-ab/toolchains/8c64cf921d3c6c456e80f00d24482d0aa2153a82-rtlsim-d3-v1"
    try:
        for target in ("sim", "board"):
            reference = ROOT / "results/c-runtime-merge-20261111-v3/modules" / target / "copy"
            lock, hardware = reference / "target_lock.json", reference / "hardware.json"
            for name, item in manifest["sources"].items():
                module = output / "modules" / target / name
                ptx = ROOT / "configs/acceptance/e-runtime-unseen-20261111-v1" / item["file"]
                base = [sys.executable, "-B", str(ROOT / "scripts/ptx_module.py")]
                commands = [base + ["prepare", str(ptx), "--output", str(module), "--target-lock", str(lock), "--hardware", str(hardware)],
                            base + ["build", str(module), "--vortex-source", source, "--tooldir", tools, "--build-root", str(output / "isolated_build" / target / name), "--target-lock", str(lock)],
                            base + ["validate", str(module), "--target-lock", str(lock)]]
                for command in commands:
                    index = len(report["commands"])
                    log_path = logs / ("%03d.log" % index)
                    row = dict(argv=command, cwd=str(ROOT), log=str(log_path.relative_to(output)), started=time.time())
                    report["commands"].append(row)
                    dump(output / "build_summary.json", report)
                    with log_path.open("wb") as stream:
                        result = subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, timeout=300)
                    row.update(exit_code=result.returncode, finished=time.time(), log_sha256=sha(log_path.read_bytes()))
                    dump(output / "build_summary.json", report)
                    if result.returncode:
                        raise RuntimeError("command failed: " + str(command))
                report["modules"][target + "/" + name] = dict(source_sha256=sha((module / "source.ptx").read_bytes()), image_sha256=sha((module / "kernel.vxbin").read_bytes()), manifest_sha256=sha((module / "manifest.json").read_bytes()))
                print("BUILT", target, name, flush=True)
        report.update(status="PASS", exit_code=0, finished=time.time())
    except Exception as error:
        report.update(status="FAIL", error=str(error), exit_code=1, finished=time.time())
    dump(output / "build_summary.json", report)
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
