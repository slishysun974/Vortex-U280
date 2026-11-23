"""Execute the reviewed D probe with live Vortex2 buffers on both sides of 4 GiB."""
import argparse
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import sys
import tempfile

from ptx_launch import BufferRegistry, BufferSlice
from native_predicate_trace import parse_request
from ptx_module import inspect_vxbin, validate
from ptx_runtime import LaunchInfo, P, Q, QueueInfo, U, api
from run_d_guarded_wide import (AUDIT, BACKENDS, BASE_BIAS, GUARD, IMAGE_SHA, LOAD,
                                SEED, SOURCE, STORE, U32, check_trace, libraries)
from run_native_smoke import PROJECT, Recorder, sha256, utc_now
from run_ptx_copy import SIM_LOCK, VORTEX, read_json, require, write_json

FOUR_GIB = 1 << 32
LOW = 0x01600000
HIGH = LOW + FOUR_GIB
CROSS = FOUR_GIB - 64
OTHER = FOUR_GIB + 0x02400000
ROLES = ("x", "z", "audit")
WORDS = 64
SIZE = WORDS * 4
ORIGIN = PROJECT / "results/d-guarded-wide-20261120-v1/module"
# B, G, N, skipped tid, extra word, native reservation bases in PTX argument order.
SPECS = {
    "cross_read":     (3, 5, 14, 7, 0, (CROSS, HIGH, LOW)),
    "cross_write":    (4, 4, 15, 0, 1, (HIGH, CROSS, LOW)),
    "cross_audit":    (3, 4,  0, 7, 0, (LOW, HIGH, CROSS)),
    "high_to_low":    (4, 3, 11, 3, 1, (HIGH, LOW, OTHER)),
    "low_to_high":    (4, 3,  9, 2, 0, (LOW, HIGH, OTHER)),
}
# Logical lanes 1 and 2 straddle the boundary at these reviewed data sites.
CROSSINGS = {"cross_read": (LOAD, "LD", 2), "cross_write": (STORE, "ST", 1),
             "cross_audit": (AUDIT, "ST", 2)}


def vectors(cid):
    block, grid, n, skip, extra, bases = SPECS[cid]
    case = dict(id=cid, block=block, grid=grid, n=n, skip_lane=skip, bias=BASE_BIAS + extra,
                words=WORDS, bases=dict(zip(ROLES, bases)))
    arrays = {}
    for role in ROLES:
        data = [hashlib.sha256(f"d-high-address-v1/{cid}/{role}/{j}".encode()).digest()[:4]
                for j in range(WORDS)]
        arrays[role] = list(struct.unpack("<64I", b"".join(data)))
    arrays["x"][GUARD:GUARD+5] = [0xffffffff, 0x80000000, 0, 0x7fffffff, 0xfffffffe]
    expected = {role: words.copy() for role, words in arrays.items()}
    for i in range(block * grid):
        value = SEED
        if i < n and i % block != skip:
            value = arrays["x"][GUARD + i + extra]
            expected["z"][GUARD + i + extra + 1] = (value + (value >> 31)) & U32
        expected["audit"][GUARD + i] = (value + grid) & U32
    pack = struct.Struct("<64I").pack
    return case, {role: pack(*words) for role, words in arrays.items()}, {
        role: pack(*words) for role, words in expected.items()}


def native_check(status, operation):
    require(status == 0, f"{operation} returned Vortex2 status {status}")


def capture(module, root, backend):
    """One model process owns the queue, native reservations and host transfer storage."""
    case, _, _ = vectors(root.name)
    require(read_json(root / "case.json") == case, "unexpected test parameters")
    manifest, image = validate(module, SIM_LOCK.read_bytes())
    require(manifest["image_sha256"] == IMAGE_SHA, "unreviewed image")
    libdir, _ = libraries()[backend]
    driver = "xrt" if backend == "xrtsim" else backend
    require(os.environ.get("VORTEX_DRIVER") == driver and
            os.environ.get("LD_LIBRARY_PATH") == str(libdir), "wrong model binding")
    lib = api(C.CDLL(str(libdir / "libvortex.so")))
    lib.vx_buffer_reserve.argtypes = [P, Q, Q, U, C.POINTER(P)]
    lib.vx_buffer_reserve.restype = C.c_int
    dev, queue, mod, kernel, event = (P() for _ in range(5))
    out = root / backend
    out.mkdir()
    native_check(lib.vx_device_open(0, C.byref(dev)), "open")
    maps = Path("/proc/self/maps").read_text()
    require(str(libdir / ("libvortex-" + driver + ".so")) in maps and
            str(libdir / ("lib" + backend + ".so")) in maps, "loaded model differs")
    caps = {}
    for name, key in (("threads", 1), ("warps", 2), ("cores", 3), ("global_bytes", 5), ("vm", 15)):
        value = Q()
        native_check(lib.vx_device_query(dev, key, C.byref(value)), "query " + name)
        caps[name] = value.value
    require((caps["threads"], caps["warps"], caps["cores"], caps["vm"]) == (4, 8, 1, 0),
            "requires fixed 1c/8w/4t model without VM")
    info = QueueInfo(C.sizeof(QueueInfo), None, 1, 0)
    native_check(lib.vx_queue_create(dev, C.byref(info), C.byref(queue)), "queue")
    native_check(lib.vx_module_load_bytes(dev, image, len(image), C.byref(mod)), "load")
    native_check(lib.vx_module_get_kernel(mod, manifest["native_entry"].encode(), C.byref(kernel)), "entry")
    registry = BufferRegistry()
    buffers, pointers, slices = {}, {}, []
    for role in ROLES:
        base = case["bases"][role]
        require(base + SIZE <= caps["global_bytes"], "reservation exceeds model capacity")
        buf, addr = P(), Q()
        native_check(lib.vx_buffer_reserve(dev, base, SIZE, 3, C.byref(buf)), "reserve " + role)
        native_check(lib.vx_buffer_address(buf, C.byref(addr)), "address " + role)
        require(addr.value == base, "reserved address mismatch: " + role)
        buffers[role] = buf
        pointers[role] = addr.value + 4 * GUARD
        handle = registry.register_native(addr.value, SIZE)
        slices.append(BufferSlice(handle, 4 * GUARD, SIZE - 4 * GUARD, "r" if role == "x" else "w"))
    write_json(out / "reservations.json", dict(caps=caps, bases=case["bases"], pointers=pointers, bytes_per_buffer=SIZE))

    def read_buffers(phase):
        for role, buf in buffers.items():
            host = C.create_string_buffer(SIZE)
            native_check(lib.vx_enqueue_read(queue, host, buf, 0, SIZE, 0, None, None), "read " + role)
            native_check(lib.vx_queue_finish(queue, 30_000_000_000), "finish read " + role)
            (out / (role + "." + phase + ".bin")).write_bytes(host.raw)

    for role, buf in buffers.items():
        raw = (root / (role + ".input.bin")).read_bytes()
        require(len(raw) == SIZE, "invalid input length")
        native_check(lib.vx_enqueue_write(queue, buf, 0, raw, SIZE, 0, None, None), "write " + role)
        native_check(lib.vx_queue_finish(queue, 30_000_000_000), "finish write " + role)
    read_buffers("before")
    require(all((out / (r + ".before.bin")).read_bytes() == (root / (r + ".input.bin")).read_bytes()
                for r in ROLES), "pre-launch H2D/D2H mismatch")
    plan = registry.prepare(manifest, manifest["entry"], (case["grid"], 1, 1), (case["block"], 1, 1),
                            slices + [case["n"], case["skip_lane"], case["bias"]])
    payload = C.create_string_buffer(plan.payload)
    launch = LaunchInfo()
    launch.struct_size, launch.kernel, launch.ndim = C.sizeof(launch), kernel, 1
    launch.args_host, launch.args_size = C.cast(payload, P), len(plan.payload)
    launch.grid_dim, launch.block_dim = (U * 3)(*plan.grid), (U * 3)(*plan.block)
    (out / "params.bin").write_bytes(C.string_at(launch.args_host, launch.args_size))
    registry.pin(plan)
    native_check(lib.vx_enqueue_launch(queue, C.byref(launch), 0, None, C.byref(event)), "launch")
    native_check(lib.vx_event_wait_value(event, 1, 30_000_000_000), "wait")
    native_check(lib.vx_event_release(event), "release event")
    registry.complete(plan)
    read_buffers("after")
    for buf in buffers.values():
        native_check(lib.vx_buffer_release(buf), "release buffer")
    for release, handle in ((lib.vx_kernel_release, kernel), (lib.vx_module_release, mod),
                            (lib.vx_queue_release, queue), (lib.vx_device_release, dev)):
        native_check(release(handle), release.__name__)
    print("HIGH_ADDRESS_COMPLETE", backend, root.name, flush=True)


def check(root, backend, raw):
    case, inputs, expected = vectors(root.name)
    require(read_json(root / "case.json") == case, "archived case differs from probe specification")
    stage = root / backend
    allocation = read_json(stage / "reservations.json")
    pointers = {role: case["bases"][role] + 4 * GUARD for role in ROLES}
    require(allocation["caps"] == dict(threads=4, warps=8, cores=1, global_bytes=2 * FOUR_GIB, vm=0),
            "unexpected model capabilities")
    require(all(allocation[k] == v for k, v in (("bases", case["bases"]), ("pointers", pointers),
                                                ("bytes_per_buffer", SIZE))), "wrong live reservations")
    require(raw.splitlines().count("HIGH_ADDRESS_COMPLETE " + backend + " " + root.name) == 1,
            "missing native completion")
    payload = struct.pack("<QQQIII4x", *(pointers[r] for r in ROLES), case["n"], case["skip_lane"], case["bias"])
    require((stage / "params.bin").read_bytes() == payload, "ABI address, scalar or padding mismatch")
    for role in ROLES:
        require((root / (role + ".input.bin")).read_bytes() == inputs[role] ==
                (stage / (role + ".before.bin")).read_bytes(), "pre-launch data mismatch: " + role)
        require((root / (role + ".expected.bin")).read_bytes() == expected[role] ==
                (stage / (role + ".after.bin")).read_bytes(), "post-launch data mismatch: " + role)
    row = dict(status="PASS", full_buffers_before=3, full_buffers_after=3, argument_bytes=len(payload))
    trace = None
    if backend != "xrtsim":
        trace = check_trace(raw, backend, case, pointers)
        require(trace["status"] == "PASS", "logical lane/PC/address/order mismatch")
        row["high_accesses"] = {role: sum(pc == site and address >= FOUR_GIB for lane in trace["lanes"]
                                          for pc, _, address in lane["observed"])
                                for role, site in (("x", LOAD), ("z", STORE), ("audit", AUDIT))}
        row["accesses"] = trace["counts"]
    return row, trace


def stage_inputs(run):
    for cid in SPECS:
        case, inputs, expected = vectors(cid)
        root = run / cid
        root.mkdir()
        write_json(root / "case.json", case)
        for role in ROLES:
            (root / (role + ".input.bin")).write_bytes(inputs[role])
            (root / (role + ".expected.bin")).write_bytes(expected[role])
    return {p.relative_to(run).as_posix(): sha256(p) for cid in SPECS for p in sorted((run / cid).iterdir())}


def execute(run, recorder, origin):
    report = recorder.summary
    manifest, _ = validate(origin, SIM_LOCK.read_bytes())
    require(manifest["image_sha256"] == IMAGE_SHA and manifest["source_sha256"] == sha256(SOURCE),
            "requires the reviewed D wide-address program")
    module = run / "module"
    module.mkdir()
    for name in ["manifest.json", *manifest["files"]]:
        shutil.copyfile(origin / name, module / name)
    _, image = validate(module, SIM_LOCK.read_bytes())
    report.update(module_origin=str(origin), module_manifest_sha256=sha256(module / "manifest.json"),
                  image_sha256=IMAGE_SHA, native_entry_pc=inspect_vxbin(image)["entry_pc"],
                  target_lock_sha256=sha256(SIM_LOCK), source_sha256=sha256(SOURCE))
    for name in ("scripts/run_d_high_addresses.py", "scripts/run_d_guarded_wide.py", "scripts/ptx_launch.py",
                 "scripts/ptx_frontend_v12.py", "scripts/ptx_runtime.py", "scripts/ptx_module.py",
                 "scripts/ptx_boundary_trace.py", "scripts/run_ptx_copy_trace.py", "scripts/native_predicate_trace.py"):
        dest = run / "implementation" / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(PROJECT / name, dest)
    corpus = stage_inputs(run)
    write_json(run / "corpus.json", corpus)
    report["corpus_sha256"] = sha256(run / "corpus.json")
    for backend, (libdir, hashes) in libraries().items():
        result = report["backends"][backend]
        result.update(status="RUNNING", libraries=hashes)
        for cid in SPECS:
            root = run / cid
            cmd = ["env", "-u", "XCLBIN_PATH", "-u", "XCL_EMULATION_MODE", "VORTEX_PROFILING=0",
                   "VORTEX_DRIVER=" + ("xrt" if backend == "xrtsim" else backend),
                   "LD_LIBRARY_PATH=" + str(libdir), sys.executable, "-B", Path(__file__).resolve(),
                   "capture", "--module", module, "--case-dir", root, "--backend", backend]
            command, raw = recorder.command(backend + "_" + cid, cmd, root, timeout=150)
            try:
                require(command["returncode"] == 0 and not command["timed_out"], "capture failed: " + command["log"])
                row, trace = check(root, backend, raw)
                if trace is not None:
                    write_json(root / backend / "trace.json", trace)
                result["cases"][cid] = row
            except (OSError, ValueError, RuntimeError) as exc:
                result["cases"][cid] = dict(status="FAIL", error=str(exc))
                result["status"] = "FAIL"
                break
            recorder.save()
        else:
            result["status"] = "PASS"
        recorder.save()
        print(backend, result["status"], flush=True)
    require(all(sha256(run / name) == digest for name, digest in corpus.items()), "staged corpus changed")
    require(all(r["status"] == "PASS" for r in report["backends"].values()), "see per-model evidence")


def check_crossing(raw, backend, case, pointers, trace):
    pc, op, block = CROSSINGS[case["id"]]
    lanes = {(lane["block"], lane["lane"]): lane for lane in trace["lanes"]}
    for lane, address in ((1, FOUR_GIB - 4), (2, FOUR_GIB)):
        require((pc, op, address) in lanes[block, lane]["observed"], "missing adjacent boundary access")

    # Change one active address in the in-memory copy of the raw model output.
    # The count, lane mask, operation and lane order all stay identical.
    lines = raw.splitlines(keepends=True)
    changes = []
    for i, line in enumerate(lines):
        accesses = parse_request(line, backend)
        if accesses and (op, FOUR_GIB - 4) in accesses and (op, FOUR_GIB) in accesses:
            field = re.search(r"addr=\{([^}]+)\}", line)
            replacement, count = re.subn(r"\b0x0*100000000\b", "0x0", field[1])
            require(count == 1, "ambiguous boundary address in trace")
            lines[i] = line[:field.start(1)] + replacement + line[field.end(1):]
            changes.append(dict(line=i+1, original=line.strip(), altered=lines[i].strip()))
    require(len(changes) == 1, "expected one request containing both boundary words")
    damaged = check_trace("".join(lines), backend, case, pointers)
    mismatches = [r for r in damaged["lanes"] if r["observed"] != r["expected"]]
    require(damaged["status"] == "FAIL" and damaged["counts"] == trace["counts"] and
            len(mismatches) == 1 and (mismatches[0]["block"], mismatches[0]["lane"]) == (block, 2)
            and (pc, op, 0) in mismatches[0]["observed"], "bit-32 loss control failed")
    return dict(pc=hex(pc), block=block, lanes=[1, 2], addresses=["0xfffffffc", "0x100000000"],
                bit32_loss="DETECTED", changed_request=changes[0])


def review(run):
    report = read_json(run / "summary.json")
    require(report["status"] == "PASS" and report["exit_code"] == 0, "incomplete execution")
    manifest, _ = validate(run / "module", SIM_LOCK.read_bytes())
    require(manifest["image_sha256"] == IMAGE_SHA and sha256(run / "module/manifest.json") ==
            report["module_manifest_sha256"], "module identity differs")
    require(sha256(SOURCE) == manifest["source_sha256"] and sha256(SIM_LOCK) == report["target_lock_sha256"],
            "PTX source or target lock differs")
    implementation = run / "implementation"
    for path in implementation.rglob("*.py"):
        require(sha256(path) == sha256(PROJECT / path.relative_to(implementation)),
                "execution source differs: " + path.name)
    require(sha256(run / "corpus.json") == report["corpus_sha256"], "corpus manifest differs")
    for name, digest in read_json(run / "corpus.json").items():
        require(sha256(run / name) == digest, "changed corpus file: " + name)
    commands = {c["label"]: c for c in report["commands"]}
    require(len(commands) == len(report["commands"]) == len(BACKENDS) * len(SPECS), "unexpected command count")
    crossings = {}
    for backend in BACKENDS:
        for cid in SPECS:
            command = commands[backend + "_" + cid]
            log = run / command["log"]
            require(command["returncode"] == 0 and not command["timed_out"] and
                    sha256(log) == command["log_sha256"], "command or raw log differs")
            raw = log.read_text(encoding="utf-8")
            row, trace = check(run / cid, backend, raw)
            require(row == report["backends"][backend]["cases"][cid], "capture summary differs")
            if trace is not None:
                require(json.loads(json.dumps(trace)) == read_json(run / cid / backend / "trace.json"),
                        "archived lane trace differs from raw log")
                if cid in CROSSINGS:
                    pointers = read_json(run / cid / backend / "reservations.json")["pointers"]
                    crossings[backend + "_" + cid] = check_crossing(
                        raw, backend, read_json(run / cid / "case.json"), pointers, trace)
    inventory = read_json(PROJECT / "configs/target_lock.json")
    manifest_path = PROJECT / inventory["evidence"] / "source_manifest.json"
    require(sha256(manifest_path) == inventory["source_manifest_sha256"], "source inventory changed")
    entries = read_json(manifest_path)
    checkouts = {}
    for path in (PROJECT / "upstream/vortex", VORTEX):
        for item in entries:
            require(sha256(path / item["path"]) == item["sha256"], "fixed source changed: " + item["path"])
        checkouts[str(path)] = len(entries)
    return dict(replayed_captures=len(commands), traced_captures=2 * len(SPECS),
                crossings=crossings, source_checkouts=checkouts, source_run_summary_sha256=sha256(run / "summary.json"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)
    execute_cli = modes.add_parser("run")
    execute_cli.add_argument("--module", type=Path, default=ORIGIN)
    review_cli = modes.add_parser("review")
    review_cli.add_argument("--run", type=Path, required=True)
    for cli in (execute_cli, review_cli):
        cli.add_argument("--run-id", required=True)
    worker = modes.add_parser("capture")
    worker.add_argument("--module", type=Path, required=True)
    worker.add_argument("--case-dir", type=Path, required=True)
    worker.add_argument("--backend", choices=BACKENDS, required=True)
    args = parser.parse_args()
    if args.mode == "capture":
        capture(args.module, args.case_dir, args.backend)
        return 0
    require(re.fullmatch(r"d-high-address-[A-Za-z0-9_-]{1,64}", args.run_id), "invalid run id")
    out = PROJECT / "results" / args.run_id
    out.mkdir()
    report = dict(run_id=out.name, argv=sys.argv, started_at=utc_now(), mode=args.mode, commands=[],
                  status="RUNNING", u280="NOT_RUN", independent_acceptance="NOT_RUN")
    with tempfile.TemporaryDirectory(prefix="d-high-address-") as temp:
        recorder = Recorder(out, report, dict(os.environ), scratch_logs=temp)
        try:
            if args.mode == "run":
                report["backends"] = {b: dict(status="NOT_RUN", cases={c: dict(status="NOT_RUN") for c in SPECS})
                                      for b in BACKENDS}
                execute(out, recorder, args.module.resolve())
            else:
                report.update(source_run=str(args.run.resolve()), **review(args.run.resolve()))
            report.update(status="PASS", exit_code=0)
        except (KeyError, OSError, ValueError, RuntimeError) as exc:
            report.update(status="FAIL", error=str(exc), exit_code=1)
        report["finished_at"] = utc_now()
        recorder.save()
    print(report["status"], out, report.get("error", ""))
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
