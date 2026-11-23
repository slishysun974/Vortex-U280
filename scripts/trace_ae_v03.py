"""Compare DEBUG3 LSU requests to the separately frozen A/E PTX trace."""

import argparse
from collections import Counter, defaultdict
import os
from pathlib import Path
import re
import sys

from ae_v03_execute import preflight, review_capture
from bind_simx_runtime import bind
from native_predicate_trace import parse_request
from ptx_boundary_trace import bind_simx, bind_slots
from run_d_guarded_wide import IMAGE_SHA, lane_rows
from run_native_smoke import PROJECT, Recorder, demo_passed, sha256, utc_now
from run_ptx_copy import SIM_LOCK, read_json, require, run_stage, write_json
from run_ptx_copy_trace import TRACE_RUNS, trace_libraries


def analyze(raw, backend, bundle, run, manifest):
    frames = dict(re.findall(r"(?ms)^AE_V03_BEGIN (\w+)\r?\n(.*?)^AE_V03_END \1\s*$", raw))
    require(set(frames) == {s["id"] for s in manifest["cases"]}, "missing trace frame")
    result = {}
    for spec in manifest["cases"]:
        cid = spec["id"]
        bases = read_json(run / backend / cid / "reservations.json")
        frozen = read_json(bundle / "frozen" / cid / "requests.json")["accesses"]
        expected = [(cta, tid, op, bases[role] + 4 * index) for cta, tid, _, op, role, index in frozen]
        if spec["bases"] is not None:
            view, _ = bind_simx(frames[cid], spec) if backend == "simx" else bind_slots(frames[cid], spec["grid"])
            # The neutral decoder takes base+32 to define the log's data windows.
            observed = lane_rows(view, backend, spec, {r: base + 32 for r, base in bases.items()})
            target = defaultdict(list)
            for cta, tid, op, address in expected:
                target[cta, tid].append((op, address))
            require({k: [(op, address) for _, op, address in v] for k, v in observed.items()} == target,
                    "logical lane, address, or request order differs: " + cid)
            evidence = "per-CTA and lane ordered requests"
        else:
            ranges = [(base, base + 4 * spec["words"]) for base in bases.values()]
            actual = Counter()
            for line in frames[cid].splitlines():
                for op, address in parse_request(line, backend) or ():
                    if any(start <= address < end for start, end in ranges):
                        actual[op, address] += 1
            require(actual == Counter((op, address) for _, _, op, address in expected),
                    "data request type/address count differs: " + cid)
            evidence = "allocation-address request counts"
        result[cid] = dict(requests=len(expected), evidence=evidence,
                           high_address_requests=sum(address >= 2**32 for _, _, _, address in expected))
    return result


def native_summary(run, backend, source):
    prior_path = PROJECT / "results" / source / "summary.json"
    if backend != "simx":
        return prior_path
    # The archived SimX rerun proved the debug libraries with a native predicate
    # corpus. The ordinary runtime binding also requires a successful native demo.
    prior = read_json(prior_path)
    libraries, _ = trace_libraries(backend)
    directory = run / "native-simx"
    directory.mkdir()
    demo = Path(prior["build_path"]) / "tests/regression/demo"
    host, image = demo / "demo", demo / "kernel.vxbin"
    summary = {key: prior[key] for key in ("backend", "debug_level", "build_path", "source",
                                          "config_file_sha256", "build_artifacts")}
    summary.update(commands=[], status="RUNNING", check_only=False, archive_sha256=sha256(prior_path),
                   native_demo_files={str(path): sha256(path) for path in (host, image)})
    rec = Recorder(directory, summary, dict(os.environ, LD_LIBRARY_PATH=str(libraries), VORTEX_DRIVER="simx",
                                          VORTEX_PROFILING="0"))
    cmd, output = rec.command("demo_run", [host, "-n1", "-k", image], directory, 120)
    require(demo_passed(cmd["returncode"], cmd["timed_out"], output), "debug native demo failed")
    summary.update(status="PASS", demo_execution="PASS", exit_code=0)
    rec.save()
    return directory / "summary.json"


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--bundle", type=Path, required=True)
    cli.add_argument("--build", type=Path, required=True)
    cli.add_argument("--run-id", required=True)
    args = cli.parse_args()
    require(re.fullmatch(r"ae-v03-trace-[A-Za-z0-9_-]{1,48}", args.run_id), "choose a new trace run ID")
    run = PROJECT / "results" / args.run_id
    run.mkdir()
    report = dict(argv=[sys.executable, "-B", *sys.argv], started_at=utc_now(), status="RUNNING", commands=[], backends={})
    rec = Recorder(run, report, dict(os.environ))
    try:
        bundle, build = args.bundle.resolve(), args.build.resolve()
        plan, manifest = preflight(bundle)
        require(plan["modules"]["guarded_wide_offset"]["image_sha256"] == IMAGE_SHA and
                plan["build_summary_sha256"] == sha256(build / "summary.json"), "trace decoder image/build differs")
        for backend, source in TRACE_RUNS.items():
            binding_dir = run / "bindings" / backend
            info = bind(native_summary(run, backend, source), SIM_LOCK, SIM_LOCK.with_name("native_smoke.json"), binding_dir)
            rec.env.update(VORTEX_DRIVER=backend, LD_LIBRARY_PATH=info["library_dir"], VORTEX_PROFILING="0")
            for key in ("XCLBIN_PATH", "XCL_EMULATION_MODE", "VORTEX_CP_POLL_TIMEOUT_S"):
                rec.env.pop(key, None)
            binding = binding_dir / "binding.json"
            raw = run_stage(rec, backend, ["stdbuf", "-oL", "-eL", sys.executable, "-B",
                            bundle / "scripts/ae_v03_execute.py", "capture", "--backend", backend,
                            "--bundle", bundle, "--build", build, "--lock", SIM_LOCK, "--binding", binding,
                            "--output", run], run, 450)
            receipt = review_capture(bundle, run, backend, binding)
            cases = analyze(raw, backend, bundle, run, manifest)
            write_json(run / (backend + ".requests.json"), cases)
            report["backends"][backend] = dict(status="PASS", receipt=receipt, binding_sha256=sha256(binding),
                request_count=sum(v["requests"] for v in cases.values()), cases=len(cases))
        report.update(status="PASS", exit_code=0)
    except Exception as error:
        report.update(status="FAIL", exit_code=1, error=str(error))
    report["finished_at"] = utc_now()
    rec.save()
    print(report["status"], run, report.get("error", ""))
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
