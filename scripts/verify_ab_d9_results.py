"""Verify D9 evidence and runner tests, independently of FPGA acceptance status."""
import argparse
import ast
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "environment/u280-fpga"))
from build_prepared import validate_input


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--host-run", required=True)
    parser.add_argument("--xo-run")
    parser.add_argument("--checks-run", help="reuse previously captured test run; do not run tests again")
    args = parser.parse_args()
    for name, value in vars(args).items():
        if value and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", value):
            parser.error("unsafe run id")
    out = ROOT / "results" / args.run_id
    out.mkdir(exist_ok=False)
    result = dict(schema_version="ab-d9-evidence-v1", started_at=datetime.now(timezone.utc).isoformat(),
                  argv=sys.argv, scope="script tests and evidence integrity; FPGA outcomes reported separately",
                  checks=[], commands=[], xo_packaging="NOT_RUN", full_synthesis="NOT_RUN",
                  implementation="NOT_RUN", board_execution="NOT_RUN", host_configuration="NOT_RUN")

    def check(name, ok):
        result["checks"].append(dict(name=name, status="PASS" if ok else "FAIL"))

    def transport(run_id):
        run = ROOT / "results" / run_id
        record = read(run / "transport.json")
        probe = read(run / "probe.json")
        prep = read(run / "preparation.json")
        check(run_id + " SSH exit", record["ssh_exit_code"] == 0)
        check(run_id + " nonce/run binding", probe["run_id"] == run_id and probe["nonce"] == prep["nonce"])
        check(run_id + " collector binding", probe["remote_probe_sha256"] == prep["remote_probe_sha256"])
        check(run_id + " raw stdout", digest(run / "probe.stdout") == probe["raw_stdout_sha256"])
        for key in ("payload", "bundle"):
            path = run / ("payload.py" if key == "payload" else "bundle.json")
            check(run_id + " " + key, digest(path) == prep[key + "_sha256"])
        for name, item in probe["files"].items():
            if "local_path" in item:
                path = run / item["local_path"]
                check(run_id + " " + name, digest(path) == item["sha256"] and path.stat().st_size == item["bytes"])
        return run, probe

    try:
        before = read(ROOT / "results/ab-d9-prechange-20261109-v1/snapshot.json")
        for name, expected in before["sha256"].items():
            if name != "environment/u280-fpga/build_prepared.py":
                check("unchanged " + name, digest(ROOT / name) == expected)
        lock = read(ROOT / "configs/target_lock.json")
        manifest = ROOT / lock["evidence"] / "source_manifest.json"
        check("fixed source manifest", digest(manifest) == lock["source_manifest_sha256"])
        def source_mismatch(item):
            return item["path"] if digest(ROOT / "upstream/vortex" / item["path"]) != item["sha256"] else None
        with ThreadPoolExecutor(max_workers=8) as pool:
            mismatches = [name for name in pool.map(source_mismatch, read(manifest)) if name]
        result["fixed_source_identity"] = dict(files=len(read(manifest)), mismatches=mismatches)
        check("fixed source files", not mismatches)
        identity = validate_input(ROOT / "results/ab-d8-u280-source-20261109-v1/package")[1]
        result["input_identity"] = identity
        host, probe = transport(args.host_run)
        check("HOST/platform probe PASS", probe["status"] == "PASS" and probe["probe_kind"] == "host-platform")
        required = [c for c in probe["commands"] if not c["label"].startswith("holders_") and c["label"] != "host_mem_permission_query"]
        for command in probe["commands"]:
            for stream in ("stdout", "stderr"):
                check(command["label"] + " " + stream, digest(host / "returned" / command[stream]) == command[stream + "_sha256"])
        check("required remote commands exit 0", all(c["returncode"] == 0 and not c["timed_out"] for c in required))
        metadata = read(host / "returned/platform_metadata.json")
        ext = json.loads(next(x["small_metadata"]["ext_metadata.json"] for x in metadata if "small_metadata" in x))
        interfaces = ext["xclbin"]["append_sections"]["partition_metadata"]["interfaces"]
        platform_uuids = {x["interface_uuid"].replace("-", "").lower() for x in interfaces}
        result["platform_files"] = [{k: x[k] for k in ("path", "sha256", "bytes")} for x in metadata]
        result["platform_interface_uuids"] = sorted(platform_uuids)
        result["devices"] = []
        for device in probe["devices"]:
            bdf = device["bdf"]
            state = device["after"]
            uuids = set(state["interface_uuids"]["text"].lower().split())
            check(bdf + " interface UUID", uuids == platform_uuids)
            check(bdf + " snapshots", device["before"] == device["after"])
            report = read(host / "returned" / device["xrt_report"])["devices"][0]
            cus = [cu for region in report["dynamic_regions"] for cu in region["compute_units"]]
            result["devices"].append(dict(bdf=bdf, ready=state["ready"]["text"].strip(),
                host_mem_size=state["host_mem_size"]["text"].strip(), kds=state["kdsstat"]["text"],
                all_reported_cus_idle=bool(cus) and all("IDLE" in cu["status"]["bits_set"] for cu in cus)))
        check("eight devices", len(probe["devices"]) == 8)
        policy = next(c for c in probe["commands"] if c["label"] == "host_mem_permission_query")
        result["host_permission"] = dict(status=probe["host_configuration_permission"], exit_code=policy["returncode"],
            stderr=(host / "returned" / policy["stderr"]).read_text())
        for key in ("board_programming", "board_reset", "device_configuration", "full_vortex_synthesis", "place_route", "board_execution"):
            check("HOST probe scope " + key, probe[key] == "NOT_RUN")
        if args.xo_run:
            run, xo = transport(args.xo_run)
            result["xo_transport_run"] = args.xo_run
            result["xo_packaging"] = xo["status"]
            build = xo.get("build_result", {})
            result["xo_build_result"] = build
            check("XO result saved", build == read(run / "returned/build/result.json"))
            check("XO complete input identity", all(build[k] == identity[k] for k in identity))
            check("XO stage", build["stage"] == "xo")
            check("XO platform identity", xo["platform_identity"] == result["platform_files"])
            for c in build["commands"]:
                for stream in ("stdout", "stderr"):
                    check("XO " + c["label"] + " " + stream,
                          digest(run / "returned/build" / (c["label"] + "." + stream)) == c[stream + "_sha256"])
            check("XO success/failure truthful", (build["status"] == "PASS") == (build["exit_code"] == 0))
        changed = ["environment/u280-fpga/build_prepared.py", "scripts/prepare_u280_probe.py", "scripts/u280_remote_xo.py",
                   "scripts/Invoke-U280Preflight.ps1", "scripts/verify_ab_d9_results.py", "tests/test_u280_prepared_build.py", "tests/test_u280_probe_bundle.py"]
        result["implementation_hashes"] = {}
        for name in changed:
            path = ROOT / name
            target = out / "implementation" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            result["implementation_hashes"][name] = digest(path)
            if name.endswith(".py") and not name.startswith("tests/"):
                ast.parse(path.read_text(), feature_version=(3, 6))
                check(name + " Python 3.6 syntax", True)
        if args.checks_run:
            previous_path = ROOT / "results" / args.checks_run / "result.json"
            previous = read(previous_path)
            check("previous script checks PASS", previous["status"] == "PASS" and previous["script_tests"]["exit_code"] == 0)
            check("tested implementation unchanged", previous["implementation_hashes"] == result["implementation_hashes"])
            result["script_tests"] = previous["script_tests"]
            result["script_test_source"] = dict(run_id=args.checks_run, sha256=digest(previous_path))
            for stream in ("stdout", "stderr"):
                check("prior tests " + stream, digest(previous_path.parent / ("tests." + stream)) == previous["script_tests"][stream + "_sha256"])
        else:
            argv = [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-v"]
            with (out / "tests.stdout").open("xb") as stdout, (out / "tests.stderr").open("xb") as stderr:
                code = subprocess.call(argv, cwd=str(ROOT), stdout=stdout, stderr=stderr)
            rec = dict(argv=argv, exit_code=code, stdout_sha256=digest(out / "tests.stdout"), stderr_sha256=digest(out / "tests.stderr"))
            result["script_tests"] = rec
            result["commands"].append(rec)
            check("script tests exit 0", code == 0)
        result["status"] = "PASS" if all(c["status"] == "PASS" for c in result["checks"]) else "FAIL"
    except Exception as exc:
        result.update(status="FAIL", error=repr(exc))
    result.update(exit_code=0 if result["status"] == "PASS" else 1,
                  finished_at=datetime.now(timezone.utc).isoformat())
    (out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(dict(status=result["status"], checks=len(result["checks"]), result=str(out / "result.json"),
                         xo_packaging=result["xo_packaging"], error=result.get("error"))))
    return result["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
