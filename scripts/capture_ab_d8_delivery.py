"""Capture final D8 implementation and local wrapper inspection without changing prior evidence."""
import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--inspect-result", type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", args.run_id):
        parser.error("unsafe run id")
    output = ROOT / "results" / args.run_id
    output.mkdir(exist_ok=False)
    files = ["docs/AB_D8_PROGRESS.md", "docs/STATUS.md", "docs/PROJECT_HANDOFF.md", "docs/U280_ACCESS_CHECKLIST.md",
             "scripts/prepare_u280_fpga_candidate.py", "scripts/run_u280_source_preflight.py", "scripts/verify_ab_d8_results.py",
             "scripts/prepare_u280_probe.py", "scripts/u280_remote_probe.py", "scripts/Invoke-U280Preflight.ps1",
             "scripts/capture_ab_d8_delivery.py", "environment/u280-fpga/README.md", "environment/u280-fpga/build_prepared.py",
             "tests/test_u280_source_preflight.py"]
    files += [str(p.relative_to(ROOT)) for p in sorted((ROOT / "configs/candidates/u280-hbm32-v1").iterdir()) if p.is_file()]
    records, missing_links = [], []
    for name in files:
        source = ROOT / name
        destination = output / "files" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        records.append(dict(path=name, sha256=digest(destination), bytes=destination.stat().st_size))
        if source.suffix == ".md":
            for link in re.findall(r"\]\(([^)]+)\)", source.read_text()):
                if not link.startswith(("https:", "http:", "#")) and not (source.parent / link.split("#")[0]).exists():
                    missing_links.append(dict(file=name, link=link))
    ast.parse((ROOT / "environment/u280-fpga/build_prepared.py").read_text(), feature_version=(3, 6))
    inspect = json.loads(args.inspect_result.read_text())
    shutil.copy2(args.inspect_result, output / "wrapper_inspect.json")
    wrapper_identity = digest(args.inspect_result.parent / "build_prepared.py") == digest(ROOT / "environment/u280-fpga/build_prepared.py")
    check_path = ROOT / "results/ab-d8-closeout-20261109-v1/result.json"
    closeout = json.loads(check_path.read_text())
    remote_path = ROOT / "results/u280-host-platform-20261109-v1/transport.json"
    remote = json.loads(remote_path.read_text(encoding="utf-8-sig"))
    passed = not missing_links and wrapper_identity and inspect["status"] == "PASS" and inspect["stage"] == "inspect" and inspect["exit_code"] == 0 and not inspect["commands"] and closeout["exit_code"] == 0
    result = dict(schema_version="ab-d8-delivery-v1", status="PASS" if passed else "FAIL", exit_code=0 if passed else 1,
        scope="delivery identity, local inspect execution, source closeout and document links; no FPGA or board acceptance",
        argv=sys.argv, files=records, missing_local_links=missing_links,
        wrapper_identity_matches_executed=wrapper_identity, wrapper_inspect_sha256=digest(output / "wrapper_inspect.json"),
        closeout_sha256=digest(check_path), closeout_passed=closeout["passed"],
        remote_transport_status=remote["status"], remote_ssh_exit_code=remote["ssh_exit_code"], remote_transport_sha256=digest(remote_path),
        remote_probe="NOT_RUN", fpga_tools="NOT_RUN", board="NOT_RUN", independent_acceptance="NOT_RUN",
        finished_at=datetime.now(timezone.utc).isoformat())
    (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: result[k] for k in ("status", "exit_code", "wrapper_identity_matches_executed", "remote_transport_status")}))
    return result["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
