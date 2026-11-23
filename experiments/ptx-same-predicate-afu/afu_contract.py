"""Identity checks shared by the NOXRT alignment and replay runs."""

import os
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(PROJECT / path) for path in (
    "scripts", "experiments/ptx-same-predicate-production")]

from check_c_v03_receipt import BINDINGS, TOOLCHAIN
from ptx_module import COMMIT
from run_native_smoke import Recorder, sha256, utc_now
from run_ptx_copy import SIM_LOCK, VORTEX, read_json, require, run_stage, write_json
from runtime_backends import validate_native


BACKEND = "xrtsim"
FIXED_BINDING = BINDINGS / BACKEND / "binding.json"
FIXED_SHA = "7f1bf3fc59419f7a45c827eb7b35298c315f65ecf7180e891ac2e98d33c5d915"
STAMPS = {"xrt_config.stamp": {"-DXRTSIM"}, "xrtsim_config.stamp": {"-DNOXRT", "-DSIMULATION", "-DSV_DPI"}}
AUDIT_FILES = (
    "VX_types.toml", "sw/common/mem_alloc.h", "sw/runtime/common/common.h",
    "sw/runtime/common/vortex2_internal.h", "sw/runtime/common/device.cpp", "sw/runtime/common/queue.cpp",
    "sw/runtime/xrt/vortex.cpp", "sw/runtime/xrt/Makefile", "sim/xrtsim/Makefile", "sim/xrtsim/xrt_sim.cpp",
    "hw/rtl/afu/xrt/vortex_afu.v", "hw/rtl/Vortex.sv", "hw/rtl/VX_kmu.sv", "hw/rtl/core/VX_scheduler.sv",
    "hw/rtl/core/VX_cta_dispatch.sv", "hw/rtl/core/VX_lsu_slice.sv", "sw/kernel/src/vx_start.S",
)


def source_audit(rec, out):
    head = run_stage(rec, "source_commit", ["git", "-C", VORTEX, "rev-parse", "HEAD"], out).strip()
    require(head == COMMIT == read_json(SIM_LOCK)["vortex"]["commit"], "fixed source commit differs")
    changed = run_stage(rec, "source_diff", ["git", "-C", VORTEX, "diff", "--ignore-submodules=untracked", "HEAD", "--"], out)
    require(not changed, "fixed source has tracked changes")
    rec.summary.update(source_commit=head, source_sha256={name: sha256(VORTEX / name) for name in AUDIT_FILES})


def check_binding(binding, *, fixed):
    identity = sha256(binding)
    require((identity == FIXED_SHA) == fixed, "fixed versus trace AFU binding differs")
    info = read_json(binding)
    native_path = binding.parent / "native-summary.json"
    native = read_json(native_path)
    validate_native(native, BACKEND, sha256(SIM_LOCK))
    require(info["backend"] == BACKEND and info["driver"] == "xrt" and info["target_lock_hash"] == sha256(SIM_LOCK) and
            info["native_summary_sha256"] == sha256(native_path), "NOXRT binding does not match the fixed target/native run")
    libdir = Path(info["library_dir"])
    for stamp, flags in STAMPS.items():
        path = libdir / stamp
        require(flags <= set(path.read_text().split()) and
                sha256(path) == native["build_artifacts"]["sw/runtime/" + stamp]["sha256"], "AFU build stamp differs")
    return info, native


def clean_env():
    return {key: value for key, value in os.environ.items() if key not in
            ("XCLBIN_PATH", "XCL_EMULATION_MODE", "XRT_INI_PATH", "EMCONFIG_PATH", "VORTEX_CP_POLL_TIMEOUT_S")}


def driver_env(rec, info):
    rec.env.update(VORTEX_DRIVER="xrt", LD_LIBRARY_PATH=info["library_dir"], VORTEX_PROFILING="0", XRT_DEVICE_INDEX="0")
