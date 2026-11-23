"""Freeze source-level answers without importing the compiler or runtime."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MASK = (1 << 32) - 1
# (block, grid, active elements, affine coefficient, selected thread within CTA)
SHAPES = [(1, 3, 0, 0, 0), (3, 5, 1, MASK, 2), (7, 3, 18, 0x80000001, 3),
          (16, 2, 32, 1, 15), (31, 3, 65, 7, 29), (32, 4, 127, MASK - 1, 32)]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def words(tag, size):
    edge = (MASK, 0, 1, 0x80000000, 0x7fffffff, MASK - 1)
    return [edge[(i // 4 + len(tag)) % len(edge)] if i % 4 == 0 else
            int.from_bytes(hashlib.blake2s(f"e-v14.20261122/{tag}/{i}".encode()).digest()[:4], "little")
            for i in range(size)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    out = parser.parse_args().output.resolve()
    out.mkdir()
    (out / "sources").mkdir()
    shutil.copyfile(__file__, out / "oracle.py")
    cases = []
    for op in ("copy", "vadd", "affine", "predicate_turn"):
        src = HERE / "predicate_turn.ptx" if op == "predicate_turn" else ROOT / "ptx/samples" / (op + "_u32.ptx")
        shutil.copyfile(src, out / "sources" / (op + ".ptx"))
        roles = ("x", "z") if op == "copy" else ("x", "y", "z")
        for seq, (block, grid, n, alpha, pick) in enumerate(SHAPES):
            name = f"{op}-{seq}"
            folder = out / name
            folder.mkdir()
            offset = {r: 2 + (seq * 3 + j * 5) % 11 for j, r in enumerate(roles)}
            total = grid * block
            data = {r: words(name + r, offset[r] + total + 9) for r in roles}
            expected = data["z"][:]
            for i in range(total if op == "predicate_turn" else n):
                x = data["x"][offset["x"] + i]
                y = data["y"][offset["y"] + i] if "y" in roles else 0
                if op == "predicate_turn":
                    value = (x + 1 if i < n else y - 1) + ((1 << 31) + 1 if i % block == pick else 0)
                else:
                    value = (alpha if op == "affine" else 1) * x + y
                expected[offset["z"] + i] = value & MASK
            for role, values in {**data, "expected-z": expected}.items():
                (folder / (role + ".bin")).write_bytes(struct.pack(f"<{len(values)}I", *values))
            cases.append(dict(id=name, op=op, roles=roles, offsets=offset, block=block,
                              grid=grid, n=n, alpha=alpha, selected=pick))
    files = {p.relative_to(out).as_posix(): sha(p) for p in sorted(out.rglob("*")) if p.is_file()}
    manifest = out / "manifest.json"
    manifest.write_bytes((json.dumps(dict(cases=cases, files=files), indent=2) + "\n").encode())
    receipt = dict(status="PASS", exit_code=0, argv=sys.argv, frozen_at_unix_ns=time.time_ns(),
                   cases=len(cases), manifest_sha256=sha(manifest), scope="source answers only")
    (out / "freeze.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
