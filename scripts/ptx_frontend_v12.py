"""Strict P0 PTX frontend. Emits reviewable C++ semantics, not a device image.

No kernel-name dispatch, implicit register initialization or CPU fallback.
The Memory template is an explicit integration seam; host tests are not SimX.
"""
import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import sys

PROJECT = Path(__file__).resolve().parents[1]
PROFILE = "ptx-vx-p0-v0.2-draft"
COMPILER = "ptx-vx-frontend-v1.2"
HOST_COMPATIBILITY = "python36-integer-v1"
ABI = "ptx-vx-args-v1"
SPECIALS = {"%tid.x": "thread_id", "%ntid.x": "block_size",
            "%ctaid.x": "block_id", "%nctaid.x": "grid_size"}
OPS = {
    "mov.u32": ("b32", "u32"), "mov.u64": ("b64", "u64"),
    "ld.param.u32": ("b32", "param32"), "ld.param.u64": ("b64", "param64"),
    "add.u32": ("b32", "u32", "u32"), "sub.u32": ("b32", "u32", "u32"),
    "mul.lo.u32": ("b32", "u32", "u32"), "mul.wide.u32": ("b64", "u32", "u32"),
    "add.u64": ("b64", "u64", "u64"), "cvta.to.global.u64": ("b64", "pointer"),
    "setp.lt.u32": ("pred", "u32", "u32"),
    "setp.ge.u32": ("pred", "u32", "u32"),
    "setp.eq.u32": ("pred", "u32", "u32"),
    "selp.u32": ("b32", "u32", "u32", "pred"),
    "ld.global.u32": ("b32", "address"), "st.global.u32": ("address", "u32"),
    "ret": (),
}
TOKEN = re.compile(r"\s+|//[^\n]*|/\*[\s\S]*?\*/|"
                   r"\d+\.\d+|0[xX][0-9a-fA-F]+U?|0[bB][01]+U?|[0-9]+U?|"
                   r"\.?[A-Za-z_$%][A-Za-z0-9_$]*(?:\.[A-Za-z0-9_$]+)*|"
                   r"[{}()\[\],;<>@!+\-]")
IDENTIFIER = re.compile(r"(?:[A-Za-z_][A-Za-z0-9_$]*|[$%][A-Za-z0-9_$]+)\Z")


class PtxError(ValueError):
    def __init__(self, code, message, location=None):
        super().__init__(message)
        self.code, self.location = code, location

    def to_dict(self):
        return dict(code=self.code, phase="frontend", message=str(self),
                    source_location=self.location, run_id=None, event_id=None,
                    generation=None, backend=None, native_status=None, evidence_path=None)


@dataclass(frozen=True)
class Token:
    text: str
    line: int
    column: int


def lex(source, filename):
    if len(source.encode("utf-8")) > 1024 * 1024:
        raise PtxError("E_UNSUPPORTED", "source exceeds frontend 1 MiB limit")
    result, pos, line, column = [], 0, 1, 1
    while pos < len(source):
        match = TOKEN.match(source, pos)
        if not match:
            raise PtxError("E_UNSUPPORTED", "unrecognized token or unterminated comment",
                           dict(file=filename, line=line, column=column))
        value = match.group()
        if not value.isspace() and not value.startswith(("//", "/*")):
            result.append(Token(value, line, column))
        lines = value.split("\n")
        if len(lines) > 1:
            line += len(lines) - 1
            column = len(lines[-1]) + 1
        else:
            column += len(value)
        pos = match.end()
    result.append(Token("<eof>", line, column))
    return result


class Parser:
    def __init__(self, source, filename):
        self.source, self.filename = source, filename
        self.tokens, self.index = lex(source, filename), 0
        self.params, self.registers, self.instructions = [], {}, []
        self.facts, self.versions = {}, {}

    @property
    def token(self):
        return self.tokens[self.index]

    def location(self, token=None):
        token = token or self.token
        return dict(file=self.filename, line=token.line, column=token.column)

    def fail(self, message, code="E_UNSUPPORTED", token=None):
        raise PtxError(code, message, self.location(token))

    def take(self, expected=None):
        token = self.token
        if expected is not None and token.text != expected:
            self.fail("expected %s, got %s" % (expected, token.text))
        if token.text == "<eof>":
            self.fail("unexpected end of input")
        self.index += 1
        return token

    def accept(self, value):
        if self.token.text == value:
            self.take()
            return True
        return False

    def name(self):
        token = self.take()
        if not IDENTIFIER.fullmatch(token.text):
            self.fail("invalid identifier: " + token.text, "E_TYPE", token)
        return token

    def integer(self):
        sign = -1 if self.accept("-") else 1
        if sign == 1:
            self.accept("+")
        token = self.take()
        # Same single-suffix rule as str.removesuffix, available on Python 3.6.
        value = token.text[:-1] if token.text.endswith("U") else token.text
        try:
            if re.fullmatch(r"0[xX][0-9a-fA-F]+", value):
                number = int(value, 16)
            elif re.fullmatch(r"0[bB][01]+", value):
                number = int(value, 2)
            elif re.fullmatch(r"0[0-7]*", value):
                number = int(value, 8)
            elif re.fullmatch(r"[1-9][0-9]*", value):
                number = int(value, 10)
            else:
                raise ValueError()
        except ValueError:
            self.fail("invalid integer literal", "E_TYPE", token)
        if number >= 1 << 64:
            self.fail("integer literal exceeds 64 bits", "E_TYPE", token)
        return sign * number

    def parse(self):
        for key, expected in ((".version", "7.0"), (".target", "sm_70"), (".address_size", "64")):
            self.take(key)
            token = self.take()
            if token.text != expected:
                self.fail(key + " must be " + expected, "E_PTX_VERSION", token)
        self.accept(".visible")
        self.take(".entry")
        entry = self.name().text
        self.take("(")
        offset, alignment = 0, 1
        if self.token.text != ")":
            while True:
                self.take(".param")
                kind = self.take()
                if kind.text not in (".u32", ".u64"):
                    self.fail("only scalar .u32/.u64 entry parameters are supported", "E_TYPE", kind)
                name = self.name()
                if any(p["name"] == name.text for p in self.params):
                    self.fail("duplicate parameter", "E_PARAM_LAYOUT", name)
                size = 8 if kind.text == ".u64" else 4
                offset = (offset + size - 1) // size * size
                self.params.append(dict(name=name.text, type=kind.text[1:],
                                        kind="pointer" if size == 8 else "scalar",
                                        space="global" if size == 8 else None,
                                        size=size, align=size, offset=offset))
                offset += size
                alignment = max(alignment, size)
                if not self.accept(","):
                    break
        self.take(")")
        self.take("{")
        while self.token.text == ".reg":
            self.declaration()
        while self.token.text not in ("}", "<eof>"):
            if len(self.instructions) >= 65536:
                self.fail("instruction count exceeds implementation limit")
            self.instruction()
            if self.instructions[-1]["opcode"] == "ret":
                break
        if not self.instructions or self.instructions[-1]["opcode"] != "ret":
            self.fail("entry must end with unconditional ret")
        self.take("}")
        if self.token.text != "<eof>":
            self.fail("only one entry; no trailing declarations or instructions")
        return dict(schema_version="ptx-vx-ir-v1", compiler_id=COMPILER, profile=PROFILE,
                    abi_version=ABI, source_file=self.filename,
                    source_sha256=hashlib.sha256(self.source.encode("utf-8")).hexdigest(),
                    source_ptx_version="7.0", source_target="sm_70", source_address_bits=64,
                    entry=entry, params=self.params, params_align=alignment,
                    params_size=(offset + alignment - 1) // alignment * alignment,
                    registers=self.registers, instructions=self.instructions,
                    logical_launch_model="ptx-1d-v1", static_shared_bytes=0,
                    required_features=["rv64", "little-endian", "logical-1d-threads", "predicated-memory"],
                    memory_assumptions=["live global buffers", "u32 access alignment 4",
                                        "all active accesses in declared allocation", "no data races"],
                    status="FRONTEND_ONLY", device_image="NOT_RUN")

    def declaration(self):
        self.take(".reg")
        token = self.take()
        kind = token.text[1:]
        if token.text not in (".pred", ".b32", ".b64"):
            self.fail("unsupported register type", "E_TYPE", token)
        while True:
            name = self.name()
            names = [name.text]
            if self.accept("<"):
                count = self.integer()
                if not 1 <= count <= 4096:
                    self.fail("register array count must be 1..4096", "E_TYPE")
                self.take(">")
                names = [name.text + str(i) for i in range(count)]
            for item in names:
                if item in self.registers or any(p["name"] == item for p in self.params):
                    self.fail("duplicate symbol: " + item, "E_TYPE", name)
                if len(self.registers) >= 4096:
                    self.fail("total register count exceeds 4096", "E_TYPE", name)
                self.registers[item] = dict(type=kind, bit_width={"b32": 32, "b64": 64, "pred": 1}[kind],
                                            c_name="v" + str(len(self.registers)), source_location=self.location(name))
                self.facts[item] = {"defined": set(), "global": set()}
                self.versions[item] = 0
            if not self.accept(","):
                break
        self.take(";")

    def known(self, name, fact, guard):
        values = self.facts[name][fact]
        return None in values or (guard is not None and guard in values)

    def register(self, kind, guard, write=False):
        token = self.take()
        name = token.text
        if name not in self.registers or self.registers[name]["type"] != kind:
            self.fail("expected declared .%s register, got %s" % (kind, name), "E_TYPE", token)
        if not write and not self.known(name, "defined", guard):
            self.fail("register may be uninitialized on active path: " + name, "E_TYPE", token)
        return dict(kind="register", name=name, type=kind)

    def operand(self, kind, guard, opcode):
        if kind in ("b32", "b64"):
            return self.register(kind, guard, write=True)
        if kind == "pred":
            return self.register("pred", guard)
        if kind.startswith("param"):
            self.take("[")
            name = self.take()
            parameter = next((p for p in self.params if p["name"] == name.text), None)
            offset = self.integer() if self.token.text in ("+", "-") else 0
            self.take("]")
            if parameter is None or parameter["size"] * 8 != int(kind[5:]) or offset != 0:
                self.fail("parameter load must match whole declared scalar at offset zero", "E_PARAM_LAYOUT", name)
            return dict(kind="parameter", name=name.text, offset=parameter["offset"], type=parameter["type"])
        if kind == "address":
            self.take("[")
            operand = self.register("b64", guard)
            if not self.known(operand["name"], "global", guard):
                self.fail("address lacks global parameter provenance", "E_TYPE")
            offset = self.integer() if self.token.text in ("+", "-") else 0
            if offset % 4:
                self.fail("global u32 offset is not aligned to 4 bytes", "E_TYPE")
            self.take("]")
            return dict(kind="address", name=operand["name"], offset=offset, space="global", type="u64")
        if kind == "pointer":
            operand = self.register("b64", guard)
            if not self.known(operand["name"], "global", guard):
                self.fail("cvta requires a proven global parameter-derived pointer", "E_TYPE")
            return operand
        if self.token.text in SPECIALS:
            if opcode != "mov.u32":
                self.fail("special registers are accepted only as mov.u32 sources", "E_TYPE")
            return dict(kind="special", name=self.take().text, type="u32")
        if self.token.text in self.registers or IDENTIFIER.fullmatch(self.token.text):
            return self.register("b" + kind[1:], guard)
        return dict(kind="immediate", value=self.integer() % (1 << int(kind[1:])), type=kind)

    def write_fact(self, name, fact, guard, value):
        values = self.facts[name][fact]
        if guard is None:
            self.facts[name][fact] = {None} if value else set()
        elif value:
            values.add(guard)
            complement = (guard[0], guard[1], not guard[2])
            if complement in values:
                self.facts[name][fact] = {None}
        else:
            complement = (guard[0], guard[1], not guard[2])
            self.facts[name][fact] = {complement} if None in values or complement in values else set()

    def instruction(self):
        start, guard, predicate = self.token, None, None
        if self.accept("@"):
            negate = self.accept("!")
            operand = self.register("pred", None)
            name = operand["name"]
            guard = (name, self.versions[name], not negate)
            predicate = dict(name=name, negated=negate)
        op_token = self.take()
        opcode = op_token.text
        if opcode not in OPS:
            self.fail("unsupported instruction form: " + opcode, token=op_token)
        if guard is not None and (opcode == "ret" or opcode.startswith("ld.param")):
            self.fail("predicated ret/ld.param is outside this profile", token=op_token)
        operands = []
        for i, kind in enumerate(OPS[opcode]):
            if i:
                self.take(",")
            if i == 0 and kind == "pred":
                operands.append(self.register("pred", guard, write=True))
            else:
                operands.append(self.operand(kind, guard, opcode))
        self.take(";")
        if operands and opcode != "st.global.u32":
            dest = operands[0]["name"]
            source_ptrs = [o["kind"] == "register" and self.known(o["name"], "global", guard)
                           for o in operands[1:]]
            pointer = (opcode == "ld.param.u64" or opcode == "cvta.to.global.u64" or
                       (opcode == "mov.u64" and source_ptrs[0]) or
                       (opcode == "add.u64" and sum(source_ptrs) == 1))
            self.write_fact(dest, "defined", guard, True)
            self.write_fact(dest, "global", guard, pointer)
            if self.registers[dest]["type"] == "pred":
                self.versions[dest] += 1
        self.instructions.append(dict(opcode=opcode, operands=operands, predicate=predicate,
                                      source_location=self.location(start)))


def parse(source, filename="source.ptx"):
    return Parser(source, filename).parse()


def pack_arguments(ir, values):
    """Low-level serialization only. Addresses must already be runtime-validated.

    This function is not the handle/range/lifecycle validator specified by V06.
    """
    if len(values) != len(ir["params"]):
        raise PtxError("E_PARAM_LAYOUT", "argument count mismatch")
    payload = bytearray(ir["params_size"])
    for param, value in zip(ir["params"], values):
        if type(value) is not int or not 0 <= value < 1 << (8 * param["size"]):
            raise PtxError("E_PARAM_LAYOUT", "out-of-range integer for " + param["name"])
        offset = param["offset"]
        payload[offset:offset + param["size"]] = value.to_bytes(param["size"], "little")
    return bytes(payload)


def emit_cpp(ir):
    registers = ir["registers"]
    def reg(name):
        return registers[name]["c_name"]
    def value(op):
        if op["kind"] == "register":
            return reg(op["name"])
        if op["kind"] == "immediate":
            return "UINT%s_C(%d)" % (op["type"][1:], op["value"])
        if op["kind"] == "special":
            return "thread." + SPECIALS[op["name"]]
        if op["kind"] == "parameter":
            return "ptx_read%s(payload + %d)" % (op["type"][1:], op["offset"])
        if op["kind"] == "address":
            return "(%s + UINT64_C(%d))" % (reg(op["name"]), op["offset"] % (1 << 64))
        raise AssertionError(op)
    lines = ["// Generated semantic body; no device loader, launch or memory sandbox.",
             "#pragma once", "#include <stdint.h>",
             "struct PtxThread { uint32_t thread_id, block_size, block_id, grid_size; };",
             "static inline uint32_t ptx_read32(const uint8_t* p) {",
             "  return uint32_t(p[0]) | (uint32_t(p[1]) << 8) | (uint32_t(p[2]) << 16) | (uint32_t(p[3]) << 24);", "}",
             "static inline uint64_t ptx_read64(const uint8_t* p) {",
             "  return uint64_t(ptx_read32(p)) | (uint64_t(ptx_read32(p + 4)) << 32);", "}",
             "template<class Memory>",
             "static inline void ptx_body([[maybe_unused]] const uint8_t* payload, [[maybe_unused]] const PtxThread& thread, [[maybe_unused]] Memory& memory) {"]
    for item in registers.values():
        # PTX permits unused declarations and dead register writes. Keep the
        # semantics explicit without disabling the native compiler's warnings.
        lines.append("  [[maybe_unused]] %s %s;" % ({"b32": "uint32_t", "b64": "uint64_t", "pred": "bool"}[item["type"]], item["c_name"]))
    source_map = []
    for ins in ir["instructions"]:
        op, operands = ins["opcode"], ins["operands"]
        args = [value(o) for o in operands]
        if op == "ret":
            statement = "return;"
        elif op == "st.global.u32":
            statement = "memory.store32(%s, %s);" % tuple(args)
        else:
            dest, src = args[0], args[1:]
            if op.startswith(("mov.", "ld.param.", "cvta.")):
                expression = src[0]
            elif op.startswith(("add.", "sub.", "mul.lo.")):
                operator = "-" if op.startswith("sub.") else "*" if op.startswith("mul.") else "+"
                width = 64 if op.endswith("u64") else 32
                expression = "uint%d_t(%s %s %s)" % (width, src[0], operator, src[1])
            elif op == "mul.wide.u32":
                expression = "(uint64_t(%s) * uint64_t(%s))" % tuple(src)
            elif op.startswith("setp."):
                expression = "(%s %s %s)" % (src[0], {"lt": "<", "ge": ">=", "eq": "=="}[op.split(".")[1]], src[1])
            elif op == "selp.u32":
                expression = "(%s ? %s : %s)" % (src[2], src[0], src[1])
            elif op == "ld.global.u32":
                expression = "memory.load32(%s)" % src[0]
            else:
                raise AssertionError(op)
            # An in-place mov/cvta is already validated by the typed parser.
            # Keep its source-map slot and predicate without emitting x = x,
            # which the pinned Clang correctly rejects under -Werror.
            statement = "(void)0; /* identity */" if dest == expression else dest + " = " + expression + ";"
        predicate = ins["predicate"]
        if predicate:
            statement = "if (%s%s) { %s }" % ("!" if predicate["negated"] else "", reg(predicate["name"]), statement)
        lines.append("  " + statement)
        source_map.append(dict(generated_line=len(lines), **ins["source_location"]))
    lines.append("}")
    return "\n".join(lines) + "\n", source_map


def compile_source(source, output, filename="source.ptx", target_lock=None):
    ir = parse(source, filename)
    cpp, source_map = emit_cpp(ir)
    lock_data = None
    if target_lock is not None:
        lock_data = Path(target_lock).read_bytes()
        lock = json.loads(lock_data)
        if not isinstance(lock, dict) or lock.get("xlen") != 64 or lock.get("endianness") != "little":
            raise PtxError("E_TARGET_MISMATCH", "requires RV64 little-endian target")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    artifacts = {"source.ptx": source, "ir.json": json.dumps(ir, indent=2) + "\n",
                 "kernel_body.hpp": cpp, "source_map.json": json.dumps(source_map, indent=2) + "\n"}
    for name, content in artifacts.items():
        (output / name).write_text(content, encoding="utf-8", newline="\n")
    manifest = dict(schema_version="ptx-vx-frontend-artifacts-v1", compiler_id=COMPILER,
                    profile=PROFILE, abi_version=ABI, entry=ir["entry"],
                    compiler_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    params=ir["params"], params_size=ir["params_size"], params_align=ir["params_align"],
                    status="FRONTEND_ONLY", loadable=False, image_file=None,
                    target_lock_hash=None, backend_execution="NOT_RUN",
                    independent_acceptance="NOT_RUN",
                    files={name: hashlib.sha256((output / name).read_bytes()).hexdigest() for name in artifacts})
    if lock_data is not None:
        (output / "target_lock.json").write_bytes(lock_data)
        manifest["target_lock_hash"] = hashlib.sha256(lock_data).hexdigest()
        manifest["files"]["target_lock.json"] = manifest["target_lock_hash"]
    for name in ("profile.json", "abi.json"):
        config = PROJECT / "configs/ptx_frontend/v1" / name
        data = config.read_bytes()
        (output / name).write_bytes(data)
        manifest["files"][name] = hashlib.sha256(data).hexdigest()
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return ir


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True, help="new directory; never overwrites")
    parser.add_argument("--target-lock", type=Path, default=PROJECT / "configs/target_lock.json")
    args = parser.parse_args(argv)
    try:
        source = args.source.read_bytes().decode("utf-8")
        ir = compile_source(source, args.output, str(args.source), args.target_lock)
    except (PtxError, OSError, UnicodeError, ValueError) as exc:
        error = exc.to_dict() if isinstance(exc, PtxError) else dict(code="E_INPUT", message=str(exc))
        print(json.dumps(dict(status="FAIL", error=error)))
        return 1
    print(json.dumps(dict(status="PASS", scope="frontend translation only", entry=ir["entry"], output=str(args.output))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
