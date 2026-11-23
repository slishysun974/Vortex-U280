"""Compare individual active LSU lanes with the E source semantics on small frozen cases."""
from collections import defaultdict
import argparse
import ctypes
import os
from pathlib import Path
import re
import struct
import sys

from accept import FROZEN, MODELS, PROJECT, SIM_LOCK, Recorder, corpus, read_json, require, run_stage, sha256, utc_now, write_json
sys.path.insert(0, str(PROJECT / "experiments/ptx-same-predicate"))
from run import context, invoke
from native_predicate_trace import parse_request
from ptx_boundary_trace import bind_simx, bind_slots
from ptx_module import validate
from ptx_runtime import Q
from run_ptx_copy_trace import RTL_CONTEXT, SIMX_DECODE

BIND = PROJECT / "results/ae-v03-trace-20261121-v2/bindings"
AFU = PROJECT / "results/local-ptx-same-predicate-afu-trace-build-20261121-v1/binding/binding.json"
BINDINGS = {"simx": (BIND / "simx/binding.json", "422887f3317f77a7a875dfe35cbd75503a2824f8b0993a3c77d9ef3bde487b5f"),
            "rtlsim": (BIND / "rtlsim/binding.json", "9f770fe994c180fad9b30e781510d82e6da7e64a3ee8516e48aba73bad53520f"),
            "xrtsim": (AFU, "6597e09679fa638b960e1a2895fb7b85360a7bb1a130bf900cf31a2bbc5a5c47")}


def capture(folder, accepted, built, spec, backend):
    path = (accepted if spec["op"] == "predicate_turn" else built / "modules") / spec["op"]
    manifest, image = validate(path, SIM_LOCK.read_bytes())
    require(manifest["image_sha256"] == read_json(accepted / backend / "receipt.json")["images"][spec["op"]]
            and image == (path / "kernel.vxbin").read_bytes(), "functional and trace image differ")
    bind, digest = BINDINGS[backend]
    require(sha256(bind) == digest, "debug binding differs")
    ctx = context(bind, backend, folder)
    roles = spec["roles"]
    try:
        inputs = {r: (FROZEN / spec["id"] / (r + ".bin")).read_bytes() for r in roles}
        handles = {r: ctx.alloc(len(raw)) for r, raw in inputs.items()}
        bases, pointers = {}, []
        for r in roles:
            q = Q()
            ctx.check(ctx.lib.vx_buffer_address(ctx.buffers[handles[r]][0], ctypes.byref(q)), "array_base")
            bases[r] = q.value
            pointers.append(q.value + 4 * spec["offsets"][r])
        scalars = [spec["n"]]
        if spec["op"] in ("predicate_turn", "affine"):
            scalars.append(spec["selected"] if spec["op"] == "predicate_turn" else spec["alpha"])
        payload = struct.pack("<" + "Q" * len(roles) + "I" * len(scalars), *pointers, *scalars)
        payload += bytes(-len(payload) % 8)
        write_json(folder / "bases.json", bases)
        (folder / "params.bin").write_bytes(payload)
        invoke(ctx, path / "kernel.vxbin", spec, payload, inputs, handles, folder, trace=True)
        require((folder / "z.bin").read_bytes() == (FROZEN / spec["id"] / "expected-z.bin").read_bytes(),
                "debug output differs")
    finally:
        if ctx.state == "READY":
            ctx.close()


def compare(raw, backend, spec, folder):
    mode = "simx" if backend == "simx" else "rtlsim"
    require(raw.count("LSU_TRACE_BEGIN") == raw.count("LSU_TRACE_END") == 1, "incomplete native capture")
    frame = raw.split("LSU_TRACE_BEGIN", 1)[1].split("LSU_TRACE_END", 1)[0]
    view, binds = bind_simx(frame, spec) if mode == "simx" else bind_slots(frame, spec["grid"])
    bases = read_json(folder / "bases.json")
    ends = {r: b + (folder / (r + ".bin")).stat().st_size for r, b in bases.items()}
    lookup, seen = {}, defaultdict(list)
    require(spec["block"] <= 4, "decoder requires one warp per CTA")
    for line in view.splitlines():
        if mode == "simx" and (m := SIMX_DECODE.search(line)):
            lookup[m[3]] = int(m[1])
        active = parse_request(line, mode)
        if active is None:
            continue
        mask = re.search(r"\b(?:tmask|mask)=([01]{4}), addr=", line)[1]
        lanes = [i if mode == "simx" else 3-i for i, bit in enumerate(mask) if bit == "1"]
        require(len(lanes) == len(active), "mask/address length differs")
        block = lookup[re.search(r" \(#(\d+)\)$", line)[1]] if mode == "simx" else int(RTL_CONTEXT.search(line)[1])
        for lane, (op, address) in zip(lanes, active):
            for role, base in bases.items():
                if base <= address < ends[role]:
                    seen[block, lane].append((op, role, address))
    expected = {}
    for i in range(spec["block"] * spec["grid"]):
        cta, lane = divmod(i, spec["block"])
        ops = []
        if spec["op"] == "predicate_turn":
            ops = [("LD", "x" if i < spec["n"] else "y"), ("ST", "z")]
            if lane == spec["selected"]:
                ops.extend([("LD", "z"), ("ST", "z")])
        elif i < spec["n"]:
            ops = [("ST" if r == "z" else "LD", r) for r in spec["roles"]]
        if ops:
            expected[cta, lane] = [(op, r, bases[r] + 4 * (i + spec["offsets"][r])) for op, r in ops]
    write_json(folder / "requests.json", [dict(cta=k[0], lane=k[1], expected=expected.get(k, []),
               observed=seen.get(k, [])) for k in sorted(set(expected) | set(seen))])
    require(seen == expected, "array access order, lane or address differs")
    return dict(requests=sum(map(len, seen.values())), cta_bindings=binds, full_array_scope=list(bases),
                silent_threads=spec["block"] * spec["grid"] - len(seen))


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    for name in ("output", "accepted", "built"):
        cli.add_argument(name, type=Path)
    cli.add_argument("--worker", choices=MODELS)
    cli.add_argument("--case")
    a = cli.parse_args()
    out, accepted, built = [p.resolve() for p in (a.output, a.accepted, a.built)]
    selected = [s for s in corpus() if s["id"].endswith("-1") or s["id"] == "copy-0"]
    if a.worker:
        capture(out, accepted, built, next(s for s in selected if s["id"] == a.case), a.worker)
        return 0
    out.mkdir()
    report = dict(status="RUNNING", argv=sys.argv, commands=[], models={}, started_at=utc_now(),
                  scope="pre-cache LSU requests into complete frozen array allocations", u280="NOT_RUN")
    rec = Recorder(out, report, dict(os.environ))
    try:
        for backend in MODELS:
            binding, digest = BINDINGS[backend]
            info = read_json(binding)
            rec.env.update(VORTEX_DRIVER=info["driver"], LD_LIBRARY_PATH=info["library_dir"],
                           VORTEX_PROFILING="0", XRT_DEVICE_INDEX="0")
            report["models"][backend] = dict(binding_sha256=digest, cases={})
            for spec in selected:
                folder = out / backend / spec["id"]
                folder.mkdir(parents=True)
                raw = run_stage(rec, backend + "-" + spec["id"], [sys.executable, "-B", __file__, folder, accepted,
                                built, "--worker", backend, "--case", spec["id"]], folder, 120)
                report["models"][backend]["cases"][spec["id"]] = compare(raw, backend, spec, folder)
                rec.save()
        report.update(status="PASS", exit_code=0)
    except Exception as exc:
        report.update(status="FAIL", error=str(exc), exit_code=1)
    report["finished_at"] = utc_now()
    rec.save()
    print(report["status"], report.get("error", ""))
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
