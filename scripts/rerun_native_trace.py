"""Rerun a trace on a verified existing debug build, with fresh evidence only.

No configure/source/toolchain mutation. All inherited build commands must have
succeeded; runtime, program and configuration hashes are checked before/after.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import sys

from run_native_smoke import PROJECT, Recorder, sha256, utc_now
from native_predicate_trace import run_trace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    if sys.platform != "linux":
        parser.error("Linux required")
    for value in (args.parent, args.run_id):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", value):
            parser.error("safe run directory names required")
    parent = PROJECT / "results" / args.parent
    old = json.loads((parent / "summary.json").read_text())
    if old["debug_level"] != 3 or old["backend"] not in ("simx", "rtlsim") or old["blockers"]:
        parser.error("parent must be an unblocked DEBUG=3 SimX/processor build")
    for rec in old["commands"]:
        if rec["returncode"] != 0 or rec["timed_out"] or sha256(parent / rec["log"]) != rec["log_sha256"]:
            parser.error("parent command failed, incomplete or changed: " + rec["label"])
    if old["demo_execution"] != "PASS" or old["source"]["manifest_mismatches"]:
        parser.error("parent source/demo not verified")
    build = Path(old["build_path"])
    app = build / "tests/regression/boundary"
    for source in (PROJECT / "native/boundary").iterdir():
        if source.is_file() and (sha256(source) != sha256(app / source.name) or
                                sha256(source) != sha256(parent / "predicate_trace/source" / source.name)):
            parser.error("native source changed since parent")
    paths = ["config.mk", "sw/VX_config.h", "hw/VX_config.vh"]
    paths += [str(p.relative_to(build)) for p in sorted((build / "sw/runtime").glob("*.so"))]
    paths += ["tests/regression/boundary/" + name for name in ("boundary", "kernel.vxbin", "kernel.elf", "kernel.dump")]
    before = {p: sha256(build / p) for p in paths}
    directory = PROJECT / "results" / args.run_id
    directory.mkdir(exist_ok=False)
    summary = dict(schema_version=7, run_id=args.run_id, status="RUNNING", started_at=utc_now(),
        target_profile=old["target_profile"], debug_level=3, backend=old["backend"], build_path=str(build),
        source=old["source"], config_file_sha256=old["config_file_sha256"], commands=[],
        reused_build=dict(parent=args.parent, parent_status=old["status"], parent_error=old.get("error"),
                          parent_summary_sha256=sha256(parent / "summary.json"), before_sha256=before),
        hardware_verification="NOT_RUN", afu_verification="NOT_RUN", p0_three_kernels="NOT_RUN",
        scope="Fresh native trace executions on the same verified isolated debug build; no full rebuild; no PTX or independent acceptance")
    env = {k: os.environ[k] for k in ("HOME", "PATH", "TMPDIR") if k in os.environ}
    env.update(LANG="C.UTF-8", LC_ALL="C.UTF-8", CCACHE_DISABLE="1", VORTEX_PROFILING="0",
               PYTHONDONTWRITEBYTECODE="1", XLEN="64", DEBUG="3", CONFIGS=old["configs"])
    recorder = Recorder(directory, summary, env)
    shutil.copytree(parent / "configs", directory / "configs")
    implementation = directory / "implementation"
    implementation.mkdir()
    for name in ("rerun_native_trace.py", "run_native_smoke.py", "native_predicate_trace.py", "native_boundary.py"):
        shutil.copy2(PROJECT / "scripts" / name, implementation / name)
    code = 1
    try:
        settings = argparse.Namespace(target_profile=old["target_profile"], build_dir=build, backend=old["backend"],
                                      jobs=4, timeout=1800, reuse_native_app=True)
        passed, step = run_trace(recorder, settings, old["configs"])
        summary["last_step"] = step
        after = {p: sha256(build / p) for p in paths}
        summary["reused_build"]["after_sha256"] = after
        summary["reused_build"]["unchanged"] = before == after
        summary["status"] = "PASS" if passed and before == after else "FAIL"
        summary["build_artifacts"] = {}
        for relative in paths:
            dest = directory / "artifacts" / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(build / relative, dest)
            summary["build_artifacts"][relative] = dict(sha256=sha256(dest), review_copy=str(dest.relative_to(directory)))
        code = 0 if summary["status"] == "PASS" else 1
    except Exception as exc:
        summary.update(status="FAIL", error=repr(exc))
    finally:
        summary["finished_at"] = utc_now()
        summary["exit_code"] = code
        recorder.save()
    print(json.dumps(dict(status=summary["status"], summary=str(directory / "summary.json"), exit_code=code)))
    return code


if __name__ == "__main__":
    sys.exit(main())
