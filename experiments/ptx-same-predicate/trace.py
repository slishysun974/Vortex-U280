"""Verify ordered per-thread array requests from the D6 DEBUG3 LSU logs."""

import argparse
from collections import Counter
import gzip
import os
from pathlib import Path
import re
import sys

from run import (ABI, BACKENDS, PROJECT, ROUTES, Recorder, binding_env, buffers_for, build_receipt, cases,
                 context, images, invoke, payload_bytes, read_json, require, run_stage, sha256, utc_now, write_json)
from analyze import instructions
from native_predicate_trace import parse_request
from ptx_boundary_trace import ACCEPT, DONE, FIRE, SIM_DECODE, SIM_DISPATCH, SIM_DONE
from run_ptx_copy_trace import trace_libraries
from u280_perf_pair import GUARD


TRACE_BINDINGS = PROJECT / "results/ae-v03-trace-20261121-v2/bindings"
UID = re.compile(r" \(#(\d+)\)\s*$")
MASK = re.compile(r"\b(?:tmask|mask)=([01]{4}), addr=")
RTL_WARP = re.compile(r"^\s*(\d+): .*cta_dispatch dispatch: wid=(\d+), cta_id=(\d+), .*tmask=1111,")
RTL_DONE = re.compile(r"^\s*(\d+): .*cta_dispatch warp-done: wid=(\d+), cta_id=(\d+),")
RTL_REQUEST = re.compile(r"execute-lsu\d+ (?:Rd|Wr) Req: wid=(\d+), cta_id=(\d+), PC=0x([0-9a-f]+),")
LANES, WARPS = 4, 8


def data_sites(image, op):
    code = list(instructions(image.with_name("kernel.dump"), image))
    roles = ABI[op][1]
    offsets = {8 * len(roles) + 4 * i for i in range(len(ABI[op][2]))}
    loads, stores, scalar_offsets = [], [], []
    for pc, name, operands in code:
        operand = operands[-1]
        if name in ("lw", "lwu"):
            scalar = re.fullmatch(r"(0x[0-9a-f]+)\(a0\)", operand)
            if scalar and int(scalar[1], 16) in offsets:
                scalar_offsets.append(int(scalar[1], 16))
            elif not operand.endswith("(sp)"):
                loads.append(int(pc, 16))
        elif name == "sw" and not operand.endswith("(sp)"):
            stores.append(int(pc, 16))
    require(sorted(scalar_offsets) == sorted(offsets) and len(loads) == len(roles) - 1 and len(stores) == 1,
            "unexpected scalar parameter or array instructions: " + str(image))
    sites = dict(zip(loads, (("LD", role) for role in roles[:-1])))
    sites[stores[0]] = ("ST", "z")
    return sites, dict(Counter(name for _, name, _ in code))


class Dispatches:
    def __init__(self, backend, spec):
        require(spec["block"] == LANES * WARPS, "trace requires full eight-warp CTAs")
        self.backend = backend
        self.grid = spec["grid"]
        self.warps = {}
        self.issued = Counter()
        self.uid = {}
        self.pending = {}
        self.slots = {}
        self.replacements = {}
        self.completed = set()

    def dispatch(self, wid, slot, block, rank):
        require(wid not in self.warps and 0 <= block < self.grid and 0 <= rank < WARPS,
                "invalid logical warp dispatch")
        self.warps[wid] = slot, block, rank
        self.issued[block, rank] += 1

    def simx(self, line):
        if match := SIM_DISPATCH.match(line):
            wid, slot, rank, size, block = map(int, match.groups())
            require(size == WARPS and " tmask=1111," in line, "unexpected SimX CTA shape")
            self.dispatch(wid, slot, block, rank)
        elif (match := SIM_DECODE.match(line)):
            wid, slot = map(int, match.groups())
            uid, pc = UID.search(line), re.search(r"\bPC=0x([0-9a-f]+),", line)
            require(wid in self.warps and self.warps[wid][0] == slot and uid and pc, "unbound SimX LSU decode")
            self.uid[int(uid[1])] = int(pc[1], 16), self.warps[wid]
        elif match := SIM_DONE.match(line):
            self.warps.pop(int(match[1]))

    def rtlsim(self, line):
        if match := FIRE.match(line):
            cycle, _, block, pc, param = match.groups()
            key = cycle, pc, param
            require(key not in self.pending, "duplicate RTL KMU fire")
            self.pending[key] = int(block)
        elif match := ACCEPT.match(line):
            cycle, slot, pc, param = match.groups()
            slot = int(slot)
            require(slot not in self.slots, "RTL CTA slot reused before retirement")
            self.slots[slot] = (self.pending.pop((cycle, pc, param)), 0)
        elif match := RTL_WARP.search(line):
            cycle, wid, slot = map(int, match.groups())
            block, rank = self.slots[slot]
            if wid in self.warps:
                # RTL logs replacement dispatch before the old warp's done
                # on the same edge. Reserve its new logical rank now.
                require(wid not in self.replacements, "more than one RTL replacement warp")
                self.replacements[wid] = cycle, slot, block, rank
            else:
                self.dispatch(wid, slot, block, rank)
            self.slots[slot] = block, rank + 1
        elif "cta_dispatch warp-done:" in line:
            match = RTL_DONE.match(line)
            require(match, "unparsed RTL warp retirement")
            cycle, wid, slot = map(int, match.groups())
            # Reset cycles can print an unused cta_done=0 handshake before
            # the first real dispatch. A live warp must keep its slot.
            if wid in self.warps:
                require(self.warps.pop(wid)[0] == slot, "RTL warp retired from wrong slot")
                if wid in self.replacements:
                    start, new_slot, block, rank = self.replacements.pop(wid)
                    require(start == cycle and new_slot != slot, "RTL replacement lacks a matching retirement")
                    self.dispatch(wid, new_slot, block, rank)
            if DONE.match(line):
                block, rank = self.slots.pop(slot)
                require(rank == WARPS and block not in self.completed, "invalid RTL CTA retirement")
                self.completed.add(block)

    def request(self, line):
        if self.backend == "simx":
            match = UID.search(line)
            require(match and int(match[1]) in self.uid, "unbound SimX LSU request")
            pc, (_, block, rank) = self.uid[int(match[1])]
        else:
            match = RTL_REQUEST.search(line)
            require(match and int(match[1]) in self.warps, "unbound RTL LSU request")
            slot, block, rank = self.warps[int(match[1])]
            require(int(match[2]) == slot, "RTL LSU instruction has wrong CTA slot")
            pc = int(match[3], 16)
        return pc, block, rank

    def finish(self):
        require(not self.warps and not self.slots and not self.pending and not self.replacements and
                self.issued == {(block, rank): 1 for block in range(self.grid) for rank in range(WARPS)},
                "missing or repeated warp dispatch/retirement")


def analyze_log(lines, backend, op, spec, bases, sites):
    dispatch = Dispatches(backend, spec)
    track = dispatch.simx if backend == "simx" else dispatch.rtlsim
    n = spec["n"]
    slots = spec["grid"] * spec["block"]
    roles = ABI[op][1]
    expected = [("LD", role) for role in roles[:-1]] + [("ST", "z")]
    next_request = [0] * slots
    tail_start = (n - 1) // LANES * LANES
    tail = {i: [] for i in range(tail_start, min(slots, tail_start + LANES))}
    state, request_packets = 0, 0
    for line in lines:
        if line.rstrip() == "LSU_TRACE_BEGIN":
            require(state == 0, "duplicate trace begin")
            state = 1
        elif line.rstrip() == "LSU_TRACE_END":
            require(state == 1, "trace end outside launch")
            state = 2
        elif state == 1:
            if any(token in line for token in ("dispatch", "warp-state:", "ex=LSU", "kmu cta-fire:")):
                track(line)
            if not (" mem-req:" in line if backend == "simx" else (" Rd Req:" in line or " Wr Req:" in line)):
                continue
            active = parse_request(line, backend)
            if active is None:
                continue
            pc, block, rank = dispatch.request(line)
            mask = MASK.search(line)
            require(mask, "missing LSU lane mask")
            logical = mask[1]
            if backend == "rtlsim":
                logical, active = logical[::-1], active[::-1]
            lanes = [lane for lane, flag in enumerate(logical) if flag == "1"]
            require(len(lanes) == len(active) and lanes, "invalid LSU request mask")
            request_packets += 1
            for lane, (direction, address) in zip(lanes, active):
                if pc not in sites and not any(base <= address < base + 4 * spec["words"] for base in bases.values()):
                    continue
                i = block * spec["block"] + rank * LANES + lane
                require(i < n, "false-predicate lane issued array request: index {}, PC {:#x}".format(i, pc))
                step = next_request[i]
                role = expected[step][1] if step < len(expected) else None
                require(role and sites.get(pc) == (direction, role) == expected[step] and
                        address == bases[role] + 4 * (GUARD + i),
                        "wrong array address, site, or per-thread order: index {}, PC {:#x}".format(i, pc))
                next_request[i] += 1
                if i in tail:
                    tail[i].append(dict(pc=hex(pc), operation=direction, buffer=role,
                                        address=hex(address), lane0_first_mask=logical))
    dispatch.finish()
    require(state == 2 and request_packets > 0 and next_request == [len(expected)] * n + [0] * (slots - n),
            "trace lacks the expected unique, ordered requests")
    return dict(status="PASS", active_threads=n, false_threads=slots-n, false_predicate_array_requests=0,
                active_array_requests=sum(next_request), lsu_packets=request_packets, last_warp=tail,
                active_loads=n * (len(roles) - 1), active_stores=n, dispatched_warps=len(dispatch.issued))


def trace_worker(out, backend, built, op, n, route):
    spec, frozen = next((spec, frozen) for name, spec, frozen in cases() if name == op and spec["n"] == n)
    paths = images(built, op, build_receipt(built)[op])
    ctx = context(TRACE_BINDINGS / backend / "binding.json", backend, out)
    try:
        inputs, expected, handles, bases = buffers_for(ctx, frozen, op, spec)
        payload = payload_bytes(op, bases, n)
        (out / "params.bin").write_bytes(payload)
        write_json(out / "bases.json", bases)
        invoke(ctx, paths[route], spec, payload, inputs, handles, out, trace=True)
        require((out / "z.bin").read_bytes() == expected, "full traced output differs")
    finally:
        if ctx.state == "READY":
            ctx.close()


def run_traces(out, rec, backend, built):
    libraries, hashes = trace_libraries(backend)
    binding = TRACE_BINDINGS / backend / "binding.json"
    require(Path(read_json(binding)["library_dir"]) == libraries, "mismatched D6 debug binding")
    binding_env(rec, binding)
    rec.summary.update(binding_sha256=sha256(binding), debug_libraries=hashes, cases=[])
    report = build_receipt(built)
    for op, spec, _ in sorted(cases(), key=lambda item: item[1]["n"]):
        n = spec["n"]
        paths = images(built, op, report[op])
        for route in ROUTES:
            directory = out / op / str(n) / route
            directory.mkdir(parents=True)
            log = directory / "lsu.log.gz"
            sites, static = data_sites(paths[route], op)
            command = ["bash", "-o", "pipefail", "-c", '"$@" 2>&1 | gzip -1 > "$0"', log,
                       sys.executable, "-B", Path(__file__).resolve(), "worker", "--output", directory,
                       "--backend", backend, "--build", built, "--operator", op, "--n", str(n), "--route", route]
            run_stage(rec, f"{op}_{n}_{route}", command, directory, 420)
            bases = read_json(directory / "bases.json")
            with gzip.open(log, "rt", encoding="utf-8") as raw:
                evidence = analyze_log(raw, backend, op, spec, bases, sites)
            evidence.update(operator=op, n=n, route=route, image_sha256=sha256(paths[route]),
                            raw_trace_sha256=sha256(log), sites=sites, static_opcodes=static,
                            params_sha256=sha256(directory / "params.bin"), output_sha256=sha256(directory / "z.bin"))
            write_json(directory / "trace.json", evidence)
            rec.summary["cases"].append(evidence)
            rec.save()
            print(op, n, route, evidence["active_array_requests"], evidence["false_predicate_array_requests"], flush=True)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("action", choices=("trace", "worker"))
    cli.add_argument("--output", type=Path, required=True)
    cli.add_argument("--build", type=Path, required=True)
    cli.add_argument("--backend", choices=BACKENDS, required=True)
    cli.add_argument("--operator", choices=ABI)
    cli.add_argument("--n", type=int)
    cli.add_argument("--route", choices=ROUTES)
    args = cli.parse_args()
    out, built = args.output.resolve(), args.build.resolve()
    if args.action == "worker":
        trace_worker(out, args.backend, built, args.operator, args.n, args.route)
        return 0
    require(out.parent == PROJECT / "results" and out.name.startswith("local-ptx-same-predicate-"),
            "choose a new local results directory")
    out.mkdir()
    report = dict(status="RUNNING", board_execution="NOT_RUN", afu_execution="NOT_RUN", commands=[],
                  started_at=utc_now(), backend=args.backend, build_sha256=sha256(built / "summary.json"),
                  argv=[sys.executable, "-B", *sys.argv], script_sha256=sha256(__file__))
    env = {key: value for key, value in os.environ.items()
           if key not in ("XCLBIN_PATH", "XCL_EMULATION_MODE", "VORTEX_CP_POLL_TIMEOUT_S")}
    rec = Recorder(out, report, env)
    try:
        run_traces(out, rec, args.backend, built)
        report.update(status="PASS", exit_code=0)
    except Exception as error:
        report.update(status="FAIL", exit_code=1, error=str(error))
    report["finished_at"] = utc_now()
    rec.save()
    print(report["status"], out, report.get("error", ""))
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
