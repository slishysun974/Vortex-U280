#!/usr/bin/env python3
"""Cache fixed Vortex prebuilt archives, verify their Git blobs, optionally extract on Linux."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import sys
import urllib.request

from run_native_smoke import PROJECT, TOOLCHAIN_COMMIT, Recorder, sha256, utc_now, within


REPOSITORY = "vortexgpgpu/vortex-toolchain-prebuilt"
COMPONENTS = {
    "riscv64-gnu-toolchain": "riscv64-gnu-toolchain/ubuntu/focal/",
    "llvm-vortex": "llvm-vortex/ubuntu/focal/",
    "libc64": "libc64/",
    "libcrt64": "libcrt64/",
}
PROFILES = {"simx": dict(COMPONENTS),
            "rtlsim": dict(COMPONENTS, verilator="verilator/ubuntu/focal/")}


def cache_components(manifest):
    profile = manifest.get("profile", "simx")
    if (manifest.get("schema_version") != "vortex-toolchain-cache-v1"
            or manifest.get("commit") != TOOLCHAIN_COMMIT or manifest.get("repository") != REPOSITORY
            or manifest.get("osversion") != "ubuntu/focal" or profile not in PROFILES
            or set(manifest.get("components", {})) != set(PROFILES[profile])):
        raise ValueError("cache identity or component profile differs from pinned toolchain")
    return PROFILES[profile]


def fetch(url, destination):
    request = urllib.request.Request(url, headers={"User-Agent": "Vortex-U280-reproducible-preparation"})
    with urllib.request.urlopen(request, timeout=90) as response, destination.open("xb") as output:
        shutil.copyfileobj(response, output, 1024 * 1024)


def fetch_archive(url, destination, record, recorder):
    record["attempts"] = []
    for attempt in range(1, 4):
        temporary = destination.with_name(destination.name + ".attempt" + str(attempt))
        entry = {"path": temporary.name, "started_at": utc_now()}
        record["attempts"].append(entry)
        recorder.save()
        try:
            fetch(url, temporary)
            entry.update(status="PASS", finished_at=utc_now())
            temporary.rename(destination)
            return
        except Exception as error:
            entry.update(status="FAIL", finished_at=utc_now(), error="{}: {}".format(type(error).__name__, error))
            recorder.save()
            if attempt == 3:
                raise
            print("retrying " + destination.name + " after " + entry["error"], flush=True)


def blob_sha1(path):
    digest = hashlib.sha1(("blob " + str(path.stat().st_size) + "\0").encode("ascii"))
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract_archives(recorder, manifest, cache, tooldir=None):
    import tarfile

    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise ValueError("extraction requires Linux x86_64")
    tools = Path(tooldir).resolve() if tooldir else recorder.directory / "tools"
    if within(tools, (PROJECT / "upstream").resolve()):
        raise ValueError("tool directory must stay outside upstream/")
    tools.mkdir(parents=True, exist_ok=False)
    for component, entry in manifest["components"].items():
        archive = cache / entry["archive"]
        if sha256(archive) != entry["archive_sha256"]:
            raise ValueError("cached archive hash differs: " + component)
        root = tools / component
        with tarfile.open(str(archive), "r:bz2") as stream:
            for member in stream:
                path = tools / member.name
                if not within(path.resolve(), root) or not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
                    raise ValueError("unsafe archive member: " + member.name)
                if member.issym() or member.islnk():
                    link = path.parent / member.linkname if member.issym() else tools / member.linkname
                    if not within(link.resolve(), root):
                        raise ValueError("archive link leaves its component: " + member.name)
        record, _ = recorder.command("extract_" + component,
                                     ["tar", "-xjf", str(archive), "--no-same-owner", "-C", str(tools)],
                                     recorder.directory, timeout=600)
        if record["returncode"] != 0 or record["timed_out"]:
            raise RuntimeError("extraction failed: " + component)
    return tools


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--results-dir", type=Path, default=PROJECT / "results")
    parser.add_argument("--reuse-cache", type=Path, help="reuse only complete, verified parts from an earlier download run")
    parser.add_argument("--tooldir", type=Path, help="new Linux-native tool directory for extraction; never overwritten")
    parser.add_argument("--profile", choices=tuple(PROFILES), default="simx",
                        help="download profile; rtlsim adds the fixed Verilator bundle")
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--download", action="store_true", help="download the selected fixed components; no installation")
    actions.add_argument("--extract-cache", type=Path, help="offline extraction of a completed download run")
    args = parser.parse_args(argv)
    if args.reuse_cache and not args.download:
        parser.error("--reuse-cache is only for --download")
    if args.tooldir and args.download:
        parser.error("--tooldir is only for --extract-cache")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", args.run_id):
        parser.error("use a safe single-component run-id")
    directory = args.results_dir.resolve() / args.run_id
    if within(directory, (PROJECT / "upstream").resolve()):
        parser.error("tool preparation must stay outside upstream/")
    try:
        directory.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        parser.error("run directory already exists; use a new --run-id")
    summary = {"schema_version": 1, "run_id": args.run_id, "status": "RUNNING", "started_at": utc_now(),
               "invocation": sys.argv, "scope": "fixed toolchain acquisition/extraction only; Vortex execution NOT_RUN",
               "expected_commit": TOOLCHAIN_COMMIT, "commands": [], "downloads": [], "script_sha256": sha256(__file__)}
    recorder = Recorder(directory, summary, dict(os.environ))
    code = 1
    try:
        if args.download:
            tree_path = directory / "git-tree.json"
            fetch("https://api.github.com/repos/" + REPOSITORY + "/git/trees/" + TOOLCHAIN_COMMIT + "?recursive=1", tree_path)
            tree = json.loads(tree_path.read_text(encoding="utf-8"))
            if tree.get("truncated") or not tree.get("tree"):
                raise ValueError("Git tree response is truncated or empty")
            summary["tree_sha256"] = sha256(tree_path)
            manifest = {"schema_version": "vortex-toolchain-cache-v1", "repository": REPOSITORY,
                        "commit": TOOLCHAIN_COMMIT, "osversion": "ubuntu/focal", "profile": args.profile,
                        "components": {}}
            for component, prefix in PROFILES[args.profile].items():
                entries = sorted((entry for entry in tree["tree"] if entry["path"].startswith(prefix)
                                  and entry["type"] == "blob" and ".tar.bz2" in entry["path"]),
                                 key=lambda entry: entry["path"])
                if not entries:
                    raise ValueError("no archives found for " + component)
                parts = []
                for entry in entries:
                    destination = directory / Path(entry["path"]).name
                    url = "https://raw.githubusercontent.com/" + REPOSITORY + "/" + TOOLCHAIN_COMMIT + "/" + entry["path"]
                    record = {"url": url, "path": destination.name, "git_blob_sha1": entry["sha"],
                              "expected_bytes": entry["size"], "status": "RUNNING", "started_at": utc_now()}
                    summary["downloads"].append(record)
                    recorder.save()
                    previous = args.reuse_cache / destination.name if args.reuse_cache else None
                    if previous and previous.is_file() and previous.stat().st_size == entry["size"] and blob_sha1(previous) == entry["sha"]:
                        shutil.copy2(previous, destination)
                        record["reused_from"] = str(previous.resolve())
                    else:
                        fetch_archive(url, destination, record, recorder)
                    record.update(finished_at=utc_now(), actual_bytes=destination.stat().st_size,
                                  sha256=sha256(destination), actual_git_blob_sha1=blob_sha1(destination))
                    if record["actual_bytes"] != entry["size"] or record["actual_git_blob_sha1"] != entry["sha"]:
                        record["status"] = "FAIL"
                        raise ValueError("downloaded Git blob differs: " + entry["path"])
                    record["status"] = "PASS"
                    parts.append({key: record[key] for key in ("path", "git_blob_sha1", "sha256", "actual_bytes")})
                    recorder.save()
                    print(component + ": " + destination.name + " verified", flush=True)
                archive_name = component + ".tar.bz2"
                archive = directory / archive_name
                if len(parts) == 1 and parts[0]["path"] == archive_name:
                    pass
                else:
                    with archive.open("xb") as output:
                        for part in parts:
                            with (directory / part["path"]).open("rb") as source:
                                shutil.copyfileobj(source, output, 1024 * 1024)
                manifest["components"][component] = {"parts": parts, "archive": archive_name,
                                                       "archive_sha256": sha256(archive), "archive_bytes": archive.stat().st_size}
            manifest_path = directory / "cache.json"
            manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            summary.update(cache_manifest=str(manifest_path), cache_manifest_sha256=sha256(manifest_path))
        else:
            cache = args.extract_cache.resolve()
            manifest = json.loads((cache / "cache.json").read_text(encoding="utf-8"))
            cache_components(manifest)
            summary["cache_manifest_sha256"] = sha256(cache / "cache.json")
            summary["cache"] = str(cache)
            summary["tooldir"] = str(extract_archives(recorder, manifest, cache, args.tooldir))
        summary["status"] = "PASS"
        code = 0
    except KeyboardInterrupt:
        summary.update(status="FAIL", error="interrupted")
        code = 130
    except Exception as error:
        summary.update(status="FAIL", error="{}: {}".format(type(error).__name__, error))
        for download in summary["downloads"]:
            if download["status"] == "RUNNING":
                download.update(status="FAIL", error=summary["error"], finished_at=utc_now())
    finally:
        summary["finished_at"] = utc_now()
        recorder.save()
    print(json.dumps({"status": summary["status"], "summary": str(directory / "summary.json")}, ensure_ascii=True))
    return code


if __name__ == "__main__":
    sys.exit(main())
