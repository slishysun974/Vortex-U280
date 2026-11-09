"""Bounded shared-card inspection and two-CPU Vivado component synthesis."""
import base64
import datetime
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import resource
import shutil
import signal
import subprocess
import time
import zipfile


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read(path):
    try:
        text = Path(path).read_text(errors="replace")
        return dict(status="PASS", text=text[:65536], truncated=len(text) > 65536)
    except OSError as exc:
        return dict(status="BLOCKED", error=str(exc))


def collect(bundle):
    probe_kind = bundle.get("probe_kind", "component")
    if probe_kind not in ("component", "host-platform"):
        raise ValueError("unsupported probe kind")
    started = datetime.datetime.now(datetime.timezone.utc).isoformat()
    result = dict(schema_version="u280-small-build-probe-v2", started_at=started,
                  username=pwd.getpwuid(os.getuid()).pw_name, nonce=bundle["nonce"],
                  run_id=bundle["run_id"], status="RUNNING", commands=[],
                  authorization="shared idle cards may be selected; small build with few threads allowed",
                  board_programming="NOT_RUN", board_reset="NOT_RUN", device_configuration="NOT_RUN",
                  full_vortex_synthesis="NOT_RUN", place_route="NOT_RUN", board_execution="NOT_RUN",
                  small_synthesis="NOT_RUN", license_for_small_synthesis="NOT_RUN",
                  probe_kind=probe_kind, source_commit=bundle["source_commit"], inputs={p: v["sha256"] for p, v in bundle["files"].items()})
    if result["username"] != "u280user":
        result.update(status="BLOCKED", error="unexpected remote identity")
        return result
    account_home = Path(pwd.getpwuid(os.getuid()).pw_dir).resolve()
    root = account_home / "vortex-u280-probes"
    if root.exists() and root.is_symlink():
        result.update(status="BLOCKED", error="probe root must not be a symlink")
        return result
    root.mkdir(mode=0o700, exist_ok=True)
    work = root / bundle["run_id"]
    work.mkdir(mode=0o700, exist_ok=False)
    if work.resolve().parent != root.resolve() or root.resolve().parent != account_home:
        raise ValueError("work directory outside account home")
    result["remote_work_directory"] = str(work)
    for relative, item in bundle["files"].items():
        target = work / relative
        if Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise ValueError("unsafe input path")
        data = base64.b64decode(item["base64"])
        if sha(data) != item["sha256"]:
            raise ValueError("input digest mismatch")
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(data)
    (work / "logs").mkdir()
    setup = ". /apps/Xilinx2023/Vitis/2023.1/settings64.sh >/dev/null && . /opt/xilinx/xrt/setup.sh >/dev/null && "
    env = dict(os.environ)
    env.update(OMP_NUM_THREADS="2", OPENBLAS_NUM_THREADS="2", MKL_NUM_THREADS="2")

    def command(label, argv, timeout=30, limited=False):
        stdout_path = work / "logs" / (label + ".stdout")
        stderr_path = work / "logs" / (label + ".stderr")
        rec = dict(label=label, argv=argv, cwd=str(work), timeout_seconds=timeout, returncode=None, timed_out=False)
        begin = time.monotonic()
        def child_limits():
            os.nice(10)
            if limited:
                os.sched_setaffinity(0, cpus)
        with stdout_path.open("xb") as out, stderr_path.open("xb") as err:
            try:
                proc = subprocess.Popen(argv, cwd=str(work), env=env, stdout=out, stderr=err,
                                        start_new_session=True, preexec_fn=child_limits)
                try:
                    proc.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    rec["timed_out"] = True
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait()
                rec["returncode"] = proc.returncode
                rec["status"] = "PASS" if proc.returncode == 0 and not rec["timed_out"] else "FAIL"
            except OSError as exc:
                rec.update(status="BLOCKED", error=str(exc))
        rec.update(elapsed_seconds=round(time.monotonic() - begin, 3),
                   stdout="logs/" + stdout_path.name, stderr="logs/" + stderr_path.name,
                   stdout_sha256=sha(stdout_path.read_bytes()), stderr_sha256=sha(stderr_path.read_bytes()))
        result["commands"].append(rec)
        return rec, stdout_path.read_text(errors="replace"), stderr_path.read_text(errors="replace")

    cpus = sorted(os.sched_getaffinity(0))[:2]
    result["build_limits"] = dict(cpu_affinity=cpus, vivado_max_threads=2, nice_increment=10,
                                  timeout_seconds=300, scope="small AFU module only; no implementation")
    result["load_before"] = read("/proc/loadavg")
    result["meminfo_before"] = read("/proc/meminfo")
    result["license_environment_present"] = {key: bool(os.environ.get(key)) for key in ("XILINXD_LICENSE_FILE", "LM_LICENSE_FILE")}
    command("examine_help", ["bash", "-c", setup + "exec xbutil examine --help"])
    command("configure_help", ["bash", "-c", setup + "exec xbutil configure --help"])
    if probe_kind == "host-platform":
        command("host_mem_help", ["bash", "-c", setup + "exec xbutil configure --host-mem --help"])
        command("host_mem_permission_query", ["sudo", "-n", "-l", "--", "/opt/xilinx/xrt/bin/xbutil",
            "configure", "--device", "0000:b1:00.1", "--host-mem", "enable", "--size", "256M"])
        result["permission_query_scope"] = "sudo -n -l lists command policy only; never executes configuration. Nonzero may mean password required or policy denied; inspect raw stderr."
    report_files = [work / "device_list.json"]
    command("device_list", ["bash", "-c", setup + "exec xbutil examine --format JSON --output device_list.json"])
    fuser = shutil.which("fuser")
    if not fuser:
        fuser = next((p for p in ("/usr/sbin/fuser", "/sbin/fuser", "/usr/bin/fuser")
                      if Path(p).is_file() and os.access(p, os.X_OK)), None)
    result["file_holder_check"] = dict(tool=fuser, scope="only holders visible to current account",
                                       status="AVAILABLE" if fuser else "UNAVAILABLE")
    devices = []
    for path in sorted(Path("/sys/bus/pci/devices").iterdir()):
        if read(path / "vendor").get("text", "").strip() != "0x10ee":
            continue
        if not (path / "driver").exists() or (path / "driver").resolve().name != "xocl":
            continue
        bdf = path.name
        if not re.fullmatch(r"[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]", bdf):
            continue
        item = dict(bdf=bdf, observation_only=True, reservation="NOT_ACQUIRED")
        try:
            item["sysfs_entries"] = sorted(p.name for p in path.iterdir())[:256]
        except OSError as exc:
            item["sysfs_error"] = str(exc)
        names = ("board_name", "ready", "kdsstat", "xclbinuuid", "interface_uuids", "logic_uuids",
                 "ulp_uuids", "memstat", "memstat_raw", "host_mem_size", "mig_calibration")
        item["before"] = {name: read(path / name) for name in names}
        nodes = sorted((path / "drm").glob("renderD*")) if (path / "drm").is_dir() else []
        item["device_nodes"] = ["/dev/dri/" + p.name for p in nodes]
        label = bdf.replace(":", "_").replace(".", "_")
        if nodes and fuser:
            command("holders_" + label, [fuser, "-v"] + item["device_nodes"])
        # XRT read-only reports. A report's success is not an idle-card lease.
        report_name = "device_" + label + ".json"
        report_files.append(work / report_name)
        item["xrt_report"] = report_name
        command("reports_" + label,
                ["bash", "-c", setup + "exec xbutil examine --device " + bdf +
                 " --report platform dynamic-regions memory" + (" pcie-info" if probe_kind == "host-platform" else "") +
                 " --format JSON --output " + report_name], 40)
        item["after"] = {name: read(path / name) for name in names}
        devices.append(item)
    result["devices"] = devices
    result["idle_interpretation"] = "Two sysfs snapshots and XRT reports; visible file holders only if tool available. Recheck immediately before load; no reservation created. memstat IN-USE denotes connectivity, not process occupancy."
    if probe_kind == "component":
        usage_before = resource.getrusage(resource.RUSAGE_CHILDREN)
        rec, stdout, stderr = command("small_synthesis", ["bash", "-c", setup +
            "exec vivado -mode batch -notrace -source probe.tcl -log vivado.log -journal vivado.jou"], 300, True)
        usage_after = resource.getrusage(resource.RUSAGE_CHILDREN)
        result["build_usage"] = dict(child_cpu_seconds=round(usage_after.ru_utime + usage_after.ru_stime - usage_before.ru_utime - usage_before.ru_stime, 3),
                                    cumulative_children_maxrss_kib=usage_after.ru_maxrss)
        synthesis_ok = rec["status"] == "PASS" and "U280_SMALL_SYNTH_PASS" in stdout and (work / "post_synth.dcp").is_file()
        result["small_synthesis"] = "PASS" if synthesis_ok else "FAIL"
        result["license_for_small_synthesis"] = "PASS" if synthesis_ok else "UNCONFIRMED"
        result["license_scope"] = "actual U280 part/component synthesis checkout only; not full Vortex/IP/implementation licenses"
        result["status"] = "PASS" if synthesis_ok else "FAIL"
        result["status_scope"] = "small component synthesis; per-device query/occupancy findings remain separate"
    else:
        platform_root = Path("/opt/xilinx/platforms/xilinx_u280_gen3x16_xdma_1_202211_1")
        command("platform_info", ["bash", "-c", setup + "exec platforminfo -p " + str(platform_root / (platform_root.name + ".xpfm"))], 60)
        metadata = []
        for path in (platform_root / (platform_root.name + ".xpfm"), platform_root / "hw/hw.xsa"):
            item = dict(path=str(path))
            try:
                hasher = hashlib.sha256()
                with path.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        hasher.update(chunk)
                item.update(status="PASS", bytes=path.stat().st_size, sha256=hasher.hexdigest())
                if path.suffix == ".xpfm":
                    item["text"] = path.read_text()
                else:
                    with zipfile.ZipFile(str(path)) as archive:
                        item["members"] = [dict(name=i.filename, bytes=i.file_size) for i in archive.infolist()]
                        item["small_metadata"] = {i.filename: archive.read(i).decode("utf-8", errors="replace")
                            for i in archive.infolist() if i.filename.endswith((".xml", ".json")) and i.file_size < 256 * 1024}
            except (OSError, zipfile.BadZipFile) as exc:
                item.update(status="FAIL", error=repr(exc))
            metadata.append(item)
        meta_path = work / "platform_metadata.json"
        meta_path.write_text(json.dumps(metadata, indent=2) + "\n")
        report_files.append(meta_path)
        required = [c for c in result["commands"] if not c["label"].startswith("holders_") and c["label"] != "host_mem_permission_query"]
        result["status"] = "PASS" if devices and all(c["status"] == "PASS" for c in required) and all(m["status"] == "PASS" for m in metadata) else "FAIL"
        policy = next(c for c in result["commands"] if c["label"] == "host_mem_permission_query")
        result["host_configuration_permission"] = "POLICY_LISTED" if policy["returncode"] == 0 else "UNCONFIRMED"
        result["status_scope"] = "read-only reports/help/platform metadata; permission observation separate; HOST configuration and synthesis NOT_RUN"
    result["finished_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    result["files"] = {}
    paths = sorted((work / "logs").iterdir()) + report_files + [work / n for n in ("vivado.log", "vivado.jou", "post_synth_utilization.rpt", "post_synth.dcp")]
    for path in paths:
        if path.is_file():
            data = path.read_bytes()
            item = dict(sha256=sha(data), bytes=len(data))
            if len(data) <= 4 * 1024 * 1024:
                item["base64"] = base64.b64encode(data).decode("ascii")
            else:
                item["not_returned"] = "over 4 MiB; preserved at remote path"
            result["files"][str(path.relative_to(work))] = item
    (work / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    return result
