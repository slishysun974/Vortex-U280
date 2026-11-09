"""Build D11 runtime on the server; inspect cards without loading them (Python 3.6)."""
import base64
import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import subprocess
import tarfile
import time


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def decode(item):
    data = base64.b64decode(item["base64"], validate=True)
    if sha(data) != item["sha256"] or len(data) != item.get("bytes", len(data)):
        raise ValueError("transfer identity mismatch")
    return data


def unpack_archive(archive, destination):
    # Require a fresh extraction directory and validate every member before writing.
    with tarfile.open(str(archive), "r:gz") as tar:
        members = tar.getmembers()
        if len(members) > 1000 or sum(x.size for x in members) > 16 * 1024 * 1024:
            raise ValueError("oversize runtime package")
        names = set()
        for member in members:
            path = PurePosixPath(member.name)
            if (not member.isfile() or path.is_absolute() or ".." in path.parts or
                    len(path.parts) < 2 or path.parts[0] != "u280-runtime200-input" or
                    "\\" in member.name or ":" in member.name or
                    path.as_posix() != member.name or member.name in names):
                raise ValueError("unsafe/duplicate runtime archive member")
            names.add(member.name)
        if any(parent.as_posix() in names for name in names for parent in PurePosixPath(name).parents):
            raise ValueError("file/directory collision")
        destination.mkdir(mode=0o700, exist_ok=False)
        for member in members:
            target = destination / member.name
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with target.open("xb") as out, tar.extractfile(member) as src:
                out.write(src.read())
    return destination / "u280-runtime200-input"


def validate_result(build, result, binding):
    if (result.get("status") != "PASS" or result.get("exit_code") != 0 or
            result.get("stub_only") is not False or result.get("xrt_backend") != "PASS" or
            result.get("binding") != binding):
        raise ValueError("real XRT runtime compile did not pass")
    artifacts = result.get("artifacts", [])
    if len(artifacts) != 2 or {a["path"] for a in artifacts} != {"lib/libvortex.so", "lib/libvortex-xrt.so"}:
        raise ValueError("both runtime libraries required")
    commands = result.get("commands", [])
    required = {"compiler", "glibc", "stub", "xrt", "ldd_libvortex", "ldd_libvortex-xrt"}
    if (len(commands) != len(required) or {c["label"] for c in commands} != required or
            any(c.get("exit_code") != 0 or c.get("timed_out") for c in commands)):
        raise ValueError("incomplete compile/dependency evidence")
    for item in artifacts:
        path = build / item["path"]
        if path.is_symlink() or path.stat().st_size != item["bytes"] or sha(path.read_bytes()) != item["sha256"]:
            raise ValueError("runtime artifact mismatch")


def collect(bundle):
    import pwd
    account = pwd.getpwuid(os.getuid())
    run_id = bundle["run_id"]
    if (account.pw_name != "u280user" or bundle["schema_version"] != "u280-runtime-request-v1" or
            not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", run_id)):
        raise ValueError("unexpected account/request")
    package, inspection = decode(bundle["package"]), decode(bundle["inspection"])
    root = Path(account.pw_dir).resolve() / "vortex-u280-runtime"
    if root.is_symlink():
        raise ValueError("symlink runtime root")
    root.mkdir(mode=0o700, exist_ok=True)
    work = root / run_id
    work.mkdir(mode=0o700, exist_ok=False)
    build = work / "build"
    result = dict(schema_version="u280-server-runtime-v1", run_id=run_id, nonce=bundle["nonce"],
        status="RUNNING", runtime_status="NOT_RUN", inspection_status="NOT_RUN", commands=[], files={},
        started_at=datetime.datetime.now(datetime.timezone.utc).isoformat(), remote_work_directory=str(work),
        package_sha256=sha(package), status_scope="server host-library compilation and read-only platform inspection",
        board_load="NOT_RUN", board_execution="NOT_RUN", host_configuration="NOT_RUN")
    archive = work / "u280-runtime200-input.tar.gz"
    archive.write_bytes(package)
    try:
        source = unpack_archive(archive, work / "input")
        for name, key in (("binding.json", "binding_sha256"), ("manifest.json", "manifest_sha256")):
            if sha((source / name).read_bytes()) != bundle[key]:
                raise ValueError("accepted runtime identity mismatch")
        binding = json.loads((source / "binding.json").read_text())
        # The immutable packaged builder enforces a 300-second timeout per command,
        # two CPU affinity, nice +10, and kills its own child process groups.
        build_argv = ["python3", "-B", str(source / "build_runtime.py"), "--input", str(source),
                      "--output", str(build), "--cxx", "/opt/rh/devtoolset-9/root/usr/bin/g++"]
        argv = ["bash", "-c", ". /opt/xilinx/xrt/setup.sh >/dev/null && exec " +
                " ".join(shlex.quote(arg) for arg in build_argv)]
        rec = dict(label="runtime", argv=argv, cwd=str(work))
        result["commands"].append(rec)
        begin = time.monotonic()
        with (work / "runtime.stdout").open("xb") as out, (work / "runtime.stderr").open("xb") as err:
            proc = subprocess.run(argv, cwd=str(work), stdout=out, stderr=err)
        rec.update(exit_code=proc.returncode, elapsed_seconds=round(time.monotonic() - begin, 3))
        if (build / "result.json").is_file():
            result["runtime_result"] = json.loads((build / "result.json").read_text())
        validate_result(build, result.get("runtime_result", {}), binding)
        if proc.returncode:
            raise ValueError("runtime builder exited nonzero")
        result["runtime_status"] = "PASS"
    except Exception as exc:
        result.update(runtime_status="FAIL", runtime_error=repr(exc))
    try:
        namespace = {"__name__": "u280_read_only_inspection"}
        exec(compile(inspection, "u280_remote_probe.py", "exec"), namespace)
        observed = namespace["collect"](dict(run_id=run_id, nonce=bundle["nonce"],
            probe_kind="host-platform", source_commit=bundle["source_commit"], files={}))
        for name, item in observed.pop("files", {}).items():
            result["files"]["inspection/" + name] = item
        result.update(inspection=observed, inspection_status=observed["status"])
    except Exception as exc:
        result.update(inspection_status="FAIL", inspection_error=repr(exc))
    paths = [("transport/" + p.name, p) for p in work.glob("*.stdout")]
    paths += [("transport/" + p.name, p) for p in work.glob("*.stderr")]
    paths += [("runtime/" + p.relative_to(build).as_posix(), p) for p in build.rglob("*")
              if p.is_file() and (p.suffix in (".stdout", ".stderr", ".so") or p.name == "result.json")]
    for name, path in paths:
        data = path.read_bytes()
        item = dict(bytes=len(data), sha256=sha(data))
        if len(data) <= 8 * 1024 * 1024:
            item["base64"] = base64.b64encode(data).decode("ascii")
        else:
            item["not_returned"] = "over 8 MiB; retained on server"
        result["files"][name] = item
    result["status"] = "PASS" if result["runtime_status"] == result["inspection_status"] == "PASS" else "FAIL"
    result["finished_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    (work / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    return result
