"""C-role V03/V04 adapter for the pinned Vortex2 toolchain.

prepare emits device sources, never a loadable image. build uses the upstream
SIMT build rules. validate returns verified image bytes (not a mutable path).
Neither successful packaging nor validation is device-execution evidence.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys

import ptx_frontend_v12 as frontend

COMMIT = "7fe19369587c087f902c3e2bc2add612aa910a95"
SCHEMA = "ptx-vx-module-v1-draft"
BOARD_SCHEMA = "ptx-vx-module-u280-v2-draft"
BOARD_TARGET_ADAPTER = "u280-hbm32-target-v1"
BOARD_LOCK_SHA = "e55719ecaa83d1b0f637cf212819716c58667443918f822eaed9ee2eb2aa7486"
ADAPTER = "ptx-vx-vortex2-wrapper-v1"
FORMAT = "vortex-v3-vxbin-symtab"
MAKE_BLOB = "ed7a588772ed842fc3581a355259fcb1ff3238b6"


class ModuleError(ValueError):
    def __init__(self, code, message, phase="load"):
        super().__init__(message)
        self.code, self.phase = code, phase

    def to_dict(self):
        return dict(code=self.code, phase=self.phase, message=str(self),
                    run_id=None, event_id=None, generation=None, backend=None,
                    source_location=None, native_status=None, evidence_path=None)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_json(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key: " + key)
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=unique)


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def target(lock_bytes, hardware_bytes):
    lock, hardware = read_json(lock_bytes), read_json(hardware_bytes)
    if (lock.get("xlen") != 64 or lock.get("endianness") != "little"
            or lock.get("vortex", {}).get("commit") != COMMIT
            or lock.get("runtime", {}).get("api") != "vortex2"
            or digest(hardware_bytes) != lock.get("hardware_config_sha256")
            or hardware.get("target_id") != lock.get("target_id")
            or hardware.get("xlen") != 64):
        raise ModuleError("E_TARGET_MISMATCH", "requires matching pinned RV64 Vortex2 lock/config")
    defines = hardware.get("defines", {})
    names = {"VX_CFG_NUM_" + suffix for suffix in ("CLUSTERS", "CORES", "WARPS", "THREADS")}
    board = hardware.get("target") == "hw"
    if board:
        if (digest(lock_bytes) != BOARD_LOCK_SHA
                or set(defines) != names | {"PLATFORM_MERGED_MEMORY_INTERFACE"}
                or defines.get("PLATFORM_MERGED_MEMORY_INTERFACE") is not True):
            raise ModuleError("E_TARGET_MISMATCH", "requires the exact D10/D12 U280 target")
    if (set(defines) != names and not board
            or any(type(defines.get(k)) is not int or not 1 <= defines[k] <= 1024 for k in names)):
        raise ModuleError("E_TARGET_MISMATCH", "unsupported hardware candidate defines")
    # Native source limit, not a claim that the PTX wrapper is accepted on hardware.
    limits = dict(max_block_x=min(1024, defines["VX_CFG_NUM_WARPS"] * defines["VX_CFG_NUM_THREADS"]),
                  max_grid_x=2**31 - 1, max_total_threads=2**32,
                  provenance="pinned native resident-thread limit; PTX execution NOT_RUN")
    return lock, defines, limits


def makefile():
    return '''# ROOT_DIR must be the isolated, configured Vortex build root.
ifndef ROOT_DIR
$(error supply ROOT_DIR pointing to an isolated configured Vortex build)
endif
include $(ROOT_DIR)/config.mk
PROJECT := ptx_module
SRC_DIR := .
SRCS :=
VX_SRCS := kernel.cpp
VX_HDRS := kernel_body.hpp
KERNEL_LIB := vortex2
VX_CFLAGS += -std=c++17
include $(VORTEX_HOME)/tests/regression/common.mk
'''


def wrapper():
    # One uniform payload pointer is the native kernel's argument. All layout
    # decoding remains in D's generated body; never select a body by entry name.
    return '''// Generated Vortex2 adapter; compile with the pinned +xvortex toolchain.
#include <vx_spawn2.h>
#include "kernel_body.hpp"
static_assert(sizeof(uintptr_t) == 8, "PTX64 requires RV64");
struct PtxGlobalMemory {
  uint32_t load32(uint64_t address) {
    return *reinterpret_cast<const volatile uint32_t*>(uintptr_t(address));
  }
  void store32(uint64_t address, uint32_t value) {
    *reinterpret_cast<volatile uint32_t*>(uintptr_t(address)) = value;
  }
};
__kernel void kernel_main(const uint8_t* __UNIFORM__ payload) {
  PtxThread thread{uint32_t(threadIdx.x), uint32_t(blockDim.x),
                   uint32_t(blockIdx.x), uint32_t(gridDim.x)};
  PtxGlobalMemory memory;
  ptx_body(payload, thread, memory);
}
'''


def prepare(source, output, lock_path, hardware_path):
    lock_bytes, hardware_bytes = Path(lock_path).read_bytes(), Path(hardware_path).read_bytes()
    lock, _, limits = target(lock_bytes, hardware_bytes)
    output = Path(output)
    ir = frontend.compile_source(source, output, "source.ptx", lock_path)
    (output / "manifest.json").rename(output / "frontend_manifest.json")
    (output / "hardware.json").write_bytes(hardware_bytes)
    (output / "kernel.cpp").write_text(wrapper(), encoding="utf-8", newline="\n")
    (output / "Makefile").write_text(makefile(), encoding="utf-8", newline="\n")
    manifest = dict(schema_version=SCHEMA, compiler_id=ADAPTER,
                    build_id=digest(source.encode() + lock_bytes)[:20],
                    status="SOURCE_PREPARED", loadable=False,
                    image_file=None, image_sha256=None, image_format=FORMAT,
                    entry=ir["entry"], native_entry="main",
                    source_sha256=ir["source_sha256"], source_ptx_version=ir["source_ptx_version"],
                    source_target=ir["source_target"], source_address_bits=ir["source_address_bits"],
                    profile=ir["profile"], abi_version=ir["abi_version"],
                    params=ir["params"], params_size=ir["params_size"], params_align=ir["params_align"],
                    target_lock_hash=digest(lock_bytes), target_id=lock["target_id"],
                    required_features=ir["required_features"], logical_launch_model="ptx-1d-v1",
                    launch_limits=limits, static_shared_bytes=0, dynamic_shared_policy="forbidden",
                    numeric_mode="u32 modulo 2^32", memory_assumptions=ir["memory_assumptions"],
                    known_limits=["not a memory sandbox", "single entry", "no shared memory or barriers"],
                    backend_execution="NOT_RUN", independent_acceptance="NOT_RUN")
    manifest["files"] = {p.name: digest(p.read_bytes()) for p in output.iterdir() if p.is_file()}
    if read_json(hardware_bytes).get("target") == "hw":
        manifest.update(schema_version=BOARD_SCHEMA, target_adapter_version=BOARD_TARGET_ADAPTER)
    write_json(output / "manifest.json", manifest)
    return manifest


def inspect_vxbin(data):
    """Check the pinned packer's symbol footer; forbid legacy fallback to main.

    Structural checks are stricter than the native loader. They do not prove
    that executable instructions have correct PTX semantics.
    """
    def reject(message):
        raise ModuleError("E_MODULE_CORRUPT", message)
    if len(data) < 45 or data[-8:] != b"VXSYMTAB":
        reject("missing Vortex2 symbol footer")
    low, high = struct.unpack_from("<QQ", data)
    count, = struct.unpack_from("<I", data, len(data) - 12)
    if not 0 < low < high or count != 1:
        reject("invalid VMA or non-single-entry image")
    entries = len(data) - 12 - 16 * count
    offset, length, pad, pc = struct.unpack_from("<IHHQ", data, entries)
    strings = entries - offset - length
    if offset != 0 or pad != 0 or strings <= 16 or length == 0:
        reject("invalid symbol-table extent")
    name = data[strings:entries]
    binary_size = strings - 16
    if name != b"main" or binary_size > high - low or not low <= pc < low + binary_size or pc % 2:
        reject("invalid native entry or image extent")
    return dict(min_vma=low, max_vma=high, binary_size=binary_size, entry_pc=pc)


def verify_sources(directory, expected_lock):
    """Validate all declared files and regenerate the D->C boundary metadata."""
    directory = Path(directory).resolve()
    try:
        manifest = read_json((directory / "manifest.json").read_bytes())
        if manifest.get("schema_version") not in (SCHEMA, BOARD_SCHEMA) or manifest.get("compiler_id") != ADAPTER:
            raise ModuleError("E_MODULE_CORRUPT", "unknown module schema/compiler")
        files = manifest["files"]
        required = {"source.ptx", "ir.json", "kernel_body.hpp", "kernel.cpp", "source_map.json",
                    "frontend_manifest.json", "target_lock.json", "hardware.json", "profile.json", "abi.json", "Makefile"}
        if not isinstance(files, dict) or not required <= files.keys():
            raise ModuleError("E_MODULE_CORRUPT", "missing required artifacts")
        blobs = {}
        for name, expected in files.items():
            if not re.fullmatch(r"[A-Za-z0-9_.-]+", name) or name in (".", "..", "manifest.json"):
                raise ModuleError("E_MODULE_CORRUPT", "unsafe artifact name")
            path = directory / name
            if path.is_symlink() or path.resolve().parent != directory or not path.is_file():
                raise ModuleError("E_MODULE_CORRUPT", "artifact must be a regular local file: " + name)
            blobs[name] = path.read_bytes()
            if digest(blobs[name]) != expected:
                raise ModuleError("E_MODULE_CORRUPT", "artifact hash mismatch: " + name)
        if (blobs["target_lock.json"] != expected_lock
                or manifest.get("target_lock_hash") != digest(expected_lock)):
            raise ModuleError("E_TARGET_MISMATCH", "module target differs from requested target")
        lock, _, limits = target(expected_lock, blobs["hardware.json"])
        board = read_json(blobs["hardware.json"]).get("target") == "hw"
        if (manifest["schema_version"] != (BOARD_SCHEMA if board else SCHEMA)
                or (board and manifest.get("target_adapter_version") != BOARD_TARGET_ADAPTER)):
            raise ModuleError("E_TARGET_MISMATCH", "module target adapter/version differs")
        ir = frontend.parse(blobs["source.ptx"].decode("utf-8"), "source.ptx")
        cpp, source_map = frontend.emit_cpp(ir)
        if (read_json(blobs["ir.json"]) != ir or blobs["kernel_body.hpp"] != cpp.encode()
                or read_json(blobs["source_map.json"]) != source_map
                or blobs["kernel.cpp"] != wrapper().encode()
                or blobs["Makefile"] != makefile().encode()):
            raise ModuleError("E_MODULE_CORRUPT", "generated semantics/wrapper differs from source")
        fields = ("entry", "source_sha256", "source_ptx_version", "source_target", "source_address_bits",
                  "profile", "abi_version", "params", "params_size", "params_align", "required_features",
                  "logical_launch_model", "static_shared_bytes", "memory_assumptions")
        if any(manifest.get(field) != ir[field] for field in fields):
            raise ModuleError("E_MODULE_CORRUPT", "module metadata differs from parsed source")
        if (manifest.get("launch_limits") != limits or manifest.get("target_id") != lock["target_id"]
                or manifest.get("native_entry") != "main" or manifest.get("image_format") != FORMAT
                or manifest.get("dynamic_shared_policy") != "forbidden"):
            raise ModuleError("E_MODULE_CORRUPT", "invalid launch/target metadata")
        return manifest, blobs
    except ModuleError:
        raise
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise ModuleError("E_MODULE_CORRUPT", str(exc)) from exc


def validate(directory, expected_lock):
    manifest, blobs = verify_sources(directory, expected_lock)
    if manifest.get("loadable") is not True or manifest.get("status") != "BUILT":
        raise ModuleError("E_MODULE_NOT_BUILT", "source preparation is not a loadable device module")
    if manifest.get("image_file") != "kernel.vxbin" or not {"kernel.vxbin", "kernel.elf", "program.disasm", "compile.log", "build.json"} <= blobs.keys():
        raise ModuleError("E_MODULE_CORRUPT", "missing image or build evidence")
    image = blobs["kernel.vxbin"]
    if digest(image) != manifest.get("image_sha256"):
        raise ModuleError("E_MODULE_CORRUPT", "image hash mismatch")
    try:
        evidence = read_json(blobs["build.json"])
        if (evidence.get("status") != "PASS" or evidence.get("exit_code") != 0
                or evidence.get("source_commit") != COMMIT
                or evidence.get("target_lock_hash") != digest(expected_lock)):
            raise ValueError("missing successful build bound to this source/target")
        elf = blobs["kernel.elf"]
        if (len(elf) < 64 or elf[:7] != b"\x7fELF\x02\x01\x01"
                or struct.unpack_from("<HH", elf, 16) != (2, 243)):
            raise ValueError("expected little-endian ELF64 RISC-V executable")
    except (ValueError, TypeError, AttributeError) as exc:
        raise ModuleError("E_MODULE_CORRUPT", str(exc)) from exc
    inspect_vxbin(image)
    return manifest, image


def safe_make_path(path):
    if re.search(r"[\s$#:'\"`&|;<>\\]", str(path)):
        raise ModuleError("E_BUILD_ENV", "upstream make requires paths without shell/make metacharacters", "build")


def build(directory, source, build_root, tooldir, expected_lock, timeout=300):
    """Build using fresh output and the hash-verified pinned toolchain.

    All source/SDK preparation is external and explicit. No download, CPU
    fallback, installation, device programming, or reuse of stale output.
    """
    directory, source, build_root, tooldir = (Path(p).resolve() for p in (directory, source, build_root, tooldir))
    manifest, blobs = verify_sources(directory, expected_lock)
    if any((directory / p).exists() for p in ("compile.log", "build.json", "kernel.elf", "kernel.vxbin")):
        raise ModuleError("E_BUILD_ENV", "use a fresh prepare directory; existing evidence is preserved", "build")
    for path in (directory, source, build_root, tooldir):
        safe_make_path(path)
    if (directory.is_relative_to(source) or build_root.is_relative_to(source)
            or build_root.is_relative_to(tooldir) or build_root.exists()):
        raise ModuleError("E_BUILD_ENV", "build and module output must stay outside fixed source", "build")
    rev = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    if rev != COMMIT or subprocess.check_output(["git", "-C", str(source), "diff", "HEAD", "--", "sw", "ci", "tests/regression/common.mk"]):
        raise ModuleError("E_BUILD_ENV", "source must be the clean pinned Vortex commit", "build")
    common = (source / "tests/regression/common.mk").read_bytes()
    if hashlib.sha1(b"blob " + str(len(common)).encode() + b"\0" + common).hexdigest() != MAKE_BLOB:
        raise ModuleError("E_BUILD_ENV", "upstream SIMT build rules changed", "build")
    lock, defines, _ = target(expected_lock, blobs["hardware.json"])
    hashes = lock["toolchain"]["observed_file_sha256"]
    tool_hashes = {}
    for name, expected in hashes.items():
        if name.startswith(("llvm-vortex/", "libc64/", "libcrt64/", "riscv64-gnu-toolchain/")):
            if ".." in Path(name).parts or Path(name).is_absolute():
                raise ModuleError("E_BUILD_ENV", "invalid toolchain path", "build")
            tool_hashes[name] = digest((tooldir / name).read_bytes())
            if tool_hashes[name] != expected:
                raise ModuleError("E_BUILD_ENV", "toolchain hash mismatch: " + name, "build")
    if "llvm-vortex/bin/clang++" not in tool_hashes:
        raise ModuleError("E_BUILD_ENV", "lock does not identify Vortex clang++", "build")
    configs = "CONFIGS=" + " ".join("-D%s=%d" % item for item in sorted(defines.items()))
    argv = ["make", "-C", str(directory), "ROOT_DIR=" + str(build_root),
            "VORTEX_HOME=" + str(source), "XLEN=64", "KERNEL_LIB=vortex2",
            configs, "kernel.vxbin", "kernel.dump"]
    commands = [["bash", str(source / "configure"), "--xlen=64", "--tooldir=" + str(tooldir)],
                ["make", "-j2", "-C", str(build_root / "sw/kernel"), "XLEN=64", configs], argv]
    record = dict(commands=[], source_commit=rev, target_lock_hash=digest(expected_lock),
                  toolchain_files=tool_hashes,
                  exit_code=None, status="RUNNING", scope="device compilation; no execution")
    build_root.mkdir(parents=True, exist_ok=False)
    # common.mk includes host dependencies; this device-only module has no host
    # translation units. An existing empty dependency file avoids g++ -MM with
    # no inputs while retaining the pinned device rules without modification.
    (directory / ".depend").write_text("# Device-only build; no host dependencies.\n")
    write_json(directory / "build.json", record)
    with (directory / "compile.log").open("wb") as log:
        try:
            # Reuse the existing recorder's process-group timeout handling.
            from run_native_smoke import Recorder
            for command in commands:
                log.write((json.dumps(command) + "\n").encode())
                log.flush()
                proc = subprocess.Popen(command, cwd=build_root, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                try:
                    record["exit_code"] = proc.wait(timeout=timeout)
                except (subprocess.TimeoutExpired, KeyboardInterrupt):
                    Recorder.kill_group(proc)
                    raise
                record["commands"].append(dict(argv=command, exit_code=proc.returncode))
                write_json(directory / "build.json", record)
                if proc.returncode:
                    break
            record["status"] = "PASS" if record["exit_code"] == 0 else "FAIL"
        except (OSError, subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
            record.update(status="FAIL", error=str(exc))
        finally:
            write_json(directory / "build.json", record)
    if record["status"] != "PASS":
        raise ModuleError("E_BUILD_FAILED", "see compile.log and build.json", "build")
    image = (directory / "kernel.vxbin").read_bytes()
    inspect_vxbin(image)
    shutil.copyfile(directory / "kernel.dump", directory / "program.disasm")
    manifest.update(status="BUILT", loadable=True, image_file="kernel.vxbin", image_sha256=digest(image))
    for name in ("kernel.vxbin", "kernel.elf", "program.disasm", "compile.log", "build.json"):
        manifest["files"][name] = digest((directory / name).read_bytes())
    write_json(directory / "manifest.json", manifest)
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("source", type=Path)
    prep.add_argument("--output", type=Path, required=True)
    prep.add_argument("--hardware", type=Path, required=True)
    compile_cmd = sub.add_parser("build")
    compile_cmd.add_argument("module", type=Path)
    compile_cmd.add_argument("--vortex-source", type=Path, required=True)
    compile_cmd.add_argument("--build-root", type=Path, required=True)
    compile_cmd.add_argument("--tooldir", type=Path, required=True)
    check = sub.add_parser("validate")
    check.add_argument("module", type=Path)
    for command in (prep, compile_cmd, check):
        command.add_argument("--target-lock", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == "prepare":
            result = prepare(args.source.read_bytes().decode("utf-8"), args.output, args.target_lock, args.hardware)
        elif args.action == "build":
            result = build(args.module, args.vortex_source, args.build_root, args.tooldir, args.target_lock.read_bytes())
        else:
            result, _ = validate(args.module, args.target_lock.read_bytes())
        print(json.dumps(dict(status="PASS", scope=args.action, module_status=result["status"], backend_execution="NOT_RUN")))
        return 0
    except (ModuleError, frontend.PtxError, OSError, ValueError, subprocess.SubprocessError) as exc:
        detail = exc.to_dict() if hasattr(exc, "to_dict") else dict(code="E_INPUT", message=str(exc))
        print(json.dumps(dict(status="FAIL", error=detail)))
        return 1


if __name__ == "__main__":
    sys.exit(main())
