"""Rebuild the new predicate witness and run frozen E answers on three fixed D5 models."""
import argparse
import ctypes
import os
from pathlib import Path
import struct
import sys

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
sys.path[:0] = [str(PROJECT / p) for p in ("scripts", "experiments/ptx-aligned-production",
                                            "experiments/ptx-performance-attribution")]
from check_c_v03_receipt import BINDINGS, TOOLCHAIN
from ptx_runtime import BufferSlice, Context, Q
from run_native_smoke import Recorder, sha256, utc_now
from run_ptx_copy import SIM_LOCK, VORTEX, read_json, require, run_stage, write_json
from validate import witness

FROZEN = PROJECT / "results/e-v14-frozen-20261122-v1"
ANCHOR = "b116876ecc4f7dbd7941df93e31aae1dad7e19c9b1aae4699afb31f8f8d8e523"
REFERENCE = PROJECT / "results/local-ptx-same-predicate-production-build-20261121-v1"
MODELS = ("simx", "rtlsim", "xrtsim")


def corpus():
    require(sha256(FROZEN / "manifest.json") == ANCHOR, "E corpus anchor differs")
    data = read_json(FROZEN / "manifest.json")
    for name, digest in data["files"].items():
        require(sha256(FROZEN / name) == digest, "frozen input differs: " + name)
    return data["cases"]


def execute_case(ctx, module, spec, dest):
    dest.mkdir()
    src = FROZEN / spec["id"]
    handles, addresses, args = {}, {}, []
    roles = spec["roles"]
    sizes = {}
    for r in roles:
        raw = (src / (r + ".bin")).read_bytes()
        sizes[r] = len(raw)
        handle = handles[r] = ctx.alloc(len(raw))
        ctx.write(handle, 0, raw)
        off = 4 * spec["offsets"][r]
        access = ("rw" if spec["op"] == "predicate_turn" else "w") if r == "z" else "r"
        args.append(BufferSlice(handle, off, len(raw) - off, access))
        base = Q()
        ctx.check(ctx.lib.vx_buffer_address(ctx.buffers[handle][0], ctypes.byref(base)), "query_address")
        addresses[r] = base.value
        before = ctx.read(handle, 0, len(raw))
        (dest / (r + "-before.bin")).write_bytes(before)
        require(raw == before, "upload mismatch: " + r)
    scalars = [spec["n"]]
    if spec["op"] in ("affine", "predicate_turn"):
        scalars.append(spec["alpha" if spec["op"] == "affine" else "selected"])
    pointers = [addresses[r] + 4 * spec["offsets"][r] for r in roles]
    packed = struct.pack("<" + "Q" * len(roles) + "I" * len(scalars), *pointers, *scalars)
    packed += bytes(-len(packed) % 8)
    write_json(dest / "bases.json", addresses)
    event = ctx.launch(module, module.manifest["entry"], (spec["grid"], 1, 1),
                       (spec["block"], 1, 1), args + scalars)
    payload = ctypes.string_at(event.payload, len(event.plan.payload))
    (dest / "params.bin").write_bytes(payload)
    completion = ctx.wait(event)
    write_json(dest / "event.json", completion)
    require(payload == packed and completion["status"] == "COMPLETE", "ABI or completion mismatch")
    for r in roles:
        actual = ctx.read(handles[r], 0, sizes[r])
        (dest / (r + "-after.bin")).write_bytes(actual)
        expected = src / (("expected-z" if r == "z" else r) + ".bin")
        require(actual == expected.read_bytes(), "full buffer mismatch: " + r)
        ctx.free(handles[r])


def worker(out, built, backend):
    cases = corpus()
    raw = out / backend
    raw.mkdir()
    binding = BINDINGS / backend / "binding.json"
    ctx = Context(binding, SIM_LOCK, backend=backend, run_id=out.name)
    modules = {}
    try:
        for i, spec in enumerate(cases, 1):
            op = spec["op"]
            path = out / op if op == "predicate_turn" else built / "modules" / op
            module = ctx.load(path)
            front = read_json(path / "frontend_manifest.json")
            require(sha256(FROZEN / "sources" / (op + ".ptx")) == module.manifest["source_sha256"]
                    and module.manifest["predicate_lowering"] == "same-predicate-v1"
                    and module.manifest["device_parameter_access"] == "vortex2-queue-args-align-v1"
                    and front["compiler_id"] == "ptx-vx-frontend-v1.4"
                    and front["compiler_sha256"] == sha256(PROJECT / "scripts/ptx_frontend_v14.py"),
                    "wrong source, compiler or lowering")
            modules[op] = module.manifest["image_sha256"]
            execute_case(ctx, module, spec, raw / spec["id"])
            event = read_json(raw / spec["id"] / "event.json")
            require(event == dict(status="COMPLETE", backend=backend, generation=0, event_id=i),
                    "runtime completion identity mismatch")
            ctx.unload(module)
            print(backend, spec["id"], "PASS", flush=True)
    finally:
        if ctx.state == "READY":
            ctx.close()
    witness(raw, backend, built)
    v03 = read_json(raw / "witness/summary.json")
    require(v03["launch_attempts"] == len(v03["completed"]) == 13 and v03["high"] == 5
            and v03["alias"] == "PASS", "V03 coverage mismatch")
    write_json(raw / "receipt.json", dict(status="PASS", binding=sha256(binding), images=modules,
               new_cases=len(cases), full_buffers_each_direction=sum(len(s["roles"]) for s in cases),
               v03=v03, board="NOT_RUN"))


def run(out, built, rec):
    corpus()
    ref = read_json(REFERENCE / "summary.json")
    actual = read_json(built / "summary.json")
    require(actual["status"] == "PASS" and actual["exit_code"] == 0 and len(actual["modules"]) == 5
            and actual["lock_sha256"] == sha256(SIM_LOCK), "fresh build failed")
    for name, item in actual["modules"].items():
        image = built / "modules" / name / "kernel.vxbin"
        require(item["merged_image"] == sha256(image) == ref["modules"][name]["merged_image"],
                "delivered binary differs: " + name)
    rec.summary.update(freeze=ANCHOR, fresh_build=sha256(built / "summary.json"), models={},
                       frontend=sha256(PROJECT / "scripts/ptx_frontend_v14.py"), rebuilt_images=actual["modules"],
                       target_lock=sha256(SIM_LOCK), root_lock=sha256(PROJECT / "configs/target_lock.json"))
    for label, cmd in (("upstream_head", ["git", "-C", VORTEX, "rev-parse", "HEAD"]),
                       ("upstream_diff", ["git", "-C", VORTEX, "diff", "--exit-code", "HEAD", "--"])):
        output = run_stage(rec, label, cmd, out)
        if label == "upstream_head":
            require(output.strip() == read_json(SIM_LOCK)["vortex"]["commit"], "wrong upstream checkout")
    cli = [sys.executable, "-B", PROJECT / "scripts/ptx_module.py"]
    probe = out / "predicate_turn"
    for action, options in (
            ("prepare", [FROZEN / "sources/predicate_turn.ptx", "--output", probe,
                         "--hardware", SIM_LOCK.with_name("native_smoke.json"), "--device-parameter-access",
                         "vortex2-queue-args-align-v1", "--predicate-lowering", "same-predicate-v1"]),
            ("build", [probe, "--vortex-source", VORTEX, "--tooldir", TOOLCHAIN,
                       "--build-root", PROJECT / "build" / out.name / "predicate_turn"]),
            ("validate", [probe])):
        run_stage(rec, action, cli + [action, *options, "--target-lock", SIM_LOCK], out, 420)
    # Independently check the three source regions actually exercised the intended generation change.
    src = (probe / "source.ptx").read_text().splitlines()
    gen = (probe / "kernel_body.hpp").read_text().splitlines()
    mapping = {row["line"]: row["generated_line"] - 1 for row in read_json(probe / "source_map.json")}
    groups = []
    for line, source in enumerate(src, 1):
        if "ld.global.u32" in source:
            start = mapping[line]
            require([mapping[line + j] for j in range(3)] == list(range(start, start + 3))
                    and gen[start - 1].strip().startswith("if (") and gen[start + 3].strip() == "}"
                    and ("!" in gen[start - 1]) == source.strip().startswith("@!")
                    and "load32" in gen[start] and "store32" in gen[start + 2], "predicate region differs")
            groups.append(dict(source_line=line, generated_guard=gen[start - 1].strip()))
    require(len(groups) == 3, "expected three source regions")
    rec.summary["probe_groups"] = groups
    for backend in MODELS:
        binding = read_json(BINDINGS / backend / "binding.json")
        rec.env.update(VORTEX_DRIVER=binding["driver"], LD_LIBRARY_PATH=binding["library_dir"],
                       VORTEX_PROFILING="0", XRT_DEVICE_INDEX="0")
        run_stage(rec, backend, [sys.executable, "-B", __file__, str(out), str(built), "--worker", backend],
                  out, 600)
        rec.summary["models"][backend] = read_json(out / backend / "receipt.json")
    run_stage(rec, "runner_self_test", [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-v"],
              PROJECT, 900)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out", type=Path)
    parser.add_argument("built", type=Path)
    parser.add_argument("--worker", choices=MODELS)
    args = parser.parse_args()
    out, built = args.out.resolve(), args.built.resolve()
    if args.worker:
        worker(out, built, args.worker)
    else:
        out.mkdir()
        report = dict(status="RUNNING", started_at=utc_now(), commands=[], argv=sys.argv,
                      physical_u280="NOT_RUN", human_signoff="NOT_RUN", new_lane_traces="NOT_RUN")
        env = {k: v for k, v in os.environ.items() if k not in
               ("XCLBIN_PATH", "XCL_EMULATION_MODE", "XRT_INI_PATH", "VORTEX_CP_POLL_TIMEOUT_S")}
        recorder = Recorder(out, report, env)
        try:
            run(out, built, recorder)
            report.update(status="PASS", exit_code=0)
        except Exception as error:
            report.update(status="FAIL", exit_code=1, error=str(error))
        report["finished_at"] = utc_now()
        recorder.save()
        print(report["status"], report.get("error", ""))
        sys.exit(report["exit_code"])
