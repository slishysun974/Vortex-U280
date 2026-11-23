"""Freeze new A/E vectors by interpreting the two PTX source files on the host."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import sys

PROJECT = Path(__file__).resolve().parents[1]
FORMS = "p0_form_witness"
WIDE = "guarded_wide_offset"
ROLES = ("x", "z", "audit")
LIMIT = 1 << 32
MASK = LIMIT - 1
BIAS = 1 << 30
LOW, HIGH, CROSS, OTHER = 0x03200000, 0x103200000, 0xffffff80, 0x104400000
ALIAS = {"low": LOW, "high": HIGH}


def case(name, entry, block, grid, offsets, values, bases=None):
    return dict(id=name, entry=entry, block=block, grid=grid, offsets=dict(zip(ROLES, offsets)),
                scalars=list(values), bases=None if bases is None else dict(zip(ROLES, bases)),
                words=256 if bases is None else 64)


CASES = (
    case("forms_four", FORMS, 4, 1, (9, 5, 4), (BIAS + 11,)),
    case("wide_second_warp", WIDE, 6, 5, (3, 11, 8), (26, 4, BIAS + 7)),
    case("forms_three", FORMS, 3, 1, (13, 17, 3), (BIAS + 9,)),
    case("wide_partial_third", WIDE, 10, 4, (7, 5, 12), (34, 8, BIAS + 3)),
    case("forms_two", FORMS, 2, 1, (6, 23, 7), (BIAS + 7,)),
    case("wide_several_warps", WIDE, 19, 3, (11, 13, 7), (52, 15, BIAS + 5)),
    case("wide_near_resident_limit", WIDE, 31, 3, (4, 9, 15), (65, 28, BIAS + 9)),
    case("wide_all_masked", WIDE, 9, 4, (5, 12, 11), (0, 7, BIAS + 3)),
    case("new_low_to_high", WIDE, 4, 6, (4, 6, 9), (21, 1, BIAS + 3), (LOW, HIGH, OTHER)),
    case("new_high_to_low", WIDE, 4, 7, (5, 8, 7), (26, 3, BIAS + 4), (HIGH, LOW, OTHER)),
    case("new_cross_read", WIDE, 4, 7, (9, 7, 11), (25, 3, BIAS + 5), (CROSS, HIGH, LOW)),
    case("new_cross_write", WIDE, 4, 8, (8, 10, 6), (29, 0, BIAS + 2), (HIGH, CROSS, LOW)),
    case("new_cross_audit", WIDE, 3, 9, (7, 8, 13), (0, 1, BIAS + 6), (LOW, HIGH, CROSS)),
)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def save(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def instructions(source):
    body = False
    for number, raw in enumerate(source.splitlines(), 1):
        line = raw.split("//", 1)[0].strip()
        if not body:
            body = line.endswith("{")
            continue
        if not line or line.startswith(".reg ") or line == "}":
            continue
        if not line.endswith(";"):
            raise ValueError("unsupported source line {}: {}".format(number, line))
        line = line[:-1]
        pred = None
        if line.startswith("@"):
            pred, line = line[1:].split(None, 1)
        parts = line.split(None, 1)
        yield number, pred, parts[0], parts[1].split(",") if len(parts) > 1 else []


def evaluate(ops, spec, initial):
    data = {role: words[:] for role, words in initial.items()}
    bases = spec["bases"] or dict(zip(ROLES, (0x10000, 0x30000, 0x50000)))
    params = {r: base + 4 * spec["offsets"][r] for r, base in bases.items()}
    names = ("bias",) if spec["entry"] == FORMS else ("n", "skip_lane", "bias")
    params.update(zip(names, spec["scalars"]))
    requests, suppressed, stores = [], [], set()
    for cta in range(spec["grid"]):
        for lane in range(spec["block"]):
            regs = {"%tid.x": lane, "%ntid.x": spec["block"], "%ctaid.x": cta, "%nctaid.x": spec["grid"]}

            def value(token):
                token = token.strip()
                if token.startswith("["):
                    name, displacement = re.fullmatch(r"\[([A-Za-z_]\w*)([+-]\d+)?\]", token).groups()
                    return regs.get(name, params.get(name)) + int(displacement or "0")
                return regs[token] if token in regs else int(token, 0)

            for number, pred, op, args in ops:
                enabled = pred is None or bool(regs[pred.lstrip("!")]) != pred.startswith("!")
                is_store, is_load = op == "st.global.u32", op == "ld.global.u32"
                if not enabled:
                    if is_store or is_load:
                        address = value(args[0 if is_store else 1])
                        suppressed.append([cta, lane, number, "ST" if is_store else "LD", address])
                    continue
                if op == "ret":
                    break
                if is_store or is_load:
                    address = value(args[0 if is_store else 1])
                    matches = [(role, (address - base) // 4) for role, base in bases.items()
                               if base <= address and address + 4 <= base + 4 * len(data[role])]
                    if len(matches) != 1 or address % 4:
                        raise ValueError("invalid active access {} {}".format(spec["id"], hex(address)))
                    role, index = matches[0]
                    requests.append([cta, lane, number, "ST" if is_store else "LD", role, index])
                    if is_store:
                        if (role, index) in stores:
                            raise ValueError("test would have competing stores")
                        stores.add((role, index))
                        data[role][index] = value(args[1]) & MASK
                    else:
                        regs[args[0].strip()] = data[role][index]
                    continue
                values = [value(v) for v in args[1:]]
                width = (1 << 64) - 1 if op.endswith(".u64") or op == "mul.wide.u32" else MASK
                if op.startswith(("ld.param.", "mov.", "cvta.to.global.")):
                    answer = values[0]
                elif op.startswith("add."):
                    answer = values[0] + values[1]
                elif op == "sub.u32":
                    answer = values[0] - values[1]
                elif op in ("mul.lo.u32", "mul.wide.u32"):
                    answer = values[0] * values[1]
                elif op.startswith("setp."):
                    answer = {"eq": values[0] == values[1], "ge": values[0] >= values[1],
                              "lt": values[0] < values[1]}[op.split(".")[1]]
                elif op == "selp.u32":
                    answer = values[0 if values[2] else 1]
                else:
                    raise ValueError("unsupported oracle opcode: " + op)
                regs[args[0].strip()] = answer & width
    return data, requests, suppressed


def words(label, size):
    return [int.from_bytes(hashlib.blake2s(("ae-v03-20261121/" + label + "/" + str(i)).encode()).digest()[:4], "little")
            for i in range(size)]


def binary(path, values):
    path.write_bytes(struct.pack("<{}I".format(len(values)), *values))


def freeze(out):
    source = out / "sources"
    source.mkdir()
    programs = {}
    for entry in (FORMS, WIDE):
        path = PROJECT / "ptx/probes" / (entry + ".ptx")
        shutil.copyfile(path, source / path.name)
        programs[entry] = tuple(instructions(path.read_text(encoding="utf-8")))
    shutil.copyfile(__file__, out / "oracle.py")
    for spec in CASES:
        directory = out / spec["id"]
        directory.mkdir()
        initial = {role: words(spec["id"] + "/" + role, spec["words"]) for role in ROLES}
        offset = spec["offsets"]["x"]
        edges = (0xffffffff, 0x80000000, 0x7fffffff, 0, 1, 0x80000001, 0xfffffffe, 0x40000000)
        for i in range(offset, len(initial["x"]), 5):
            initial["x"][i] = edges[(i - offset) // 5 % len(edges)]
        if spec["entry"] == FORMS:
            initial["x"][offset:offset + 4] = edges[spec["block"] - 2:spec["block"] + 2]
        expected, requests, suppressed = evaluate(programs[spec["entry"]], spec, initial)
        for role in ROLES:
            binary(directory / (role + ".input.bin"), initial[role])
            binary(directory / (role + ".expected.bin"), expected[role])
        save(directory / "requests.json", dict(accesses=requests, suppressed=suppressed))
        if spec["id"].startswith("new_cross_"):
            pair = {spec["bases"][role] + 4 * index for _, _, _, _, role, index in requests}
            if not {LIMIT - 4, LIMIT} <= pair:
                raise ValueError("case lacks live adjacent boundary addresses: " + spec["id"])
    alias = out / "alias"
    alias.mkdir()
    for epoch in (1, 2):
        for role in ALIAS:
            binary(alias / ("{}-{}.bin".format(epoch, role)), words("alias/{}/{}".format(epoch, role), 64))
    files = {p.relative_to(out).as_posix(): digest(p.read_bytes()) for p in sorted(out.rglob("*")) if p.is_file()}
    save(out / "manifest.json", dict(schema="ae-v03-source-oracle-v1", cases=CASES, alias=ALIAS,
                                    files=files, source="direct PTX interpreter and BLAKE2s input words"))
    return digest((out / "manifest.json").read_bytes())


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--run-id", required=True)
    args = cli.parse_args()
    if not re.fullmatch(r"ae-v03-frozen-[A-Za-z0-9_-]{1,48}", args.run_id):
        cli.error("choose a fresh ae-v03-frozen-* identifier")
    out = PROJECT / "results" / args.run_id
    out.mkdir()
    report = dict(argv=[sys.executable, "-B", *sys.argv], scope="source oracle only", devices="NOT_RUN")
    try:
        report.update(manifest_sha256=freeze(out), status="PASS", exit_code=0)
    except Exception as error:
        report.update(status="FAIL", exit_code=1, error=str(error))
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    save(out / "freeze.json", report)
    print(json.dumps(report))
    sys.exit(report["exit_code"])
