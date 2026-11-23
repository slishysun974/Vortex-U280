"""P0 code generation for the versioned Vortex2 queue parameter contract.

The v1.2 parser and portable emitter remain the source of PTX semantics.
Only the device parameter decoder and its source-map line offsets change.
"""

import hashlib
import json
from pathlib import Path

import ptx_frontend_v12 as portable


COMPILER = "ptx-vx-frontend-v1.3"
DEVICE_PARAMETER_ACCESS = "vortex2-queue-args-align-v1"
DEVICE_BASE_ALIGNMENT = 64
MAX_PAYLOAD_BYTES = 4096

BYTEWISE_READERS = """static inline uint32_t ptx_read32(const uint8_t* p) {
  return uint32_t(p[0]) | (uint32_t(p[1]) << 8) | (uint32_t(p[2]) << 16) | (uint32_t(p[3]) << 24);
}
static inline uint64_t ptx_read64(const uint8_t* p) {
  return uint64_t(ptx_read32(p)) | (uint64_t(ptx_read32(p + 4)) << 32);
}
"""
ALIGNED_READERS = """static inline uint32_t ptx_read32(const uint8_t* p) {
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


def emit_cpp(ir):
    size = ir["params_size"]
    if not 0 < size <= MAX_PAYLOAD_BYTES:
        raise portable.PtxError("E_PARAM_LAYOUT", "aligned queue payload must contain 1 to 4096 bytes")
    for field in ir["params"]:
        width = {"u32": 4, "u64": 8}.get(field["type"])
        if (width is None or field["size"] != width or field["align"] != width
                or field["offset"] % width or not 0 <= field["offset"] <= size - width):
            raise portable.PtxError("E_PARAM_LAYOUT", "device parameter is not naturally aligned: " + field["name"])
    header, mapping = portable.emit_cpp(ir)
    if header.count(BYTEWISE_READERS) != 1:
        raise portable.PtxError("E_INPUT", "expected a single portable parameter reader section")
    first_line = header[:header.index(BYTEWISE_READERS)].count("\n") + 1
    delta = ALIGNED_READERS.count("\n") - BYTEWISE_READERS.count("\n")
    return header.replace(BYTEWISE_READERS, ALIGNED_READERS, 1), [
        dict(row, generated_line=row["generated_line"] + delta) if row["generated_line"] >= first_line else row
        for row in mapping
    ]


def write_codegen(output, ir):
    """Finalize the device artifacts after v1.2 writes the shared IR and ABI."""
    cpp, source_map = emit_cpp(ir)
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest.update(compiler_id=COMPILER, device_parameter_access=DEVICE_PARAMETER_ACCESS,
                    compiler_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    portable_compiler_sha256=manifest["compiler_sha256"])
    for name, data in (("kernel_body.hpp", cpp), ("source_map.json", json.dumps(source_map, indent=2) + "\n")):
        raw = data.encode("utf-8")
        (output / name).write_bytes(raw)
        manifest["files"][name] = hashlib.sha256(raw).hexdigest()
    manifest_path.write_bytes((json.dumps(manifest, indent=2) + "\n").encode("utf-8"))
