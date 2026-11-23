"""Audit the archived D10/D12 identities and their parameter-staging source."""

from pathlib import Path

from ptx_module import BOARD_LOCK_SHA, COMMIT, target
from run_native_smoke import PROJECT, sha256
from run_ptx_copy import BOARD_LOCK, VORTEX, read_json, require, run_stage
from u280_board_smoke import RUNTIME_SHAS, XCLBIN_SHA, XCLBIN_UUID


D10 = PROJECT / "results/u280-archive-20261109-v5"
D8 = PROJECT / "results/ab-d8-u280-source-20261109-v1/package"
D12 = PROJECT / "results/u280-runtime-20261109-v4/returned/runtime"
D12_INPUT = PROJECT / "results/u280-runtime-gcc9-prepare-20261109-v2/extracted/u280-runtime200-input"
RTL_FILES = ("VX_config.vh", "VX_cp_axil_regfile.sv", "VX_afu_wrap.sv", "VX_kmu.sv", "VX_scheduler.sv", "vortex_afu.v")
HOST_FILES = (
    "sw/common/mem_alloc.h", "sw/runtime/common/common.h", "sw/runtime/common/device.cpp",
    "sw/runtime/common/queue.cpp", "sw/runtime/common/vortex2_internal.h", "sw/runtime/include/vortex2.h",
    "sw/runtime/xrt/vortex.cpp", "sw/runtime/common/vm.cpp", "sw/runtime/common/vm.h",
)
PATCHED = {"source/sw/runtime/common/vm.cpp", "source/sw/runtime/common/vm.h", "build/sw/runtime/common.mk"}


def execute(out, rec):
    lock = BOARD_LOCK.read_bytes()
    hardware = BOARD_LOCK.with_name("fpga.json").read_bytes()
    target(lock, hardware)
    require(sha256(BOARD_LOCK) == BOARD_LOCK_SHA, "board lock differs")
    require(run_stage(rec, "fixed_source_head", ["git", "-C", VORTEX, "rev-parse", "HEAD"], out).strip() == COMMIT and
            not run_stage(rec, "fixed_source_diff", ["git", "-C", VORTEX, "diff", "--ignore-submodules=untracked", "HEAD"], out),
            "fixed build source differs")
    archive = read_json(D10 / "probe.json")
    require(archive["status"] == archive["build_status"] == "PASS", "D10 archive status differs")
    archived = {}
    for name in ("artifacts/vortex_afu.xclbin", "build/result.json", "build/input_manifest.json",
                 "inspection/ip_layout.json", "inspection/mem_topology.json", "inspection/connectivity.json"):
        entry = archive["files"][name]
        file = D10 / entry["local_path"]
        require(file.stat().st_size == entry["bytes"] and sha256(file) == entry["sha256"], "D10 archive changed: " + name)
        archived[name] = file
    build = read_json(archived["build/result.json"])
    require(sha256(archived["artifacts/vortex_afu.xclbin"]) == build["artifact"]["sha256"] == XCLBIN_SHA and
            build["status"] == "PASS" and build["exit_code"] == 0 and build["target_lock_sha256"] == BOARD_LOCK_SHA and
            build["input_manifest_sha256"] == sha256(archived["build/input_manifest.json"]) and
            all(c["exit_code"] == 0 and not c["timed_out"] for c in build["commands"]), "D10 build receipt differs")
    xclbin = archived["artifacts/vortex_afu.xclbin"]
    require(bytes.fromhex(XCLBIN_UUID.replace("-", "")) in xclbin.read_bytes()[:1024], "D10 UUID absent from xclbin header")
    rtl_index = {row["path"]: row["sha256"] for row in read_json(archived["build/input_manifest.json"])}
    rtl = {name: sha256(D8 / "src" / name) for name in RTL_FILES}
    require(all(value == rtl_index["src/" + name] for name, value in rtl.items()), "D10 RTL input differs from preserved bytes")
    config = (D8 / "src/VX_config.vh").read_text(encoding="utf-8")
    resolved = (D12_INPUT / "resolved.cflags").read_text(encoding="utf-8").split()
    cp_source = (D8 / "src/VX_cp_axil_regfile.sv").read_text(encoding="utf-8")
    require("`define VX_CFG_VM_ENABLED 0" in config and "6'h08: return {8'd0," in cp_source and
            "-DVX_CFG_VM_ENABLED=0" in resolved and "-DVX_CFG_VM_ENABLE" not in resolved, "fixed D10/D12 VM evidence differs")
    ip = read_json(archived["inspection/ip_layout.json"])["ip_layout"]["m_ip_data"]
    require(any(i["m_name"] == "vortex_afu:vortex_afu_1" for i in ip), "D10 AFU IP name differs")

    native = read_json(D12 / "result.json")
    binding = native["binding"]
    require(native["status"] == "PASS" and native["exit_code"] == 0 and native["xrt_backend"] == "PASS" and
            {Path(i["path"]).name: i["sha256"] for i in native["artifacts"]} == RUNTIME_SHAS and
            binding == read_json(D12_INPUT / "binding.json") and binding["xclbin"]["sha256"] == XCLBIN_SHA and
            binding["source_commit"] == COMMIT and binding["target_lock_sha256"] == BOARD_LOCK_SHA and
            binding["fpga_build_result_sha256"] == sha256(archived["build/result.json"]) and
            binding["resolved_cflags_sha256"] == sha256(D12_INPUT / "resolved.cflags") and
            {row["path"] for row in binding["patches"]} == PATCHED, "D12 build/profile receipt differs")
    for label in ("stub", "xrt"):
        command, = (c for c in native["commands"] if c["label"] == label)
        flags, = (arg[len("XCONFIGS="):].split() for arg in command["argv"] if arg.startswith("XCONFIGS="))
        require(command["exit_code"] == 0 and not command["timed_out"] and "TARGET=hw" in command["argv"] and flags == resolved,
                "D12 native compile flags differ")
    index = {row["path"]: row["sha256"] for row in binding["source_files"]}
    patches = {row["path"]: row for row in binding["patches"]}
    source = {name: sha256(D12_INPUT / "source" / name) for name in HOST_FILES}
    for name, value in source.items():
        path = "source/" + name
        pinned = sha256(VORTEX / name)
        require(value == index[name], "D12 input file differs: " + name)
        if path in patches:
            require(patches[path]["after_sha256"] == value and patches[path]["before_sha256"] == pinned, "D12 VM patch differs")
        else:
            require(value == pinned, "D12 staging or ABI differs from pinned source")
    common_patch = patches["build/sw/runtime/common.mk"]
    require(sha256(D12_INPUT / common_patch["path"]) == common_patch["after_sha256"], "D12 build scaffold patch differs")
    for name, digest in RUNTIME_SHAS.items():
        require(sha256(D12 / "lib" / name) == digest, "D12 archived library changed: " + name)
    elf = run_stage(rec, "d12_xrt_elf", ["readelf", "-d", D12 / "lib/libvortex-xrt.so"], out)
    require("[libxrt_coreutil.so" in elf and "libxrtsim.so" not in elf, "D12 XRT dependency differs")
    symbols = run_stage(rec, "d12_stub_symbols", ["nm", "-D", "-C", D12 / "lib/libvortex.so"], out)
    require(all(name in symbols for name in ("Device::args_slot_acquire", "Device::args_slot_release", "Device::mem_alloc",
                "vx_enqueue_launch", "vx_device_query")), "D12 queue/allocator exports are missing")
    query = run_stage(rec, "d12_vm_fallback_string", ["strings", D12 / "lib/libvortex.so"], out)
    require("CP_DEV_CAPS read returned all-ones" in query, "D12 capability fallback marker differs")
    return dict(status="PASS", scope="archived build, physical runtime bytes, and source audit",
                board_lock_sha256=BOARD_LOCK_SHA, xclbin_sha256=XCLBIN_SHA, xclbin_uuid=XCLBIN_UUID,
                runtime_sha256=RUNTIME_SHAS, d10_artifacts={name: sha256(path) for name, path in archived.items()},
                d10_input_rtl=rtl, d12_build_sha256=sha256(D12 / "result.json"),
                d12_input_binding_sha256=sha256(D12_INPUT / "binding.json"), d12_source=source, d12_patch_inventory=sorted(PATCHED),
                vm_build_enabled=0, cp_dev_caps_offset=0x1008, cp_caps_all_ones_fallback=True,
                args_slot_bytes=4096, allocator_base=0x10000, allocator_alignment_bytes=64,
                live_vm="NOT_RUN", live_staging_addresses="NOT_RUN", formal_aligned_load="BLOCKED")
