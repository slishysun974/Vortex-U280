"""Start or observe one authorized, detached U280 link job (Python 3.6)."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import time

WORKER = r'''import datetime, json, os, subprocess, sys
from pathlib import Path
job = Path(sys.argv[1])
lock_fd = int(sys.argv[2])
request = json.loads((job / "request.json").read_text())
state = dict(status="RUNNING", pid=os.getpid(), argv=request["argv"],
             started_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
def save():
    (job / "worker.tmp").write_text(json.dumps(state, indent=2) + "\n")
    os.replace(str(job / "worker.tmp"), str(job / "worker.json"))
save()
try:
    with (job / "build.stdout").open("xb") as out, (job / "build.stderr").open("xb") as err:
        process = subprocess.Popen(request["argv"], cwd=str(job), stdin=subprocess.DEVNULL,
                                   stdout=out, stderr=err)
        state["builder_pid"] = process.pid
        save()
        code = process.wait()
    path = Path(request["build_directory"]) / "result.json"
    build = json.loads(path.read_text()) if path.is_file() else {}
    state.update(exit_code=code, status="PASS" if code == 0 and build.get("status") == "PASS" else "FAIL")
except Exception as exc:
    state.update(status="FAIL", error=repr(exc), exit_code=1)
state["finished_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
save()
os.close(lock_fd)
'''


def sha(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def resource_gate(meminfo, disk_free):
    match = re.search(r"^MemAvailable:\s+(\d+) kB$", meminfo, re.M)
    available = int(match.group(1)) * 1024 if match else None
    return dict(available_memory_bytes=available, free_disk_bytes=disk_free,
                minimum_memory_bytes=64 * 1024 ** 3, minimum_disk_bytes=50 * 1024 ** 3,
                pass_minimums=available is not None and available >= 64 * 1024 ** 3 and disk_free >= 50 * 1024 ** 3,
                memory_hard_limit="NOT_ENFORCED; user approved this plan")


def collect(bundle):
    import fcntl
    import pwd
    account = pwd.getpwuid(os.getuid())
    if account.pw_name != "u280user":
        raise ValueError("unexpected remote account")
    for key in ("run_id", "build_run", "xo_run"):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", bundle[key]):
            raise ValueError("unsafe run id")
    if bundle["mode"] not in ("start", "status"):
        raise ValueError("unknown mode")
    account_home = Path(account.pw_dir).resolve()
    root = account_home / "vortex-u280-link-jobs"
    if root.is_symlink():
        raise ValueError("symlink job root")
    root.mkdir(mode=0o700, exist_ok=True)
    job = root / bundle["build_run"]
    build = account_home / "vortex-u280-builds" / bundle["build_run"]
    if job.is_symlink() or build.is_symlink():
        raise ValueError("symlink run directory")
    result = dict(schema_version="u280-link-control-v1", run_id=bundle["run_id"], nonce=bundle["nonce"],
        mode=bundle["mode"], build_run=bundle["build_run"], job_directory=str(job), build_directory=str(build),
        status="RUNNING", files={}, commands=[], board_load="NOT_RUN", host_configuration="NOT_RUN")
    if bundle["mode"] == "start":
        if not bundle.get("authorized"):
            raise ValueError("link authorization missing")
        lock_file = (root / "active.lock").open("a+")
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock_file.close()
            raise ValueError("another project link worker is active; observe it instead")
        created = False
        try:
            if job.exists() or build.exists():
                raise ValueError("run already exists; do not restart or overwrite")
            job.mkdir(mode=0o700)
            created = True
            previous = account_home / "vortex-u280-builds" / bundle["xo_run"]
            inputs = account_home / "vortex-u280-probes" / bundle["xo_run"]
            builder = inputs / "build_prepared.py"
            if sha(builder) != bundle["builder_sha256"]:
                raise ValueError("remote builder identity differs from tested D9 script")
            api = runpy.run_path(str(builder))
            cfg, identity = api["validate_input"](inputs / "u280-rtl-input")
            identity.update(build_flow="ip-ooc-v1", flow_sha256=bundle["flow_sha256"])
            if any(identity[k] != v for k, v in bundle["input_identity"].items()):
                raise ValueError("prepared source identity mismatch")
            xo = api["validate_xo"](previous, identity)
            if sha(xo) != bundle["xo_sha256"]:
                raise ValueError("XO differs from accepted D9 artifact")
            result["validated_identity"] = dict(identity, builder_sha256=sha(builder), xo_sha256=sha(xo))
            result["platform_files"] = []
            for item in bundle["platform_files"]:
                path = Path(item["path"])
                actual = dict(path=str(path), sha256=sha(path), bytes=path.stat().st_size)
                if actual != item:
                    raise ValueError("platform files changed since successful XO")
                result["platform_files"].append(actual)
            for label, argv in (("identity", ["id", "-un"]), ("hostname", ["hostname"]),
                                ("uptime", ["uptime"]), ("memory", ["free", "-h"]),
                                ("disk", ["df", "-h", str(account_home)])):
                output = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
                (job / (label + ".stdout")).write_bytes(output.stdout)
                (job / (label + ".stderr")).write_bytes(output.stderr)
                result["commands"].append(dict(label=label, argv=argv, exit_code=output.returncode))
                if output.returncode != 0:
                    raise ValueError("resource inspection command failed: " + label)
            result["resources"] = resource_gate(Path("/proc/meminfo").read_text(), shutil.disk_usage(str(account_home)).free)
            if not result["resources"]["pass_minimums"]:
                result.update(status="BLOCKED", reason="available memory or disk below approved starting budget")
            else:
                argv = ["python3", "-B", str(builder), "--input", str(inputs / "u280-rtl-input"),
                        "--run-id", bundle["build_run"], "--stage", "link", "--build-flow", "ip-ooc-v1",
                        "--xo-run", str(previous)]
                request = dict(argv=argv, build_directory=str(build), authorization=bundle["authorization"],
                               validated_identity=result["validated_identity"], resources=result["resources"])
                (job / "request.json").write_text(json.dumps(request, indent=2) + "\n")
                (job / "worker.py").write_text(WORKER)
                with (job / "supervisor.stdout").open("xb") as out, (job / "supervisor.stderr").open("xb") as err:
                    worker = subprocess.Popen(["python3", "-B", str(job / "worker.py"), str(job), str(lock_file.fileno())],
                        cwd=str(job), stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                        start_new_session=True, pass_fds=(lock_file.fileno(),))
                result.update(worker_pid=worker.pid, status="PASS", status_scope="detached job accepted; not build completion")
                for _ in range(30):
                    if (job / "worker.json").is_file():
                        state = json.loads((job / "worker.json").read_text())
                        if state["status"] != "RUNNING" or (build / "link.stdout").exists():
                            break
                    time.sleep(1)
        except Exception as exc:
            if not created:
                raise
            result.update(status="FAIL", error=repr(exc))
        finally:
            lock_file.close()  # The detached worker retains the same flock descriptor.
            if created:
                (job / "launch.json").write_text(json.dumps(result, indent=2) + "\n")
    else:
        if not job.is_dir():
            raise ValueError("unknown job; status never starts a new build")
        result.update(status="PASS", status_scope="read-only job observation; see build_status")
    if (job / "worker.json").is_file():
        result["worker"] = json.loads((job / "worker.json").read_text())
        result["build_status"] = result["worker"]["status"]
        worker_pid = result["worker"]["pid"]
        alive = subprocess.run(["ps", "-o", "pid,ppid,stat,etime,args", "-p", str(worker_pid)],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
        result["worker_process"] = dict(exit_code=alive.returncode, stdout=alive.stdout.decode("utf-8", "replace"))
        if result["build_status"] == "RUNNING" and alive.returncode != 0:
            result["build_status"] = "UNCONFIRMED"
            result["observation_warning"] = "worker state says RUNNING but worker process is absent"
        pid = result["worker"].get("builder_pid")
        if pid:
            query = subprocess.run(["ps", "-o", "pid,ppid,stat,etime,args", "--ppid", str(pid)],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
            result["builder_children"] = dict(exit_code=query.returncode, stdout=query.stdout.decode("utf-8", "replace"))
    else:
        result["build_status"] = "NOT_RUN" if result["status"] in ("BLOCKED", "FAIL") else "UNCONFIRMED"
    if (build / "result.json").is_file():
        result["build_result"] = json.loads((build / "result.json").read_text())
    for prefix, folder, names in (
        ("job", job, ("launch.json", "request.json", "worker.json", "worker.py", "build.stdout", "build.stderr",
                      "supervisor.stderr", "identity.stdout", "hostname.stdout", "uptime.stdout", "memory.stdout", "disk.stdout")),
        ("build", build, ("result.json", "platform.stdout", "platform.stderr", "link.stdout", "link.stderr",
                          "clock_check.stdout", "clock_check.stderr", "flow_patch.json", "flow.patch"))):
        for name in names:
            path = folder / name
            if path.is_file():
                raw = path.read_bytes()
                item = dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
                if len(raw) <= 4 * 1024 * 1024:
                    item["base64"] = base64.b64encode(raw).decode("ascii")
                else:
                    item["not_returned"] = "over 4 MiB; retained remotely"
                result["files"][prefix + "/" + name] = item
    return result
