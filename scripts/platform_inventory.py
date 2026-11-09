#!/usr/bin/env python3
"""Read-only Linux platform inventory. No network, sudo, installs or device changes.

Run with Python 3.6+; stdout is JSON unless --output names a local evidence file.
Every child command is bounded by --timeout (1..30 seconds, default 8).
Commercial tools are located but not started. Device examination is opt-in.
"""
import argparse
import datetime
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time


def text_value(value):
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def read_file(path, limit=32768):
    try:
        with open(str(path), "r", encoding="utf-8", errors="replace") as stream:
            data = stream.read(limit + 1)
        return {"status": "PASS", "path": str(path),
                "text": data[:limit], "truncated": len(data) > limit}
    except OSError as exc:
        return {"status": "BLOCKED", "path": str(path), "error": str(exc)}


def directory(path, limit=128):
    try:
        names = sorted(os.listdir(str(path)))
        return {"status": "PASS", "path": str(path),
                "entries": names[:limit], "truncated": len(names) > limit}
    except OSError as exc:
        return {"status": "BLOCKED", "path": str(path), "error": str(exc)}


def command(argv, timeout):
    binary = shutil.which(argv[0])
    if binary is None:
        return {"argv": argv, "status": "BLOCKED", "exit_code": None,
                "reason": "command_not_found_in_current_PATH"}
    start = time.monotonic()
    result = {"argv": argv, "resolved_executable": binary,
              "timeout_seconds": timeout}
    try:
        process = subprocess.run(argv, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, timeout=timeout,
                                 universal_newlines=True,
                                 encoding="utf-8", errors="replace")
        result.update(status="PASS" if process.returncode == 0 else "FAIL",
                      exit_code=process.returncode, stdout=process.stdout[:32768],
                      stderr=process.stderr[:32768],
                      truncated=len(process.stdout) > 32768 or len(process.stderr) > 32768)
    except subprocess.TimeoutExpired as exc:
        result.update(status="FAIL", exit_code=None, reason="timeout",
                      stdout=text_value(exc.stdout)[:32768],
                      stderr=text_value(exc.stderr)[:32768])
    except OSError as exc:
        result.update(status="BLOCKED", exit_code=None, error=str(exc))
    result["elapsed_seconds"] = round(time.monotonic() - start, 3)
    return result


def pci_devices():
    root = Path("/sys/bus/pci/devices")
    report = {"status": "PASS", "scope": "Xilinx vendor 0x10ee only",
              "devices": []}
    try:
        devices = sorted(root.iterdir())
    except OSError as exc:
        return {"status": "BLOCKED", "error": str(exc)}
    for device in devices:
        vendor = read_file(device / "vendor")
        if vendor.get("text", "").strip() != "0x10ee":
            continue
        item = {"bdf": device.name}
        for name in ("vendor", "device", "subsystem_vendor", "subsystem_device", "class"):
            item[name] = read_file(device / name)
        try:
            item["driver"] = str((device / "driver").resolve(strict=True))
        except OSError:
            item["driver"] = None
        report["devices"].append(item)
    report["interpretation"] = "Visibility only; no accessible device does not prove no physical board."
    return report


def collect(args):
    if sys.platform != "linux":
        return {"schema_version": "vortex-platform-inventory-v1",
                "status": "BLOCKED", "reason": "linux_required",
                "platform": sys.platform, "device_operations_performed": False}
    versions = [
        ["gcc", "--version"], ["g++", "--version"], ["make", "--version"],
        ["cmake", "--version"], ["ninja", "--version"], ["git", "--version"],
        ["python3", "--version"], ["verilator", "--version"],
        ["iverilog", "-V"], ["vvp", "-V"], ["yosys", "-V"],
        ["ccache", "--version"], ["pkg-config", "--version"], ["ldd", "--version"],
    ]
    packages = ["build-essential", "cmake", "ccache", "zlib1g-dev", "libtinfo-dev",
                "libncurses-dev", "uuid-dev", "libboost-serialization-dev",
                "libpng-dev", "libhwloc-dev", "xrt"]
    report = {
        "schema_version": "vortex-platform-inventory-v1",
        "status": "PASS", "status_scope": "inventory collection only, not toolchain or device acceptance",
        "collected_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "hostname": platform.node(), "kernel": platform.platform(),
        "python": platform.python_version(), "cpu_logical_visible": os.cpu_count(),
        "libc": list(platform.libc_ver()), "os_release": read_file("/etc/os-release"),
        "meminfo": read_file("/proc/meminfo"),
        "resource_limits": {name: read_file(path) for name, path in [
            ("cgroup_cpu_max", "/sys/fs/cgroup/cpu.max"),
            ("cgroup_memory_max", "/sys/fs/cgroup/memory.max"),
            ("cgroup_v1_memory_limit", "/sys/fs/cgroup/memory/memory.limit_in_bytes")
        ]},
        "disks": [], "versions": [], "fpga_tools_on_PATH": {},
        "directories": [], "xilinx_pci_visibility": pci_devices(),
        "device_query_requested": args.include_device_query,
        "device_mutations_performed": False, "network_operations_performed": False,
        "system_configuration_changed": False,
    }
    for path in sorted(set(["/", "/tmp", os.getcwd()])):
        try:
            usage = shutil.disk_usage(path)
            report["disks"].append({"path": path, "status": "PASS", "total_bytes": usage.total,
                                    "used_bytes": usage.used, "free_bytes": usage.free})
        except OSError as exc:
            report["disks"].append({"path": path, "status": "BLOCKED", "error": str(exc)})
    for argv in versions:
        report["versions"].append(command(argv, args.timeout))
    report["packages"] = command(["dpkg-query", "-W", "-f=${Package}\t${Status}\t${Version}\n"] + packages, args.timeout)
    for name in ("vivado", "vitis", "v++", "platforminfo", "xbutil", "xbmgmt", "xrt-smi"):
        found = shutil.which(name)
        report["fpga_tools_on_PATH"][name] = {
            "path": found, "status": "PASS" if found else "BLOCKED",
            "scope": "path discovery; version, license and operation not verified"}
    for path in ("/opt", "/tools", "/opt/Xilinx", "/tools/Xilinx", "/opt/xilinx",
                 "/opt/xilinx/xrt", "/opt/xilinx/platforms", "/opt/amd",
                 "/lib/modules/" + platform.release() + "/extra", "/dev/dri"):
        report["directories"].append(directory(path))
    if args.include_device_query:
        tool = next((t for t in ("xrt-smi", "xbutil") if shutil.which(t)), None)
        report["device_query"] = command([tool, "examine", "--format", "JSON"], args.timeout) if tool else {
            "status": "BLOCKED", "reason": "xrt-smi_and_xbutil_not_found"}
    else:
        report["device_query"] = {"status": "NOT_RUN", "reason": "opt_in_required"}
    report["acceptance"] = {"simx": "NOT_RUN", "rtlsim": "NOT_RUN", "fpga_build": "NOT_RUN",
                            "u280": "NOT_RUN", "host_memory_bridge": "NOT_RUN"}
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=int, default=8, help="Per-command timeout, 1..30 seconds")
    parser.add_argument("--output", help="Optional evidence JSON path; stdout otherwise")
    parser.add_argument("--include-device-query", action="store_true",
                        help="Read-only XRT examine; use only on an authorized assigned board host")
    args = parser.parse_args()
    if not 1 <= args.timeout <= 30:
        parser.error("--timeout must be between 1 and 30")
    result = collect(args)
    # ASCII JSON escapes preserve non-ASCII paths through Windows/WSL consoles.
    encoded = json.dumps(result, ensure_ascii=True, indent=2) + "\n"
    if args.output:
        # Exclusive create keeps previous evidence intact; choose a fresh run directory.
        with open(args.output, "x", encoding="utf-8", newline="\n") as stream:
            stream.write(encoded)
    else:
        sys.stdout.write(encoded)
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
