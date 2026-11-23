"""Run one Iris milestone in a fresh results directory in the fixed project WSL."""
import argparse
import os
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
sys.path.insert(0, str(PROJECT / "scripts"))
from check_c_v03_receipt import BINDINGS, TOOLCHAIN
from ptx_module import BOARD_SCHEMA, SCHEMA, validate
from run_native_smoke import Recorder, sha256, utc_now
from run_ptx_copy import BOARD_LOCK, SIM_LOCK, VORTEX, read_json, require, run_stage
from runtime_backends import BACKENDS

ENTRY = "iris_nearest_centroid_u32"
SOURCE = PROJECT / "ptx/samples" / (ENTRY + ".ptx")
PY = [sys.executable, "-B"]


def build(run, rec):
    root_lock = PROJECT / "configs/target_lock.json"
    head = run_stage(rec, "upstream_head", ["git", "-C", VORTEX, "rev-parse", "HEAD"], run).strip()
    require(head == read_json(root_lock)["vortex"]["commit"], "upstream commit differs from root lock")
    run_stage(rec, "upstream_diff", ["git", "-C", VORTEX, "diff", "--exit-code", "HEAD", "--"], run)
    rec.summary.update(root_lock_sha256=sha256(root_lock), source_commit=head, ptx_sha256=sha256(SOURCE), modules={})
    expected_layout = [("x","u64",0), ("sums","u64",8), ("out","u64",16), ("n","u32",24)]
    for target, lock, hardware, schema in (("sim", SIM_LOCK, "native_smoke.json", SCHEMA),
                                          ("board", BOARD_LOCK, "fpga.json", BOARD_SCHEMA)):
        module = run / "modules" / target
        build_dir = PROJECT / "build" / run.name / target
        for action, args in (
                ("prepare", [SOURCE, "--output", module, "--hardware", lock.with_name(hardware)]),
                ("build", [module, "--build-root", build_dir, "--vortex-source", VORTEX, "--tooldir", TOOLCHAIN]),
                ("validate", [module])):
            run_stage(rec, target+"_"+action, PY+[PROJECT/"scripts/ptx_module.py", action, *args, "--target-lock", lock], run, 600)
        meta, _ = validate(module, lock.read_bytes())
        params = [(p["name"], p["type"], p["offset"]) for p in meta["params"]]
        front = read_json(module / "frontend_manifest.json")
        require(params == expected_layout and meta["params_size"] == 32 and meta["params_align"] == 8
                and meta["entry"] == ENTRY and meta["abi_version"] == "ptx-vx-args-v1"
                and meta["schema_version"] == schema and meta["source_sha256"] == sha256(SOURCE)
                and front["compiler_id"] == "ptx-vx-frontend-v1.2", "Iris module contract differs")
        rec.summary["modules"][target] = dict(manifest_sha256=sha256(module/"manifest.json"),
            image_sha256=meta["image_sha256"], schema=schema, lock_sha256=sha256(lock), params=params,
            payload_bytes=meta["params_size"], compiler=front["compiler_id"])


def models(run, rec, frozen, compiled):
    from review import check_corpus, review
    manifest = check_corpus(frozen)
    built = read_json(compiled / "summary.json")
    require(built["status"] == "PASS" and built["exit_code"] == 0, "missing successful build")
    module = compiled / "modules/sim"
    identity = sha256(module / "manifest.json")
    require(identity == built["modules"]["sim"]["manifest_sha256"], "sim module changed since build")
    rec.summary.update(models={}, corpus_sha256=sha256(frozen/"manifest.json"), build_summary_sha256=sha256(compiled/"summary.json"))
    for backend, (driver, _, _) in BACKENDS.items():
        binding = BINDINGS / backend / "binding.json"
        rec.env.update(VORTEX_DRIVER=driver, LD_LIBRARY_PATH=read_json(binding)["library_dir"],
                       VORTEX_PROFILING="0", XRT_DEVICE_INDEX="0")
        out = run / backend
        run_stage(rec, backend, PY+[HERE/"capture.py", "--inputs", frozen, "--module", module,
                  "--lock", SIM_LOCK, "--binding", binding, "--backend", backend, "--output", out], run, 900)
        rec.summary["models"][backend] = review(frozen, manifest, out, backend, binding, identity, negative=True)
        rec.save()


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("stage", choices=("freeze","build","models","selftest"))
    cli.add_argument("tag", help="fresh ID suffix")
    cli.add_argument("--frozen", type=Path)
    cli.add_argument("--compiled", type=Path)
    a = cli.parse_args()
    require(re.fullmatch(r"[a-zA-Z0-9_-]{1,48}", a.tag), "invalid run tag")
    run = PROJECT / "results" / ("iris-" + a.stage + "-" + a.tag)
    run.mkdir()
    env = {k:v for k,v in os.environ.items() if k not in
           ("XCL_EMULATION_MODE","XCLBIN_PATH","VORTEX_CP_POLL_TIMEOUT_S","VORTEX_DRIVER","VORTEX_PROFILING")}
    report = dict(stage=a.stage, run_id=run.name, status="RUNNING", commands=[],
                  argv=[sys.executable,"-B",*sys.argv], started_at=utc_now())
    rec = Recorder(run, report, env)
    try:
        if a.stage == "freeze":
            run_stage(rec, "freeze", PY+[HERE/"freeze.py", run/"corpus"], run)
            report.update(manifest_sha256=sha256(run/"corpus/manifest.json"), oracle_sha256=sha256(HERE/"freeze.py"))
        elif a.stage == "build":
            build(run, rec)
        elif a.stage == "models":
            require(a.frozen and a.compiled, "models requires --frozen CORPUS and --compiled BUILD")
            models(run, rec, a.frozen.resolve(), a.compiled.resolve())
        else:
            run_stage(rec, "runner_selftest", PY+["-m","unittest","discover","-s","tests","-v"], PROJECT, 900)
        report.update(status="PASS", exit_code=0)
    except Exception as error:
        report.update(status="FAIL", exit_code=1, error=str(error))
    report["finished_at"] = utc_now()
    rec.save()
    print(report["status"], run, report.get("error",""))
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
