"""D13: interactive HOST setup plus read-only DCP audit; server Python 3.6."""
import base64
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import time
import zipfile

BUILD = "/home/course/u280user/vortex-u280-builds/u280-link-20261109-103830-671"
XCLBIN_SHA = "bbac2ab73073b24ba857fb34eadf22bf1c11dc745527f064c4eec61b70d2c843"
XSA = "/opt/xilinx/platforms/xilinx_u280_gen3x16_xdma_1_202211_1/hw/hw.xsa"
XSA_SHA = "11c9e4acdfdb6e98e136df84c4af806d1d01a8d69a8e0c7b20477a6692010c91"
TIMING7_FINAL_SHA = "4942bb1979f74e60bbbd8d20ce9779ec1cdee675d2a3217453e505ac4cd26c19"
TIMING7_BASELINE_SHA = "f5cee615c973ebd572f85ce6d412edbf273115b8f7b061874d286caa3408bcf3"
INTERFACE_UUID = "fb2b2c5a19ed63593fea95f51fbc8eb9"
BDFS = ["0000:" + b + ":00.1" for b in ("b1", "b4", "b5", "3d", "3e", "40", "41", "b2")]


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as src:
        for block in iter(lambda: src.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def idle(snapshot):
    """Fail closed when a critical attribute is missing, malformed, or busy."""
    if snapshot.get("driver") != "xocl" or snapshot.get("ready", "").strip() != "0x1":
        return False
    if snapshot.get("interface_uuids", "").strip().replace("-", "") != INTERFACE_UUID:
        return False
    if not snapshot.get("device_nodes"):
        return False
    text = snapshot.get("kdsstat", "")
    for label in ("outstanding execs", "contexts"):
        rows = re.findall(r"(?m)^" + label + r":\s*([^\n]*)$", text)
        if len(rows) != 1 or rows[0].strip() != "0":
            return False
    clients = re.findall(r"(?m)^client pid:[ \t]*([^\n]*)$", text)
    return len(clients) == 1 and not clients[0].strip()


def snapshot(bdf):
    if bdf not in BDFS:
        raise ValueError("unapproved BDF")
    root = Path("/sys/bus/pci/devices") / bdf
    item = dict(bdf=bdf, observed_at=now(), device_nodes=[])
    item["driver"] = (root / "driver").resolve().name
    for name in ("ready", "kdsstat", "interface_uuids", "xclbinuuid", "host_mem_size"):
        try:
            item[name] = (root / name).read_text()
        except OSError as exc:
            item[name + "_error"] = str(exc)
    item["device_nodes"] = ["/dev/dri/" + p.name for p in sorted((root / "drm").glob("renderD*"))]
    return item


def select_final(paths):
    # Exact top-level checkpoint names only; never choose an IP/OOC DCP or mtime.
    for name in ("level0_wrapper_postroute_physopt.dcp", "level0_wrapper_routed.dcp",
                 "hw_bb_locked_postroute_physopt.dcp", "hw_bb_locked_postroute_physopted.dcp",
                 "hw_bb_locked_routed.dcp"):
        found = [p for p in paths if p.name == name and p.parent.name == "impl_1"]
        if len(found) > 1:
            raise ValueError("ambiguous final checkpoint: " + name)
        if found:
            return found[0]
    raise ValueError("no recognized final checkpoint; inspect dcp_inventory.json")


def run_command(work, result, label, argv, timeout=120, limited=False):
    record = dict(label=label, argv=argv, started_at=now(), timeout_seconds=timeout)
    result["commands"].append(record)
    def restrict():
        cpus = sorted(os.sched_getaffinity(0))[:2]
        os.sched_setaffinity(0, cpus)
        os.nice(10)
    begin = time.monotonic()
    with (work / (label + ".stdout")).open("xb") as out, (work / (label + ".stderr")).open("xb") as err:
        proc = subprocess.Popen(argv, cwd=str(work), stdout=out, stderr=err,
                                start_new_session=True, preexec_fn=restrict if limited else None)
        try:
            record["exit_code"] = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
            record.update(exit_code=proc.returncode, timed_out=True)
    record["elapsed_seconds"] = round(time.monotonic() - begin, 3)
    return record["exit_code"]


def configure_host(work, result):
    observations = [snapshot(bdf) for bdf in BDFS]
    result["initial_devices"] = observations
    eligible = [x for x in observations if idle(x)]
    if not eligible:
        raise RuntimeError("no ready idle card with matching shell")
    print("HOST preparation requires sudo authentication in this terminal; no password is recorded.", flush=True)
    # Inherit the real TTY. Never pipe or log this authentication conversation.
    auth = subprocess.call(["sudo", "-v"])
    result["sudo_authentication"] = dict(argv=["sudo", "-v"], exit_code=auth, session_recorded=False)
    if auth:
        raise RuntimeError("sudo authentication/policy not available")
    fuser = shutil.which("fuser") or next((x for x in ("/usr/sbin/fuser", "/sbin/fuser", "/usr/bin/fuser") if Path(x).is_file()), None)
    if not fuser:
        raise RuntimeError("privileged holder check unavailable")
    selected = None
    result["selection_checks"] = []
    for candidate in eligible:
        bdf = candidate["bdf"]
        before = snapshot(bdf)
        if not idle(before):
            continue
        label = "holders_" + bdf.replace(":", "_").replace(".", "_")
        rc = run_command(work, result, label, ["sudo", "-n", fuser, "-v"] + before["device_nodes"], 15)
        stdout = (work / (label + ".stdout")).read_text()
        stderr = (work / (label + ".stderr")).read_text()
        after = snapshot(bdf)
        accepted = rc == 1 and not stdout.strip() and not stderr.strip() and idle(after)
        result["selection_checks"].append(dict(before=before, after=after, holder_exit_code=rc, accepted=accepted))
        if accepted:
            selected = after
            break
    if selected is None:
        raise RuntimeError("no card passed privileged holder and immediate idle checks")
    result["selected_device"] = selected["bdf"]
    result["reservation"] = "No exclusive XRT reservation; immediate idle checks only; recheck before every later load."
    existing = selected.get("host_mem_size", "").strip()
    if existing != "0":
        result["host_configuration"] = "EXISTING_UNCHANGED"
        raise RuntimeError("nonzero HOST reservation preserved; inspect capacity before reuse")
    # No other work between the final idle snapshot and configuration.
    rc = run_command(work, result, "host_enable", ["sudo", "-n", "/opt/xilinx/xrt/bin/xbutil",
        "configure", "--device", selected["bdf"], "--host-mem", "enable", "--size", "256M"], 120)
    result["after_host_configuration"] = snapshot(selected["bdf"])
    result["host_configuration"] = "COMMAND_PASS" if rc == 0 else "FAIL"
    setup = ". /opt/xilinx/xrt/setup.sh >/dev/null && exec "
    report_argv = ["/opt/xilinx/xrt/bin/xbutil", "examine", "--device", selected["bdf"],
                   "--report", "platform", "memory", "pcie-info", "dynamic-regions", "--format", "JSON", "--output", "host_after.json"]
    query = run_command(work, result, "host_readback", ["bash", "-c", setup + " ".join(shlex.quote(x) for x in report_argv)])
    if rc or query:
        raise RuntimeError("HOST configuration/readback command failed")
    # Store raw units verbatim. Capacity acceptance is reviewed against XRT JSON,
    # not inferred from an undocumented sysfs unit.
    result["host_configuration"] = "CONFIGURED_PENDING_CAPACITY_REVIEW"


def audit(work, result, tcl):
    xclbin = Path(BUILD) / "out/vortex_afu.xclbin"
    if digest(xclbin) != XCLBIN_SHA or digest(Path(XSA)) != XSA_SHA:
        raise ValueError("D10 xclbin/platform identity mismatch")
    result["inputs"] = dict(xclbin=dict(path=str(xclbin), sha256=XCLBIN_SHA), xsa=dict(path=XSA, sha256=XSA_SHA))
    paths = sorted(Path(BUILD).rglob("*.dcp"))
    inventory = [dict(path=str(p), bytes=p.stat().st_size) for p in paths]
    (work / "dcp_inventory.json").write_text(json.dumps(inventory, indent=2))
    final = select_final(paths)
    result["final_checkpoint"] = dict(path=str(final), bytes=final.stat().st_size, sha256=digest(final))
    base = work / "platform"
    base.mkdir()
    with zipfile.ZipFile(XSA) as archive:
        for name in ("hw_bb_locked.dcp", "tcl_hooks/prelink.tcl", "tcl_hooks/postlink.tcl",
                     "tcl_hooks/preopt.tcl", "tcl_hooks/postopt.tcl", "tcl_hooks/postroute.tcl", "tcl_hooks/impl.xdc"):
            raw = archive.read(name)
            dest = base / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(raw)
    result["baseline_checkpoint"] = dict(path=str(base / "hw_bb_locked.dcp"), sha256=digest(base / "hw_bb_locked.dcp"))
    if result.get("timing7") and (result["final_checkpoint"]["sha256"] != TIMING7_FINAL_SHA or
                                  result["baseline_checkpoint"]["sha256"] != TIMING7_BASELINE_SHA):
        raise ValueError("TIMING-7 checkpoint differs from the archived D13 identity")
    (work / "audit.tcl").write_bytes(tcl)
    results = []
    for label, dcp in (("implemented", final), ("baseline", base / "hw_bb_locked.dcp")):
        print("Reading " + label + " DCP (two CPUs, nice +10, 900 s limit).", flush=True)
        argv = ["vivado", "-mode", "batch", "-nojournal", "-log", str(work / (label + ".log")),
                "-source", str(work / "audit.tcl"), "-tclargs", str(dcp), str(work / label)]
        rc = run_command(work, result, label, ["bash", "-c", ". /apps/Xilinx2023/Vitis/2023.1/settings64.sh >/dev/null && exec " +
                         " ".join(shlex.quote(x) for x in argv)], 900, True)
        results.append(rc)
    result["timing_collection"] = "PASS" if all(x == 0 for x in results) else "FAIL"


def main(bundle):
    import pwd
    account = pwd.getpwuid(os.getuid())
    run_id = bundle["run_id"]
    if bundle.get("timing7") and bundle.get("configure_host", True):
        raise ValueError("TIMING-7 evidence collection requires timing-only mode")
    if account.pw_name != "u280user" or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", run_id):
        raise ValueError("unexpected account/run id")
    parent = Path(account.pw_dir) / "vortex-u280-readiness"
    if parent.is_symlink():
        raise ValueError("symlink work root")
    parent.mkdir(mode=0o700, exist_ok=True)
    work = parent / run_id
    work.mkdir(mode=0o700, exist_ok=False)
    raw_tcl = base64.b64decode(bundle["tcl_base64"], validate=True)
    if hashlib.sha256(raw_tcl).hexdigest() != bundle["tcl_sha256"]:
        raise ValueError("Tcl identity mismatch")
    result = dict(schema_version="u280-readiness-v1", run_id=run_id, nonce=bundle["nonce"],
        remote_probe_sha256=bundle["remote_probe_sha256"], status="RUNNING", commands=[], files={},
        started_at=now(), board_load="NOT_RUN", board_execution="NOT_RUN", warnings_disposition="OPEN",
        host_configuration="NOT_RUN", timing_collection="NOT_RUN", timing7=bundle.get("timing7", False),
        work_directory=str(work))
    def save():
        (work / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    save()
    if bundle.get("configure_host", True):
        try:
            configure_host(work, result)
        except Exception as exc:
            result["host_error"] = repr(exc)
            if result["host_configuration"] == "NOT_RUN":
                result["host_configuration"] = "BLOCKED"
            print("HOST stage: " + repr(exc), flush=True)
    save()
    try:
        audit(work, result, raw_tcl)
    except Exception as exc:
        result.update(timing_collection="FAIL", timing_error=repr(exc))
        print("Timing stage: " + repr(exc), flush=True)
    total = 0
    for path in sorted(work.rglob("*")):
        if not path.is_file() or path.suffix == ".dcp" or path.name == "result.json":
            continue
        size = path.stat().st_size
        item = dict(bytes=size, sha256=digest(path))
        total += size
        if size <= 8 * 1024 * 1024 and total <= 64 * 1024 * 1024:
            raw = path.read_bytes()
            item["base64"] = base64.b64encode(raw).decode("ascii")
        else:
            item["not_returned"] = "over transfer cap; retained on server"
        result["files"][path.relative_to(work).as_posix()] = item
    # Collection success never means warnings are waived or board readiness passed.
    result["status"] = "PASS" if result["timing_collection"] == "PASS" else "FAIL"
    result["board_readiness"] = "PENDING_REVIEW"
    result["finished_at"] = now()
    save()
    if bundle.get("configure_host", True):
        print("Finished. Result collection will request SSH authentication once more.", flush=True)
    else:
        print("U280_PROBE_BEGIN_" + result["nonce"])
        print(json.dumps(result, ensure_ascii=True))
        print("U280_PROBE_END_" + result["nonce"])
    return 0 if result["status"] == "PASS" else 1
