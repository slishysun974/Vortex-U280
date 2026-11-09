"""Check D8 source preparation evidence and run script tests, separately from FPGA acceptance."""
import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tarfile

from run_u280_source_preflight import ports, connectivity_ports

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--source-run", required=True)
    args = parser.parse_args()
    for value in vars(args).values():
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", value):
            parser.error("unsafe run id")
    output = ROOT / "results" / args.run_id
    output.mkdir(exist_ok=False)
    checks = []

    def check(name, ok):
        checks.append(dict(name=name, status="PASS" if ok else "FAIL"))

    try:
        run = ROOT / "results" / args.source_run
        summary = read(run / "summary.json")
        check("source preparation execution", summary["status"] == "PASS" and summary["exit_code"] == 0)
        check("full source identity", summary["source_identity"]["files"] == 3329 and not summary["source_identity"]["mismatches"])
        for command in summary["commands"]:
            check(command["label"] + " exit", command["exit_code"] == 0 and not command["timed_out"])
            for stream in ("stdout", "stderr"):
                check(command["label"] + " " + stream, digest(run / command[stream]) == command[stream + "_sha256"])
        for key in ("synthesis", "vivado_elaboration", "implementation", "board_execution", "host_memory", "independent_reproduction"):
            check(key + " scope", summary[key] == "NOT_RUN")
        check("configurations unchanged in run", summary["config_hashes_before"] == summary["config_hashes_after"])
        for name, value in summary["config_hashes_after"].items():
            check("current configuration " + name, digest(ROOT / name) == value)
        for variant in ("upstream_unmerged", "candidate_merged"):
            top = (run / variant / "vortex_afu.v").read_text()
            plan = (run / "logs" / (variant + "_link_plan.stdout")).read_text()
            actual, linked = ports(top), connectivity_ports(plan)
            contract = summary["variants"][variant]["contract"]
            check(variant + " observed ports", actual == contract["memory_ports"] and linked == contract["explicitly_connected_memory_ports"])
            check(variant + " connection result", (actual == linked) == (contract["status"] == "PASS"))
            check(variant + " HOST", "m_axi_host_awvalid" in top and "vortex_afu_1.m_axi_host:HOST[0]" in plan)
        resolved = shlex.split((run / "candidate_merged/resolved_config.cflags").read_text())
        for flag in ("-DVX_CFG_XLEN=64", "-DVX_CFG_NUM_CLUSTERS=1", "-DVX_CFG_NUM_CORES=1",
                     "-DVX_CFG_NUM_WARPS=8", "-DVX_CFG_NUM_THREADS=4", "-DVX_CFG_PLATFORM_MEMORY_NUM_BANKS=32",
                     "-DVX_CFG_PLATFORM_MEMORY_ADDR_WIDTH=33", "-DVX_CFG_PLATFORM_MEMORY_DATA_SIZE=64",
                     "-DVX_CFG_FPU_TYPE_DSP", "-DSYNTHESIS", "-DVIVADO"):
            check("resolved " + flag, flag in resolved)
        package = run / "package"
        manifest = read(package / "manifest.json")
        fixed = read(ROOT / "results/ab-d1-source-20261107-v2/source_manifest.json")
        fixed = {entry["path"]: entry["sha256"] for entry in fixed}
        generated = {entry["path"]: entry["sha256"] for entry in summary["variants"]["candidate_merged"]["generated_files"]}
        for entry in manifest:
            name = entry["path"]
            check("package " + name, digest(package / name) == entry["sha256"] and (package / name).stat().st_size == entry["bytes"])
            if name.startswith("scripts/"):
                check("pinned " + name, entry["sha256"] == fixed["hw/" + name])
            elif name.startswith("xrt/"):
                check("pinned " + name, entry["sha256"] == fixed["hw/syn/xilinx/" + name])
            elif name.startswith("src/"):
                check("generated " + name, entry["sha256"] == generated[name])
        archive = run / summary["rtl_package"]["path"]
        check("archive identity", digest(archive) == summary["rtl_package"]["sha256"])
        with tarfile.open(archive, "r:gz") as tar:
            expected = {"u280-rtl-input/" + item["path"]: item["sha256"] for item in manifest}
            expected["u280-rtl-input/manifest.json"] = digest(package / "manifest.json")
            actual = {}
            for member in tar.getmembers():
                if member.isfile():
                    actual[member.name] = hashlib.sha256(tar.extractfile(member).read()).hexdigest()
            check("archive exact files and bytes", expected == actual)
        for name in ("u280_remote_probe.py", "wlan_ssh_proxy.py"):
            ast.parse((ROOT / "scripts" / name).read_text(), feature_version=(3, 6))
            check(name + " Python 3.6 syntax", True)
        tests = [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-v"]
        with (output / "tests.log").open("xb") as stream:
            completed = subprocess.run(tests, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, timeout=180)
        check("Python runner/frontend/evidence tests", completed.returncode == 0)
        test_result = dict(argv=tests, cwd=str(ROOT), exit_code=completed.returncode,
                           log="tests.log", sha256=digest(output / "tests.log"))
    except Exception as exc:
        checks.append(dict(name="verification exception", status="FAIL", detail=repr(exc)))
        test_result = locals().get("test_result", dict(status="NOT_RUN"))
    result = dict(schema_version="ab-d8-source-closeout-v1", argv=sys.argv,
        status="PASS" if all(c["status"] == "PASS" for c in checks) else "FAIL", checks=checks,
        passed=sum(c["status"] == "PASS" for c in checks), total=len(checks), tests=test_result,
        source_run=args.source_run, source_summary_sha256=digest(ROOT / "results" / args.source_run / "summary.json"),
        finished_at=datetime.now(timezone.utc).isoformat(),
        scope="same-author source/package evidence and script tests only; remote HOST, FPGA tools, board and independent acceptance remain separate")
    result["exit_code"] = 0 if result["status"] == "PASS" else 1
    snapshot = output / "implementation"
    snapshot.mkdir()
    for name in ("run_u280_source_preflight.py", "prepare_u280_fpga_candidate.py", "prepare_u280_probe.py", "u280_remote_probe.py", "Invoke-U280Preflight.ps1", "verify_ab_d8_results.py"):
        shutil.copy2(ROOT / "scripts" / name, snapshot / name)
    shutil.copytree(ROOT / "tests", snapshot / "tests", ignore=shutil.ignore_patterns("__pycache__"))
    (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: result[k] for k in ("status", "passed", "total", "exit_code")}))
    return result["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
