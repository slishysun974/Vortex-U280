"""Verify the staged U280 pair and frozen answers without touching a device."""

import argparse
import hashlib
import json
from pathlib import Path
import struct


SCHEMA = "u280-aligned-predicate-pair-staging-v1"
OPERATORS = ("copy", "vadd", "affine")
ROUTES = ("aligned", "merged")
COUNTS = (1024, 16381)
ROLES = {"copy": ("x", "z"), "vadd": ("x", "y", "z"), "affine": ("x", "y", "z")}
ALPHA = 0x9e3779b9
GUARD, BLOCK = 16, 32


def sha(path):
    with Path(path).open("rb") as stream:
        h = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def require(condition, message):
    if not condition:
        raise ValueError(message)


def geometry(n):
    grid = (n + BLOCK - 1) // BLOCK
    return dict(n=n, grid=grid, block=BLOCK, words=grid * BLOCK + 2 * GUARD)


def layout(op):
    ptrs = ROLES[op]
    fields = [dict(name=name, offset=8 * i, size=8, align=8) for i, name in enumerate(ptrs)]
    fields.append(dict(name="n", offset=8 * len(ptrs), size=4, align=4))
    if op == "affine":
        fields.append(dict(name="alpha", offset=28, size=4, align=4))
    return dict(bytes=24 if op == "copy" else 32, fields=fields)


def verify_inputs(root, op, spec):
    folder = root / "inputs" / op / str(spec["n"])
    n, words = spec["n"], spec["words"]
    format_string = "<{}I".format(words)
    raw = {file: (folder / (file + ".bin")).read_bytes() for file in (*ROLES[op], "expected")}
    require(all(len(data) == 4 * words for data in raw.values()), "wrong frozen input size")
    x = struct.unpack(format_string, raw["x"])
    result = list(struct.unpack(format_string, raw["z"]))
    live = slice(GUARD, GUARD + n)
    if op == "copy":
        result[live] = x[live]
    else:
        y = struct.unpack(format_string, raw["y"])
        alpha = ALPHA if op == "affine" else 1
        result[live] = [(alpha * a + b) & 0xffffffff for a, b in zip(x[live], y[live])]
    require(struct.pack(format_string, *result) == raw["expected"], "frozen oracle, padding or sentinel mismatch")


def verify(bundle):
    plan = read(bundle / "plan.json")
    require(plan["schema"] == SCHEMA and plan["formal_aligned_load"] == "BLOCKED" and
            plan["board_execution"] == "NOT_RUN" and plan["live_vm"] == plan["live_staging"] == "NOT_RUN" and
            plan["cases"] == [geometry(n) for n in COUNTS] and plan["operators"] == list(OPERATORS) and
            plan["routes"] == list(ROUTES) and plan["warm"] == 5 and plan["trials"] == 30 and
            plan["affine_alpha"] == ALPHA and plan["guard_words"] == GUARD, "stage plan differs")
    files = tuple(bundle.rglob("*"))
    require(not any(p.is_symlink() for p in files), "staged bundle contains linked paths")
    seen = {p.relative_to(bundle).as_posix(): sha(p) for p in files if p.is_file() and p.name != "plan.json"}
    require(seen == plan["files"], "bundle member identity differs")
    require(sha(bundle / "target_lock.json") == plan["board_lock_sha256"] and
            sha(bundle / "hardware.json") == read(bundle / "target_lock.json")["hardware_config_sha256"], "board lock/hardware differs")
    audit = read(bundle / "offline-audit.json")
    require(audit["status"] == "PASS" and all(audit[k] == plan[k] for k in
            ("xclbin_sha256", "xclbin_uuid", "runtime_sha256", "board_lock_sha256", "formal_aligned_load")),
            "stage plan differs from the static D10/D12 audit")
    for op in OPERATORS:
        for spec in plan["cases"]:
            verify_inputs(bundle, op, spec)
        for route in ROUTES:
            path = bundle / "candidates" / op / route
            row = read(path / "candidate.json")
            require(row == plan["images"][op][route] and row["layout"] == layout(op) and
                    row["board_lock_sha256"] == plan["board_lock_sha256"] and row["formal_loadable"] is False and
                    sha(path / "kernel.vxbin") == row["image_sha256"] == row["model_image_sha256"], "candidate descriptor differs")
    require(sha(bundle / "probe/kernel.vxbin") == plan["probe_sha256"], "bytewise probe image differs")
    schedule = read(bundle / "pair-schedule.json")
    require(schedule == [dict(operator=op, n=n, pair=i, warmup=i < plan["warm"],
                             order=list(ROUTES if i % 2 == 0 else ROUTES[::-1]))
                        for op in OPERATORS for n in COUNTS for i in range(plan["warm"] + plan["trials"])],
            "pair order differs")
    return dict(status="PASS", members=len(seen), workloads=len(OPERATORS) * len(COUNTS), candidate_images=6,
                planned_pairs=len(schedule), planned_launches=2 * len(schedule), board_execution="NOT_RUN",
                formal_aligned_load="BLOCKED", plan_sha256=sha(bundle / "plan.json"))


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("bundle", type=Path)
    print(json.dumps(verify(cli.parse_args().bundle), indent=2))
