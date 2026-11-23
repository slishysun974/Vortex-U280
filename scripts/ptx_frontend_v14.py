"""Aligned P0 lowering for consecutive, stable predicates on device code."""

import hashlib
from itertools import groupby
import json
from pathlib import Path

import ptx_frontend_v12 as portable
import ptx_frontend_v13 as aligned


COMPILER = "ptx-vx-frontend-v1.4"
PREDICATE_LOWERING = "same-predicate-v1"
GLOBAL_MEMORY = {"ld.global.u32", "st.global.u32"}
MERGEABLE = GLOBAL_MEMORY | {
    "mov.u32", "mov.u64", "add.u32", "sub.u32", "mul.lo.u32", "mul.wide.u32",
    "add.u64", "cvta.to.global.u64", "selp.u32",
}


def merge_guard(instruction):
    # Predicate writes are explicit boundaries even when they write a different
    # predicate. The remaining forms only write integer registers or global memory.
    guard = instruction["predicate"]
    if guard and instruction["opcode"] in MERGEABLE:
        return guard["name"], guard["negated"]
    return None


def emit_cpp(ir):
    header, mapping = aligned.emit_cpp(ir)
    original = header.splitlines()
    start = mapping[0]["generated_line"] - 1
    end = start + len(mapping)
    if [row["generated_line"] for row in mapping] != list(range(start + 1, end + 1)):
        raise portable.PtxError("E_INPUT", "expected consecutive generated statements")
    lines, source_map = original[:start], []
    records = zip(ir["instructions"], mapping, original[start:end])
    for guard, members in groupby(records, key=lambda row: merge_guard(row[0])):
        region = list(members)
        merge = guard is not None and len(region) > 1 and any(ins["opcode"] in GLOBAL_MEMORY for ins, _, _ in region)
        if merge:
            name, negated = guard
            expr = ("!" if negated else "") + ir["registers"][name]["c_name"]
            prefix = "  if (" + expr + ") {"
            lines.append(prefix)
        for _, row, statement in region:
            if merge:
                if not statement.startswith(prefix + " ") or not statement.endswith(" }"):
                    raise portable.PtxError("E_INPUT", "aligned emitter no longer matches the typed guard")
                # Keep each full statement, including volatile loads and stores,
                # in the original order and under the single stable guard.
                statement = "    " + statement[len(prefix) + 1:-2]
            lines.append(statement)
            source_map.append(dict(row, generated_line=len(lines)))
        if merge:
            lines.append("  }")
    lines.extend(original[end:])
    return "\n".join(lines) + "\n", source_map


def write_codegen(output, ir):
    cpp, source_map = emit_cpp(ir)
    path = output / "manifest.json"
    manifest = json.loads(path.read_bytes())
    manifest.update(compiler_id=COMPILER, predicate_lowering=PREDICATE_LOWERING,
                    device_parameter_access=aligned.DEVICE_PARAMETER_ACCESS,
                    compiler_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    portable_compiler_sha256=manifest["compiler_sha256"])
    for name, data in (("kernel_body.hpp", cpp), ("source_map.json", json.dumps(source_map, indent=2) + "\n")):
        raw = data.encode("utf-8")
        (output / name).write_bytes(raw)
        manifest["files"][name] = hashlib.sha256(raw).hexdigest()
    path.write_bytes((json.dumps(manifest, indent=2) + "\n").encode("utf-8"))
