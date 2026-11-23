"""Create deterministic C receiver vectors from the two delivered PTX programs."""
import argparse
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
WORDS = 224
ROLES = ("x", "z", "audit")
MASK = 0xffffffff
# (id, entry, block, grid, scalar arguments, x/z/audit pointer offsets in words)
CASES = (
    ("partial_forms", FORMS, 3, 1, [0x40000001], (7, 11, 2)),
    ("second_warp", WIDE, 5, 5, [23, 4, 0x40000002], (3, 8, 13)),
    ("full_forms", FORMS, 4, 1, [0x40000003], (11, 3, 7)),
    ("seventeen", WIDE, 17, 3, [48, 12, 0x40000004], (9, 6, 1)),
    ("single_form_lane", FORMS, 1, 1, [0x40000005], (1, 17, 3)),
    ("max_block", WIDE, 32, 2, [64, 29, 0x40000003], (5, 4, 7)),
    ("tail_hole", WIDE, 7, 4, [17, 2, 0x40000001], (12, 2, 9)),
    ("zero_active", WIDE, 9, 2, [0, 1, 0x40000002], (1, 13, 5)),
)


def fill(case, role):
    values = []
    for index in range(WORDS):
        digest = hashlib.sha256(f"c-v03-receipt-v1/{case}/{role}/{index}".encode()).digest()
        values.append(int.from_bytes(digest[:4], "little"))
    return values


def form_outputs(buffers, offsets, block, bias):
    x, z = buffers["x"], buffers["z"]
    start, output = offsets["x"], offsets["z"]
    for lane in range(block):
        a, alt = x[start + lane], x[start + lane + 4]
        low, equal = a < 2**31, a == MASK
        seed = 0x5a5a5a5a
        # For each opcode, record its active result and its pre-instruction destination.
        pairs = ((a, seed), (a, alt), ((a + 1) & MASK, seed), ((a - 1) & MASK, seed),
                 ((3 * a) & MASK, seed), (x[start + lane + bias - 2**30], alt),
                 (a, alt), (a, alt), (int(low), int(not low)), (int(not low), int(low)),
                 (int(equal), int(not equal)), (0x52 if low else 0x61, seed), (a, seed))
        for group, (result, previous) in enumerate(pairs):
            for mode, enabled in enumerate((True, lane < 2, lane >= 2)):
                z[output + lane + 4 * (group * 3 + mode)] = result if enabled else previous
        for mode, enabled in enumerate((True, lane < 2, lane >= 2)):
            if enabled:
                z[output + lane + 4 * (39 + mode)] = a


def wide_outputs(buffers, offsets, block, grid, scalars):
    n, skipped_tid, bias = scalars
    for cta in range(grid):
        for tid in range(block):
            i = cta * block + tid
            a = 0xa5a55a5a
            if i < n and tid != skipped_tid:
                j = i + bias - 2**30
                a = buffers["x"][offsets["x"] + j]
                buffers["z"][offsets["z"] + j + 1] = (a + int(a >= 2**31)) & MASK
            buffers["audit"][offsets["audit"] + i] = (a + grid) & MASK


def write_json(path, value):
    path.write_bytes((json.dumps(value, indent=2, sort_keys=True) + "\n").encode())


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze(root):
    (root / "sources").mkdir()
    for name in (FORMS, WIDE):
        shutil.copyfile(PROJECT / "ptx/probes" / (name + ".ptx"), root / "sources" / (name + ".ptx"))
    shutil.copyfile(__file__, root / "oracle.py")
    cases = []
    for number, (cid, entry, block, grid, scalars, starts) in enumerate(CASES):
        directory = root / cid
        directory.mkdir()
        offsets = dict(zip(ROLES, starts))
        inputs = {role: fill(cid, role) for role in ROLES}
        edges = (0xffffffff, 0x7fffffff, 0, 0x80000000, 0x80000001, 1, 0xfffffffe, 0x7ffffffe)
        start = offsets["x"]
        inputs["x"][start:start+8] = [edges[(number + i) % 8] for i in range(8)]
        expected = {r: data.copy() for r, data in inputs.items()}
        if entry == FORMS:
            form_outputs(expected, offsets, block, scalars[0])
        else:
            wide_outputs(expected, offsets, block, grid, scalars)
        for role in ROLES:
            for suffix, arrays in (("input", inputs), ("expected", expected)):
                (directory / (role + "." + suffix + ".bin")).write_bytes(struct.pack("<224I", *arrays[role]))
        cases.append(dict(id=cid, entry=entry, block=block, grid=grid, offsets=offsets, scalars=scalars))
    files = {p.relative_to(root).as_posix(): file_hash(p) for p in root.rglob("*") if p.is_file()}
    write_json(root / "manifest.json", dict(schema="c-v03-receiver-v1", words=WORDS, cases=cases, files=files))
    return file_hash(root / "manifest.json")


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--run-id", required=True)
    args = cli.parse_args()
    if not re.fullmatch(r"c-v03-corpus-[A-Za-z0-9_-]{1,64}", args.run_id):
        cli.error("choose a fresh c-v03-corpus-* identifier")
    root = PROJECT / "results" / args.run_id
    root.mkdir()
    digest = freeze(root)
    write_json(root / "freeze.json", dict(argv=sys.argv, status="PASS", exit_code=0,
               scope="C receiver inputs and answers, no model execution", manifest_sha256=digest))
    print(digest)


if __name__ == "__main__":
    main()
