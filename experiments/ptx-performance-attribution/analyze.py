"""Bind archived disassembly to executed bytes and review the two counter captures."""

import argparse
from collections import Counter
import json
from pathlib import Path
import re
from statistics import median
import struct
import sys

from measure import ARCHIVES, COUNTERS, PROJECT
from ptx_module import inspect_vxbin
from run_native_smoke import sha256
from run_ptx_copy import read_json, require, write_json
from u280_perf_pair import ABI, ROUTES, operator_path, workloads


def instructions(dump, image):
    text = dump.read_text(encoding="utf-8").split("<kernel_main>:\n", 1)[1].split("\n\n", 1)[0]
    raw = image.read_bytes()
    base = inspect_vxbin(raw)["min_vma"]
    for line in text.splitlines():
        match = re.fullmatch(r"\s*([0-9a-f]+): ([0-9a-f]{8})\s+(\w+)\s*(.*?)\s*", line)
        require(match is not None, "unrecognized kernel instruction: " + line)
        pc, word, opcode, operands = match.groups()
        offset = 16 + int(pc, 16) - base
        require(struct.unpack_from("<I", raw, offset)[0] == int(word, 16), "image bytes differ at " + pc)
        yield pc, opcode, operands.split(", ")


def classify(op, route, code):
    """Track products of byte loads through shifts and OR in these straight-line regions."""
    packed, annotated = set(), []
    field_offsets = {8 * i for i in range(len(ABI[op][1]))}
    field_offsets.update(8 * len(ABI[op][1]) + 4 * i for i in range(len(ABI[op][2])))
    for pc, opcode, operands in code:
        dest = operands[0]
        category = "other"
        if opcode in ("vx_split_n", "beqz", "vx_join"):
            category = "predicate_control"
        elif opcode == "lbu":
            require(route == "ptx" and re.fullmatch(r"0x[0-9a-f]+\(a0\)", operands[-1]),
                    "unexpected byte-load source at " + pc)
            category = "parameter_load"
        elif opcode in ("slli", "slliw", "or"):
            sources = operands[1:2] if opcode != "or" else operands[1:]
            if all(reg in packed for reg in sources):
                category = "parameter_unpack"
        elif opcode in ("ld", "lw") and route == "native":
            match = re.fullmatch(r"(0x[0-9a-f]+)\(a0\)", operands[-1])
            if match and int(match.group(1), 16) in field_offsets:
                category = "parameter_load"
        elif opcode == "sd" and operands[-1].endswith("(sp)"):
            category = "stack_store"
        if opcode not in ("beqz", "vx_join", "sw", "sd", "ret"):
            packed.discard(dest)
            if category == "parameter_unpack" or (opcode == "lbu" and category == "parameter_load"):
                packed.add(dest)
        annotated.append(dict(pc=pc, opcode=opcode, operands=operands, category=category))
    counts = Counter(item["category"] for item in annotated)
    return dict(total=len(annotated), category_counts=dict(counts), instructions=annotated)


def collect_static():
    static, cases = {}, {}
    for suffix in ARCHIVES:
        bundle = PROJECT / "results" / ("u280-perf-kit-" + suffix) / "bundle"
        build = PROJECT / "results" / ("u280-perf-build-" + suffix)
        plan = read_json(bundle / "plan.json")
        for op, spec, subdir in workloads(plan):
            cases[op, spec["n"]] = (spec, bundle / "inputs" / subdir, plan, subdir)
        for op in {op for op, _, _ in workloads(plan)}:
            static[op] = {}
            for route in ROUTES:
                images = []
                for target in ("sim", "board"):
                    root = operator_path(plan, build / target, op) / route
                    image = root / "kernel.vxbin"
                    dump = root / ("program.disasm" if route == "ptx" else "kernel.dump")
                    images.append((image, dump, list(instructions(dump, image))))
                sim, board = images
                require(sim[2] == board[2] and sha256(sim[0]) == sha256(board[0]), "board/model code or image differs")
                static[op][route] = dict(classify(op, route, sim[2]), image_sha256=sha256(sim[0]),
                                         dumps={str(d.relative_to(PROJECT)): sha256(d) for _, d, _ in images})
    return static, cases


def review_capture(run, backend, cases, static):
    report = read_json(run / "summary.json")
    require(report["status"] == "PASS" and report["exit_code"] == 0 and report["backend"] == backend
            and report["board_execution"] == "NOT_RUN", "backend did not pass")
    command, = report["commands"]
    require(command["returncode"] == 0 and sha256(run / command["log"]) == command["log_sha256"], "command or log differs")
    out = run / backend
    log = out / "samples.jsonl"
    capture = read_json(out / "capture.json")
    rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    by_key = {(r["operator"], r["n"], r["route"], r["repeat"]): r for r in rows}
    keys = {(op, n, route, rep) for op, n in cases for rep in range(report["repeats"]) for route in ROUTES}
    require(by_key.keys() == keys and len(by_key) == len(rows) == capture["samples"], "missing or duplicate sample")
    for (op, n, route, rep), row in by_key.items():
        spec, frozen, plan, subdir = cases[op, n]
        case = out / op / str(n)
        expected = frozen / "expected.bin"
        output = case / ("{}-{}.bin".format(route, rep))
        require(row["grid"] == spec["grid"] and row["block"] == spec["block"] and
                row["position"] == (ROUTES if rep % 2 == 0 else ROUTES[::-1]).index(route), "geometry or order differs")
        for role, digest in {**row["inputs"], "expected": row["expected_sha256"]}.items():
            key = (Path("inputs") / subdir / (role + ".bin")).as_posix()
            require(digest == sha256(frozen / (role + ".bin")) == plan["files"][key],
                    "frozen input or answer differs")
        require(row["inputs"].keys() == set(ABI[op][1]) and row["params_sha256"] == sha256(case / "params.bin") and
                row["image_sha256"] == static[op][route]["image_sha256"], "sample input or image identity differs")
        require(output.read_bytes() == expected.read_bytes() and row["output_sha256"] == sha256(expected), "output differs")
        require(row["idle"] == row["before"] and row["delta"] ==
                {k: row["after"][k] - row["before"][k] for k in COUNTERS}, "counter snapshot differs")
    return by_key, dict(samples=len(rows), report_sha256=sha256(run / "summary.json"), raw_samples_sha256=sha256(log))


def review(static, cases, paths):
    receipts, metrics = {}, {}
    for backend, run in paths.items():
        rows, receipts[backend] = review_capture(run, backend, cases, static)
        metrics[backend] = {}
        for op, n in cases:
            routes = {}
            for route in ROUTES:
                selected = [r["delta"] for (operator, size, name, _), r in rows.items() if (operator, size, name) == (op, n, route)]
                routes[route] = {key: median(r[key] for r in selected) for key in COUNTERS}
                require(len({r["instret"] for r in selected}) == 1, "retired instructions changed across repeats")
                routes[route]["cycles_range"] = [min(r["cycles"] for r in selected), max(r["cycles"] for r in selected)]
            native, ptx = (routes[name] for name in ROUTES)
            for route in ROUTES:
                routes[route]["cpi"] = routes[route]["cycles"] / routes[route]["instret"]
            key = "{}/{}".format(op, n)
            metrics[backend][key] = dict(routes, cycles_ratio=ptx["cycles"] / native["cycles"],
                                         instret_ratio=ptx["instret"] / native["instret"],
                                         cpi_ratio=ptx["cpi"] / native["cpi"],
                                         cycles_delta=ptx["cycles"] - native["cycles"],
                                         instret_delta=ptx["instret"] - native["instret"])
    attribution = {}
    for (op, n), (spec, _, _, _) in cases.items():
        key = "{}/{}".format(op, n)
        sim, rtl = metrics["simx"][key], metrics["rtlsim"][key]
        require(all(sim[route]["instret"] == rtl[route]["instret"] for route in ROUTES), "backend retirement counts differ")
        all_active_warps = spec["grid"] * spec["block"] // 4
        native, ptx = (static[op][name] for name in ROUTES)
        static_delta = (ptx["total"] - native["total"]) * all_active_warps
        require(n % 4 or static_delta == sim["instret_delta"], "full-warp projection differs from retirement")
        categories = Counter(ptx["category_counts"])
        categories.subtract(native["category_counts"])
        attribution[key] = dict(full_warp_projection=static_delta, observed_instret_delta=sim["instret_delta"],
                                residual=sim["instret_delta"] - static_delta,
                                full_warp_category_projection={name: count * all_active_warps
                                                               for name, count in categories.items() if count})
    return dict(metrics=metrics, attribution=attribution, capture_receipts=receipts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("simx", "rtlsim", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    static, cases = collect_static()
    result = review(static, cases, dict(simx=args.simx, rtlsim=args.rtlsim))
    result.update(status="PASS", exit_code=0, scope="archived native/PTX pairs on local SimX and processor RTL", board_execution="NOT_RUN",
                  static=static, argv=[sys.executable, "-B", *sys.argv],
                  capture_paths={"simx": str(args.simx), "rtlsim": str(args.rtlsim)},
                  script_sha256={name: sha256(Path(__file__).with_name(name)) for name in ("measure.py", "analyze.py")})
    write_json(args.output, result)
    for op, n in cases:
        name = "{}/{}".format(op, n)
        print(name, result["attribution"][name])
        for backend in result["metrics"]:
            row = result["metrics"][backend][name]
            print(backend, [(r, row[r]["cycles"], row[r]["instret"]) for r in ROUTES],
                  "CPI multiplier", round(row["cpi_ratio"], 4))


if __name__ == "__main__":
    main()
