#!/usr/bin/env python3
"""Fetch pinned Ramulator source dependencies into a new evidence directory."""

import argparse
import json
import os
from pathlib import Path
import re
import sys


PROJECT = Path(__file__).resolve().parents[1]
RAMULATOR_COMMIT = "e62c84a6f0e06566ba6e182d308434b4532068a5"
DEPENDENCIES = {
    "yaml-cpp": {"repository": "https://github.com/jbeder/yaml-cpp.git",
                 "tag": "yaml-cpp-0.7.0", "commit": "0579ae3d976091d7d664aa9d2527e0d0cff25763"},
    "spdlog": {"repository": "https://github.com/gabime/spdlog.git",
               "tag": "v1.11.0", "commit": "ad0e89cbfb4d0c1ce4d097e134eb7be67baebb36"},
    "argparse": {"repository": "https://github.com/p-ranav/argparse.git",
                 "tag": "v2.9", "commit": "997da9255618311d1fcb0135ce86022729d1f1cb"},
}


def source_manifest(root):
    from run_native_smoke import sha256

    files = {}
    for directory, names, filenames in os.walk(str(root), followlinks=False):
        names[:] = sorted(name for name in names if name != ".git")
        for name in names + sorted(filenames):
            path = Path(directory) / name
            if path.is_symlink():
                raise ValueError("dependency symlink is not supported: " + str(path))
            if path.is_file() and name != ".git":
                files[path.relative_to(root).as_posix()] = sha256(path)
    return files


def validate_bundle(root):
    root = Path(root)
    manifest_path = root / "bundle.json"
    if manifest_path.is_symlink() or root.is_symlink():
        raise ValueError("dependency bundle must not be a symlink")
    bundle = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (bundle.get("schema_version") != "ramulator-dependencies-v1"
            or bundle.get("ramulator_commit") != RAMULATOR_COMMIT
            or set(bundle.get("dependencies", {})) != set(DEPENDENCIES)):
        raise ValueError("dependency bundle schema or Ramulator identity differs")
    for name, expected in DEPENDENCIES.items():
        entry = bundle["dependencies"][name]
        if any(entry.get(key) != value for key, value in expected.items()):
            raise ValueError("dependency identity differs: " + name)
        dependency = root / name
        if dependency.is_symlink() or not dependency.is_dir():
            raise ValueError("dependency source directory missing or linked: " + name)
        actual = source_manifest(dependency)
        if not actual or actual != entry.get("files"):
            raise ValueError("dependency file hashes differ: " + name)
        if "CMakeLists.txt" not in actual or not any(path.startswith("include/") for path in actual):
            raise ValueError("dependency CMakeLists.txt or headers missing: " + name)
    return bundle


def main(argv=None):
    from run_native_smoke import Recorder, sha256, utc_now, within

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--results-dir", type=Path, default=PROJECT / "results")
    parser.add_argument("--fetch", action="store_true", help="explicitly download the three fixed Git commits")
    parser.add_argument("--timeout", type=int, default=180, help="seconds per Git command")
    args = parser.parse_args(argv)
    if not args.fetch:
        parser.error("--fetch is required; this command accesses the three upstream repositories")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", args.run_id) or args.timeout <= 0:
        parser.error("use a safe single-component run-id and a positive timeout")
    directory = args.results_dir.resolve() / args.run_id
    if within(directory, (PROJECT / "upstream").resolve()):
        parser.error("dependency evidence must stay outside upstream/")
    try:
        directory.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        parser.error("run directory already exists; use a new --run-id")
    summary = {"schema_version": 1, "run_id": args.run_id, "status": "RUNNING", "started_at": utc_now(),
               "scope": "pinned Ramulator dependency source acquisition only; no tool installation or Vortex execution",
               "commands": [], "dependencies": {}, "script_sha256": sha256(__file__),
               "upstream_smoke": "NOT_RUN", "hardware_verification": "NOT_RUN"}
    env = dict(os.environ)
    env.update({"GIT_TERMINAL_PROMPT": "0", "GIT_LFS_SKIP_SMUDGE": "1"})
    recorder = Recorder(directory, summary, env)
    root = directory / "dependencies"
    root.mkdir()
    code = 1
    try:
        bundle = {"schema_version": "ramulator-dependencies-v1", "ramulator_commit": RAMULATOR_COMMIT,
                  "dependencies": {}}
        for name, pin in DEPENDENCIES.items():
            destination = root / name
            git = ["git", "-c", "core.autocrlf=false", "-c", "core.longpaths=true"]
            commands = [
                ("init", git + ["init", "-q", str(destination)]),
                ("remote", git + ["-C", str(destination), "remote", "add", "origin", pin["repository"]]),
                ("fetch", git + ["-C", str(destination), "fetch", "--depth=1", "origin", pin["commit"]]),
                ("checkout", git + ["-C", str(destination), "checkout", "--detach", "FETCH_HEAD"]),
                ("identity", git + ["-C", str(destination), "rev-parse", "HEAD"]),
            ]
            for label, command in commands:
                record, output = recorder.command(name + "_" + label, command, directory, args.timeout)
                if record["returncode"] != 0 or record["timed_out"]:
                    raise RuntimeError(name + " " + label + " failed; see " + record["log"])
                if label == "identity" and output.strip() != pin["commit"]:
                    raise ValueError("downloaded commit differs: " + name)
            files = source_manifest(destination)
            bundle["dependencies"][name] = dict(pin, files=files)
            summary["dependencies"][name] = dict(pin, file_count=len(files))
        bundle_path = root / "bundle.json"
        bundle_path.write_text(json.dumps(bundle, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        validate_bundle(root)
        summary.update(status="PASS", bundle=str(bundle_path), bundle_sha256=sha256(bundle_path))
        code = 0
    except KeyboardInterrupt:
        summary.update(status="FAIL", error="interrupted")
        code = 130
    except Exception as error:
        summary.update(status="FAIL", error="{}: {}".format(type(error).__name__, error))
    finally:
        summary["finished_at"] = utc_now()
        recorder.save()
    print(json.dumps({"status": summary["status"], "scope": summary["scope"],
                      "summary": str(directory / "summary.json")}, ensure_ascii=True))
    return code


if __name__ == "__main__":
    sys.exit(main())
