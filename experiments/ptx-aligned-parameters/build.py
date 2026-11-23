"""Build isolated PTX reader controls and an untimed payload-address probe."""

import argparse
import difflib
import hashlib
import os
from pathlib import Path
import re
import shutil
import sys


PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "scripts"))
sys.path.insert(0, str(PROJECT / "experiments" / "ptx-performance-attribution"))

from analyze import instructions
from measure import ARCHIVES
from check_c_v03_receipt import TOOLCHAIN
from ptx_module import MAKE_BLOB, inspect_vxbin, target
from run_native_smoke import Recorder, sha256, utc_now
from run_ptx_copy import SIM_LOCK, VORTEX, read_json, require, run_stage
from u280_perf_pair import operator_path, operations, preflight, validate_images


BYTE_READERS = b"""static inline uint32_t ptx_read32(const uint8_t* p) {
  return uint32_t(p[0]) | (uint32_t(p[1]) << 8) | (uint32_t(p[2]) << 16) | (uint32_t(p[3]) << 24);
}
static inline uint64_t ptx_read64(const uint8_t* p) {
  return uint64_t(ptx_read32(p)) | (uint64_t(ptx_read32(p + 4)) << 32);
}
"""
ALIGNED_READERS = b"""static inline uint32_t ptx_read32(const uint8_t* p) {
  uint32_t value;
  __builtin_memcpy(&value, __builtin_assume_aligned(p, 4), sizeof(value));
  return value;
}
static inline uint64_t ptx_read64(const uint8_t* p) {
  uint64_t value;
  __builtin_memcpy(&value, __builtin_assume_aligned(p, 8), sizeof(value));
  return value;
}
"""
PROBE_SOURCE = b"""#include <stdint.h>
#include <vx_spawn2.h>
#include <vx_intrinsics.h>

__kernel void kernel_main(const uint8_t* __UNIFORM__ payload) {
  if (threadIdx.x == 0 && blockIdx.x == 0) {
    uintptr_t output = 0;
    for (unsigned i = 0; i != 8; ++i)
      output |= uintptr_t(payload[i]) << (8 * i);
    auto* words = reinterpret_cast<volatile uint32_t*>(output);
    const uint64_t a0 = uintptr_t(payload);
    const uint64_t mscratch = csr_read(VX_CSR_MSCRATCH);
    words[0] = uint32_t(a0);
    words[1] = uint32_t(a0 >> 32);
    words[2] = uint32_t(mscratch);
    words[3] = uint32_t(mscratch >> 32);
  }
}
"""
AUDIT_FILES = (
    "VX_types.toml", "sw/common/mem_alloc.h", "sw/runtime/common/common.h",
    "sw/runtime/common/device.cpp", "sw/runtime/common/vortex2_internal.h", "sw/runtime/common/queue.cpp",
    "sw/kernel/src/vx_start.S", "hw/rtl/VX_kmu.sv", "hw/rtl/core/VX_cta_dispatch.sv",
    "hw/rtl/core/VX_scheduler.sv", "sim/simx/kmu/kmu.cpp", "sim/simx/cta_dispatcher.cpp",
    "sim/simx/scheduler.cpp", "sim/simx/csr_unit.cpp", "tests/regression/common.mk",
)


def archives():
    for suffix in ARCHIVES:
        yield (PROJECT / "results" / ("u280-perf-kit-" + suffix) / "bundle",
               PROJECT / "results" / ("u280-perf-build-" + suffix))


def read_layout(module):
    manifest = read_json(module / "manifest.json")
    fields = manifest["params"]
    size = manifest["params_size"]
    require(manifest["abi_version"] == "ptx-vx-args-v1" and size in (24, 32) and manifest["params_align"] == 8,
            "unexpected archived parameter ABI")
    offset = 0
    for field in fields:
        width = {"u32": 4, "u64": 8}[field["type"]]
        offset = (offset + width - 1) // width * width
        require(field["align"] == field["size"] == width and field["offset"] == offset and offset + width <= size,
                "misaligned field: " + field["name"])
        offset += width
    require(fields[0]["name"] == "x" and fields[0]["type"] == "u64" and size == (offset + 7) // 8 * 8,
            "address probe requires x at payload offset zero and natural tail padding")
    return dict(bytes=size, alignment=manifest["params_align"], fields=fields)


def compile_device(directory, root, flags, rec, label):
    (directory / ".depend").write_text("# Device-only build; no host dependencies.\n", encoding="utf-8")
    run_stage(rec, label, ["make", "-C", directory, "ROOT_DIR=" + str(root), "VORTEX_HOME=" + str(VORTEX),
                           "XLEN=64", "KERNEL_LIB=vortex2", flags, "kernel.vxbin", "kernel.dump"], root, 180)
    inspect_vxbin((directory / "kernel.vxbin").read_bytes())
    return {name: sha256(directory / name) for name in ("kernel.cpp", "kernel_body.hpp", "Makefile", "kernel.vxbin",
                                                       "kernel.elf", "kernel.dump") if (directory / name).is_file()}


def build_variants(out, rec, report):
    lock_bytes = SIM_LOCK.read_bytes()
    lock, defines, _ = target(lock_bytes, SIM_LOCK.with_name("native_smoke.json").read_bytes())
    report["lock_sha256"] = sha256(SIM_LOCK)
    root = PROJECT / "build" / out.name
    root.mkdir(parents=True)
    head = run_stage(rec, "source_head", ["git", "-C", VORTEX, "rev-parse", "HEAD"], root).strip()
    require(head == lock["vortex"]["commit"], "wrong Vortex commit")
    diff = run_stage(rec, "source_diff", ["git", "-C", VORTEX, "diff", "HEAD", "--", "sw", "hw", "sim", "ci",
                                         "VX_types.toml", "tests/regression/common.mk"], root)
    require(not diff, "fixed source has local changes")
    report["source_sha256"] = {name: sha256(VORTEX / name) for name in AUDIT_FILES}
    common = (VORTEX / "tests/regression/common.mk").read_bytes()
    require(hashlib.sha1(b"blob " + str(len(common)).encode() + b"\0" + common).hexdigest() == MAKE_BLOB,
            "upstream SIMT build rules changed")
    report["tool_sha256"] = {name: sha256(TOOLCHAIN / name) for name in lock["toolchain"]["observed_file_sha256"]
                            if name.startswith(("llvm-vortex/", "libc64/", "libcrt64/", "riscv64-gnu-toolchain/"))}
    require(all(value == lock["toolchain"]["observed_file_sha256"][name] for name, value in report["tool_sha256"].items()),
            "tool hashes differ from model lock")
    flags = "CONFIGS=" + " ".join("-D%s=%d" % item for item in sorted(defines.items()))
    run_stage(rec, "configure", ["bash", VORTEX / "configure", "--xlen=64", "--tooldir=" + str(TOOLCHAIN)], root, 120)
    run_stage(rec, "kernel_library", ["make", "-j2", "-C", root / "sw/kernel", "XLEN=64", flags], root, 180)
    report["operators"] = {}
    makefile = None
    for bundle, old_build in archives():
        plan = preflight(bundle)
        require(sha256(old_build / "summary.json") == plan["build_summary_sha256"], "archived build differs")
        validate_images(old_build / "sim", SIM_LOCK, plan)
        for op in operations(plan):
            source = operator_path(plan, old_build / "sim", op) / "ptx"
            layout = read_layout(source)
            base_header = (source / "kernel_body.hpp").read_bytes()
            require(base_header.count(BYTE_READERS) == 1, "baseline parameter helper differs")
            header = base_header.replace(BYTE_READERS, ALIGNED_READERS)
            require(header.replace(ALIGNED_READERS, BYTE_READERS) == base_header, "change outside read helpers")
            details = dict(layout=layout, archive=str(source.relative_to(PROJECT)), variants={})
            report["operators"][op] = details
            patch = difflib.unified_diff(base_header.decode().splitlines(True), header.decode().splitlines(True),
                                         "bytewise/kernel_body.hpp", "aligned/kernel_body.hpp")
            (out / (op + "-readers.diff")).write_text("".join(patch), encoding="utf-8", newline="\n")
            for variant, body in (("bytewise", base_header), ("aligned", header)):
                directory = out / op / variant
                directory.mkdir(parents=True)
                for name in ("kernel.cpp", "Makefile"):
                    shutil.copyfile(source / name, directory / name)
                (directory / "kernel_body.hpp").write_bytes(body)
                details["variants"][variant] = compile_device(directory, root, flags, rec, op + "_" + variant)
            base, aligned = (details["variants"][name] for name in ("bytewise", "aligned"))
            require(base["kernel.vxbin"] == sha256(source / "kernel.vxbin") and
                    all(base[name] == aligned[name] == sha256(source / name) for name in ("kernel.cpp", "Makefile")),
                    "baseline image, wrapper or flags differ from archive")
            directory = out / op / "aligned"
            code = list(instructions(directory / "kernel.dump", directory / "kernel.vxbin"))
            require(all(opcode != "lbu" for _, opcode, _ in code), "aligned image still uses lbu: " + op)
            details["aligned_static_instructions"] = len(code)
            makefile = source / "Makefile"
    probe = out / "probe"
    probe.mkdir()
    (probe / "kernel.cpp").write_bytes(PROBE_SOURCE)
    (probe / "Makefile").write_bytes(makefile.read_bytes().replace(b"VX_HDRS := kernel_body.hpp", b"VX_HDRS :="))
    report["probe"] = compile_device(probe, root, flags, rec, "payload_address_probe")


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()
    out = args.output.resolve()
    require(out.parent == PROJECT / "results" and re.fullmatch(r"local-ptx-align-build-[a-z0-9-]+", out.name),
            "choose a new local build run under results")
    out.mkdir()
    report = dict(status="RUNNING", board_execution="NOT_RUN", commands=[], started_at=utc_now(),
                  argv=[sys.executable, "-B", *sys.argv], script_sha256=sha256(__file__))
    rec = Recorder(out, report, dict(os.environ))
    try:
        build_variants(out, rec, report)
        report.update(status="PASS", exit_code=0)
    except Exception as error:
        report.update(status="FAIL", exit_code=1, error=str(error))
    report["finished_at"] = utc_now()
    rec.save()
    print(report["status"], out, report.get("error", ""))
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
