#!/usr/bin/env python3
"""Capture source identity and resolve a candidate target without claiming execution."""
import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "upstream" / "vortex"
COMMIT = "7fe19369587c087f902c3e2bc2add612aa910a95"
TOOLCHAIN = "8c64cf921d3c6c456e80f00d24482d0aa2153a82"


def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical(value))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    import re
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", args.run_id):
        parser.error("run-id must be a simple directory name")
    result = ROOT / "results" / args.run_id
    result.mkdir(parents=True, exist_ok=False)
    commands = []

    def run(command, cwd=SOURCE):
        proc = subprocess.run(command, cwd=cwd, capture_output=True, text=True, encoding="utf-8")
        commands.append({"argv": command, "cwd": str(cwd), "exit_code": proc.returncode,
                         "stdout": proc.stdout, "stderr": proc.stderr})
        save(result / "commands.json", commands)
        if proc.returncode:
            raise RuntimeError(proc.stderr)
        return proc.stdout

    actual = run(["git", "rev-parse", "HEAD"]).strip()
    if actual != COMMIT:
        raise RuntimeError("source commit mismatch")
    if run(["git", "status", "--porcelain", "--untracked-files=no"]).strip():
        raise RuntimeError("tracked source modifications must be reviewed before capture")
    tracked = run(["git", "ls-files", "-z"]).split("\0")
    submodules = []
    for line in run(["git", "ls-tree", "HEAD", "third_party/"]).splitlines():
        meta, relative = line.split("\t")
        mode, kind, pin = meta.split()
        if mode != "160000":
            continue
        folder = SOURCE / relative
        initialized = (folder / ".git").exists()
        entry = {"path": relative, "commit": pin, "initialized": initialized, "actual_commit": None}
        if initialized:
            entry["actual_commit"] = run(["git", "rev-parse", "HEAD"], folder).strip()
            if entry["actual_commit"] != pin:
                raise RuntimeError("submodule mismatch: " + relative)
            if run(["git", "status", "--porcelain", "--untracked-files=no"], folder).strip():
                raise RuntimeError("submodule modifications: " + relative)
            tracked.extend(relative + "/" + p for p in run(["git", "ls-files", "-z"], folder).split("\0") if p)
        submodules.append(entry)
    manifest = [{"path": p, "bytes": (SOURCE / p).stat().st_size, "sha256": sha(SOURCE / p)}
                for p in sorted(tracked) if p and (SOURCE / p).is_file()]
    save(result / "source_manifest.json", manifest)

    config = {
        "schema_version": "ab-hardware-candidate-v1", "status": "draft",
        "target_id": "vortex-v3-rv64-1c4w4t-smoke-draft", "xlen": 64,
        "defines": {"VX_CFG_NUM_CLUSTERS": 1, "VX_CFG_NUM_CORES": 1,
                    "VX_CFG_NUM_WARPS": 4, "VX_CFG_NUM_THREADS": 4},
        "simx_mode": "timing", "source_config_sha256": sha(SOURCE / "VX_config.toml"),
        "resolved_scope": "Common candidate flags only; backend Makefiles add further defines. This is not a final RTL/FPGA configuration hash.",
        "scope": "Upstream integer demo smoke only; project P0 is NOT_RUN"
    }
    flags = " ".join("-D%s=%s" % item for item in config["defines"].items()) + " -DVX_CFG_XLEN=64"
    resolved = run([sys.executable, "-B", str(SOURCE / "ci/gen_config.py"), "--config",
                    str(SOURCE / "VX_config.toml"), "--cflags=" + flags, "--format=cflags"], ROOT)
    (result / "resolved_config.cflags").write_text(resolved, encoding="utf-8", newline="\n")
    for key, value in {**config["defines"], "VX_CFG_XLEN": 64}.items():
        if "-D%s=%s" % (key, value) not in resolved.split():
            raise RuntimeError("resolved configuration mismatch: " + key)
    config["resolved_config_sha256"] = sha(result / "resolved_config.cflags")
    save(ROOT / "configs" / "native_smoke.json", config)
    lock = {
        "schema_version": "target-lock-draft-v1", "status": "draft", "frozen": False,
        "target_id": config["target_id"], "vortex": {"url": "https://github.com/vortexgpgpu/vortex",
        "tag_label": "v3.0", "commit": actual, "submodules": submodules, "patches": []},
        "toolchain": {"repository": "https://github.com/vortexgpgpu/vortex-toolchain-prebuilt",
        "tag_label": "v3.0.1", "commit_candidate": TOOLCHAIN, "downloaded": False,
        "archive_hashes": None, "llvm_actual_version": None, "riscv_gnu_actual_version": None,
        "libc_actual_version": None, "libcrt_actual_version": None},
        "runtime": {"source_commit": actual, "api": "vortex2", "built": False},
        "xlen": 64, "endianness": "little", "endianness_evidence": "source candidate; execution NOT_RUN",
        "hardware_config_file": "configs/native_smoke.json", "hardware_config_sha256": sha(ROOT / "configs/native_smoke.json"),
        "compiler_flags_source": "tests/regression/common.mk at the pinned Vortex commit; no local overrides",
        "simulators": {"simx": {"source_commit": actual, "built": False},
                       "verilator": {"candidate_version": "5.050", "actual_version": None}},
        "platform_tools": {"vitis": None, "vivado": None, "xrt": None, "shell": None, "platform_name": None},
        "acceptance": {"native_simx": "NOT_RUN", "native_rtlsim": "NOT_RUN", "xrt_afu_sim": "NOT_RUN",
                       "u280": "BLOCKED", "independent_reproduction": "NOT_RUN"},
        "canonicalization": "UTF-8, sorted object keys, compact JSON, ensure_ascii=false, exactly one final LF; hash file excluded",
        "evidence": "results/" + args.run_id,
        "source_manifest_sha256": sha(result / "source_manifest.json")
    }
    save(ROOT / "configs/target_lock.json", lock)
    lock_hash = sha(ROOT / "configs/target_lock.json")
    (ROOT / "configs/target_lock.sha256").write_text(lock_hash + "  target_lock.json\n", encoding="ascii")
    caps = {
        "schema_version": "target-caps-draft-v1", "status": "draft", "target_id": config["target_id"],
        "target_lock_hash": lock_hash, "evidence_level": "source-derived; no device query or kernel execution",
        "xlen": 64, "device_pointer_bits_candidate": 64, "device_address_bits_verified": None,
        "physical_threads_per_warp_candidate": 4, "warps_per_core_candidate": 4, "cores_candidate": 1,
        "resident_threads_per_core_candidate": 16,
        "simulation_memory": {"address_bits_candidate": 48, "banks_candidate": 2, "source": "VX_config.toml"},
        "u280_source_mapping": {"address_bits_candidate": 33, "banks_candidate": 32,
        "memory_connectivity": "HBM[0:31]", "command_processor_connectivity": "HOST[0]",
        "source": "hw/syn/xilinx/xrt/platforms.mk", "verified_on_device": False},
        "launch_limits_verified": None, "p0_default_block_32_verified": False,
        "shared_barrier_verified": False, "ptx_profile": "ptx-vx-p0-v0.1-draft",
        "numeric_mode_requested": "u32 modulo 2^32; unverified",
        "exception_reporting_verified": None, "safe_abort_verified": None, "recovery_verified": None,
        "limits": ["The upstream demo is signed int, not a P0 u32 overflow test.",
                   "4 warps x 4 lanes is a smoke configuration; block32 needs a different candidate and tests.",
                   "rtlsim core execution does not establish XRT AFU or U280 correctness.",
                   "RTL adds SV_DPI and FPGA has other backend flags; the common resolved configuration is not the complete effective backend configuration.",
                   "Source capability is not a validated promise to C/D/E."]
    }
    save(ROOT / "configs/target_caps.json", caps)
    for name in ("native_smoke.json", "target_lock.json", "target_caps.json", "target_lock.sha256"):
        (result / name).write_bytes((ROOT / "configs" / name).read_bytes())
    save(result / "result.json", {"status": "PASS", "scope": "source identity and candidate configuration resolution only",
         "utc": datetime.now(timezone.utc).isoformat(), "script_sha256": sha(Path(__file__)),
         "tracked_files_hashed": len(manifest), "target_lock_hash": lock_hash,
         "simx_execution": "NOT_RUN", "rtl_execution": "NOT_RUN", "u280_execution": "BLOCKED"})
    print("Captured draft target: " + str(result))


if __name__ == "__main__":
    main()
