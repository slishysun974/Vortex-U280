"""Archive completed link artifacts without altering the build or opening a card."""
import base64
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import tarfile
import time


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def checked_file(root, path):
    path.relative_to(root)
    current = path
    while current != root:
        if current.is_symlink():
            raise ValueError("symlink archive input: " + str(path))
        current = current.parent
    if root.is_symlink() or not path.is_file():
        raise ValueError("non-regular archive input: " + str(path))
    path.resolve().relative_to(root.resolve())
    return path


def validate_build(build, bundle):
    record = checked_file(build, build / "result.json")
    if digest(record) != bundle["accepted_result_sha256"]:
        raise ValueError("completed build result changed")
    result = json.loads(record.read_text())
    if result.get("status") != "PASS" or result.get("exit_code") != 0 or result.get("stage") != "link":
        raise ValueError("completed successful link required")
    if result.get("artifact") != bundle["artifact"]:
        raise ValueError("artifact identity differs")
    artifact = checked_file(build, build / "out/vortex_afu.xclbin")
    if (bundle["artifact"]["path"] != "out/vortex_afu.xclbin" or
            artifact.stat().st_size != bundle["artifact"]["bytes"] or
            digest(artifact) != bundle["artifact"]["sha256"]):
        raise ValueError("xclbin identity mismatch")
    return artifact


def collect(bundle):
    import pwd
    account = pwd.getpwuid(os.getuid())
    if account.pw_name != "u280user" or bundle["mode"] != "archive":
        raise ValueError("unexpected account or mode")
    for key in ("run_id", "build_run"):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", bundle[key]):
            raise ValueError("unsafe run id")
    home = Path(account.pw_dir).resolve()
    build_root = home / "vortex-u280-builds"
    if build_root.is_symlink():
        raise ValueError("symlink build root")
    build = build_root / bundle["build_run"]
    artifact = validate_build(build, bundle)
    root = home / "vortex-u280-archives"
    if root.is_symlink():
        raise ValueError("symlink archive root")
    root.mkdir(mode=0o700, exist_ok=True)
    work = root / bundle["run_id"]
    work.mkdir(mode=0o700, exist_ok=False)
    result = dict(schema_version="u280-link-archive-v1", run_id=bundle["run_id"], nonce=bundle["nonce"],
        build_run=bundle["build_run"], build_status="PASS", status="RUNNING", files={}, commands=[],
        status_scope="archive transport and metadata extraction only; review and hardware execution separate",
        board_load="NOT_RUN", host_configuration="NOT_RUN", board_execution="NOT_RUN",
        remote_work_directory=str(work), started_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
    setup = ". /apps/Xilinx2023/Vitis/2023.1/settings64.sh >/dev/null && . /opt/xilinx/xrt/setup.sh >/dev/null && exec "

    def command(label, argv, vendor=False):
        if vendor:
            argv = ["bash", "-c", setup + " ".join(shlex.quote(str(v)) for v in argv)]
        start = time.monotonic()
        record = dict(label=label, argv=argv, cwd=str(work), timeout_seconds=60, timed_out=False)
        with (work / (label + ".stdout")).open("xb") as out, (work / (label + ".stderr")).open("xb") as err:
            try:
                p = subprocess.run(argv, cwd=str(work), stdout=out, stderr=err, timeout=60)
                record["exit_code"] = p.returncode
            except subprocess.TimeoutExpired:
                record.update(exit_code=None, timed_out=True)
            except OSError as exc:
                record.update(exit_code=None, error=repr(exc))
        record["elapsed_seconds"] = round(time.monotonic() - start, 3)
        result["commands"].append(record)
        return record.get("exit_code") == 0

    try:
        ok = command("xclbin_info", ["xclbinutil", "--input", artifact, "--info"], vendor=True)
        sections = [("CLOCK_FREQ_TOPOLOGY", "JSON"), ("MEM_TOPOLOGY", "JSON"),
                    ("CONNECTIVITY", "JSON"), ("IP_LAYOUT", "JSON"),
                    ("BUILD_METADATA", "JSON"), ("PARTITION_METADATA", "JSON"),
                    ("EMBEDDED_METADATA", "RAW")]
        for name, fmt in sections:
            output = name.lower() + (".xml" if fmt == "RAW" else ".json")
            passed = command(name.lower(), ["xclbinutil", "--input", artifact,
                "--dump-section", name + ":" + fmt + ":" + str(work / output)], vendor=True)
            ok = passed and ok
        command("compiler_default", ["g++", "--version"])
        for version in (7, 8, 9):
            compiler = Path("/opt/rh/devtoolset-%d/root/usr/bin/g++" % version)
            if compiler.is_file():
                command("compiler_devtoolset%d" % version, [str(compiler), "--version"])
        command("glibc", ["getconf", "GNU_LIBC_VERSION"])
        command("xrt_version", ["/opt/xilinx/xrt/bin/xbutil", "--version"])
        result["xrt_headers"] = []
        for name in ("xrt_bo.h", "xrt_device.h", "xrt_error.h", "xrt_ip.h", "xrt_kernel.h", "xrt_xclbin.h"):
            path = Path("/opt/xilinx/xrt/include/experimental") / name
            result["xrt_headers"].append(dict(path=str(path), exists=path.is_file(),
                sha256=digest(path) if path.is_file() else None))
        selected = {"build/" + n: checked_file(build, build / n) for n in
                    ("result.json", "input_manifest.json", "flow_patch.json", "flow.patch", "link.stdout",
                     "link.stderr", "clock_check.stdout", "clock_check.stderr")}
        selected["artifacts/vortex_afu.xclbin"] = artifact
        reports = build / "out/_x/reports"
        if not reports.is_dir():
            raise ValueError("missing report directory")
        report_paths = []
        result["report_inventory"] = []
        for path in sorted(reports.rglob("*")):
            if path.is_file():
                checked_file(build, path)
                report_paths.append(path)
                result["report_inventory"].append(dict(path=path.relative_to(reports).as_posix(),
                    bytes=path.stat().st_size, sha256=digest(path)))
        result["report_count"] = len(report_paths)
        result["report_uncompressed_bytes"] = sum(p.stat().st_size for p in report_paths)
        if not result["report_count"]:
            raise ValueError("empty report directory")
        if result["report_uncompressed_bytes"] > 2 * 1024 ** 3:
            raise ValueError("reports exceed 2 GiB uncompressed bound")
        # Preserve the complete report set while bounding wire size, not redundant text.
        with tarfile.open(str(work / "reports.tar.gz"), "w:gz") as tar:
            for path in report_paths:
                tar.add(str(path), arcname=path.relative_to(reports).as_posix(), recursive=False)
        for path in sorted(work.iterdir()):
            if path.is_file():
                selected["inspection/" + path.name] = checked_file(work, path)
        total = sum(p.stat().st_size for p in selected.values())
        result["transport_bytes"] = total
        if total > 192 * 1024 ** 2:
            raise ValueError("archive exceeds 192 MiB bounded transport")
        for name, path in sorted(selected.items()):
            raw = path.read_bytes()
            result["files"][name] = dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
                base64=base64.b64encode(raw).decode("ascii"))
        validate_build(build, bundle)
        result.update(status="PASS" if ok else "FAIL", archived_bytes=total,
                      metadata_extraction="PASS" if ok else "FAIL")
    except Exception as exc:
        result.update(status="FAIL", error=repr(exc))
    result["finished_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    metadata = dict(result, files={n: {k: v for k, v in item.items() if k != "base64"}
                                 for n, item in result["files"].items()})
    (work / "result.json").write_text(json.dumps(metadata, indent=2) + "\n")
    return result
