"""Transfer verified D8 RTL and run only the bounded XO stage (Python 3.6)."""
import base64
import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import signal
import subprocess
import tarfile
import time


def sha(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def unpack_archive(archive, work):
    with tarfile.open(str(archive), "r:gz") as tar:
        members = tar.getmembers()
        names = set()
        if sum(x.size for x in members) > 64 * 1024 * 1024:
            raise ValueError("oversize source input")
        for member in members:
            path = PurePosixPath(member.name)
            if (path.is_absolute() or ".." in path.parts or not path.parts or
                    path.parts[0] != "u280-rtl-input" or "\\" in member.name or
                    ":" in member.name or path.as_posix() != member.name or
                    member.name in names or not (member.isfile() or member.isdir())):
                raise ValueError("unsafe/duplicate archive member")
            names.add(member.name)
        for member in members:
            destination = work.joinpath(*PurePosixPath(member.name).parts)
            if member.isdir():
                destination.mkdir(mode=0o700, parents=True, exist_ok=True)
            else:
                destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                with destination.open("xb") as out, tar.extractfile(member) as src:
                    out.write(src.read())


def collect(bundle):
    import pwd
    run_id = bundle["run_id"]
    if bundle["probe_kind"] != "xo" or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", run_id):
        raise ValueError("invalid XO request")
    account = pwd.getpwuid(os.getuid())
    if account.pw_name != "u280user":
        raise ValueError("unexpected remote account")
    root = Path(account.pw_dir).resolve() / "vortex-u280-probes"
    if root.is_symlink():
        raise ValueError("symlink work root")
    root.mkdir(mode=0o700, exist_ok=True)
    work = root / run_id
    work.mkdir(mode=0o700, exist_ok=False)
    build = Path(account.pw_dir).resolve() / "vortex-u280-builds" / run_id
    result = dict(schema_version="u280-xo-transport-v1", run_id=run_id, nonce=bundle["nonce"],
        started_at=datetime.datetime.now(datetime.timezone.utc).isoformat(), probe_kind="xo",
        status="RUNNING", commands=[], files={}, remote_work_directory=str(work),
        build_directory=str(build), platform_evidence=bundle["platform_evidence"],
        board_programming="NOT_RUN", board_execution="NOT_RUN", host_configuration="NOT_RUN",
        full_synthesis="NOT_RUN", implementation="NOT_RUN")
    try:
        if build.exists():
            raise ValueError("build run already exists")
        if set(bundle["files"]) != {"u280-rtl-input.tar.gz", "build_prepared.py"}:
            raise ValueError("unexpected transfer files")
        for name, item in bundle["files"].items():
            raw = base64.b64decode(item["base64"], validate=True)
            if hashlib.sha256(raw).hexdigest() != item["sha256"]:
                raise ValueError("transfer digest mismatch")
            with (work / name).open("xb") as stream:
                stream.write(raw)
        result["platform_identity"] = []
        for item in bundle["platform_files"]:
            path = Path(item["path"])
            actual = dict(path=str(path), sha256=sha(path), bytes=path.stat().st_size)
            result["platform_identity"].append(actual)
            if actual != item:
                raise ValueError("installed platform changed since preflight")
        unpack_archive(work / "u280-rtl-input.tar.gz", work)
        argv = ["python3", "-B", str(work / "build_prepared.py"), "--input",
                str(work / "u280-rtl-input"), "--run-id", run_id, "--stage", "xo",
                "--build-flow", bundle["build_flow"]]
        rec = dict(argv=argv, cwd=str(work), timeout_seconds=1020, timed_out=False, returncode=None)
        result["commands"].append(rec)
        started = time.monotonic()
        with (work / "build.stdout").open("xb") as out, (work / "build.stderr").open("xb") as err:
            proc = subprocess.Popen(argv, cwd=str(work), stdout=out, stderr=err, start_new_session=True)
            try:
                proc.wait(timeout=1020)
            except subprocess.TimeoutExpired:
                rec["timed_out"] = True
                # The wrapper owns the vendor process group and its shorter timeout.
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
            rec.update(returncode=proc.returncode, elapsed_seconds=round(time.monotonic() - started, 3))
        if (build / "result.json").is_file():
            result["build_result"] = json.loads((build / "result.json").read_text())
        result["status"] = "PASS" if (rec["returncode"] == 0 and not rec["timed_out"] and
            result.get("build_result", {}).get("status") == "PASS") else "FAIL"
    except Exception as exc:
        result.update(status="FAIL", error=repr(exc))
    for prefix, folder, names in (
        ("transport", work, ("build.stdout", "build.stderr")),
        ("build", build, ("result.json", "input_manifest.json", "build_prepared.py", "bounded_xo.tcl",
                          "platform.stdout", "platform.stderr", "xo.stdout", "xo.stderr", "vivado.log", "vivado.jou",
                          "flow_patch.json", "flow.patch"))):
        for name in names:
            path = folder / name
            if path.is_file():
                data = path.read_bytes()
                item = dict(sha256=hashlib.sha256(data).hexdigest(), bytes=len(data))
                if len(data) <= 4 * 1024 * 1024:
                    item["base64"] = base64.b64encode(data).decode("ascii")
                else:
                    item["not_returned"] = "over 4 MiB; retained on server"
                result["files"][prefix + "/" + name] = item
    result["ip_files"] = [dict(path=str(p.relative_to(build)), bytes=p.stat().st_size, sha256=sha(p))
                          for p in sorted((build / "out/ip").rglob("*"))
                          if p.is_file() and (p.suffix in (".xci", ".dcp") or "stub" in p.name)]
    result["finished_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    (work / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    return result
