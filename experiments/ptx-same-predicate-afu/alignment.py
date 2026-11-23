"""Audit the NOXRT queue and measure the staged parameter address on device."""

import argparse
import ctypes as C
from pathlib import Path
import struct
import sys

from afu_contract import (BACKEND, FIXED_BINDING, PROJECT, SIM_LOCK, Recorder, check_binding, clean_env, driver_env,
                          read_json, require, run_stage, sha256, source_audit, utc_now, write_json)
from model import FORMS, receipt, workloads_from_kits
from check_c_v03_receipt import WIDE
from measure import launch
from ptx_frontend_v12 import pack_arguments
from ptx_frontend_v13 import DEVICE_BASE_ALIGNMENT, MAX_PAYLOAD_BYTES
from ptx_module import ALIGNED_PARAMETER_ACCESS, SAME_PREDICATE_LOWERING, inspect_vxbin, validate
from ptx_runtime import Context, Q, VX_CAPS_VM_SUPPORT
from u280_perf_pair import ABI, GUARD, load_image, payload_bytes


PROBE = PROJECT / "results/local-ptx-align-build-20261121-v1"
PROBE_OFFSET = 4 * GUARD
PROBE_SIZE = 16


def verified_alignment(root, binding, built):
    summary = read_json(root / "summary.json")
    capture = read_json(root / "capture.json")
    require(summary["status"] == capture["status"] == "PASS" and summary["exit_code"] == capture["exit_code"] == 0 and
            summary["binding_sha256"] == capture["binding_sha256"] == sha256(binding) and
            summary["build_sha256"] == capture["build_sha256"] == sha256(built / "summary.json") and
            summary["capture_sha256"] == sha256(root / "capture.json") and
            all(c["returncode"] == 0 and not c["timed_out"] and sha256(root / c["log"]) == c["log_sha256"]
                for c in summary["commands"]) and capture["vm_support"] == 0 and
            capture["slot_alignment"] == DEVICE_BASE_ALIGNMENT and capture["probe_launches"] == len(capture["probes"]) == 10,
            "AFU alignment prerequisite did not pass for these exact artifacts")
    require({row["payload_bytes"] for row in capture["probes"].values()} == {24, 32, 40, MAX_PAYLOAD_BYTES},
            "AFU proof payload coverage differs")
    for name, row in capture["probes"].items():
        folder = root / name
        before, after = (folder / filename for filename in ("x.before.bin", "x.after.bin"))
        raw, original = after.read_bytes(), before.read_bytes()
        require(row == read_json(folder / "alignment.json") and row["status"] == "PASS" and
                0 < row["a0"] == row["mscratch"] and row["a0"] % DEVICE_BASE_ALIGNMENT == 0 and
                struct.unpack_from("<QQ", raw, PROBE_OFFSET) == (row["a0"], row["mscratch"]) and
                raw[:PROBE_OFFSET] == original[:PROBE_OFFSET] and raw[PROBE_OFFSET+PROBE_SIZE:] == original[PROBE_OFFSET+PROBE_SIZE:] and
                row["params_sha256"] == sha256(folder / "params.bin") and row["before_sha256"] == sha256(before) and
                row["after_sha256"] == sha256(after) and all(field["address"] == row["a0"] + field["offset"] and
                    field["address"] % field["alignment"] == 0 for field in row["fields"].values()), "AFU address evidence differs")
    return capture


def address(ctx, handle):
    value = Q()
    ctx.check(ctx.lib.vx_buffer_address(ctx.buffers[handle][0], C.byref(value)), "probe_buffer_address")
    return value.value


def open_afu(binding, out):
    ctx = Context(binding, SIM_LOCK, backend=BACKEND, run_id=out.name)
    vm = Q()
    ctx.check(ctx.lib.vx_device_query(ctx.device, VX_CAPS_VM_SUPPORT, C.byref(vm)), "query_vm")
    try:
        require(vm.value == 0, "AFU VM is enabled; the audited staging allocation path does not apply")
        require("libxrt_core" not in Path("/proc/self/maps").read_text(), "unexpected vendor XRT library in NOXRT process")
    except Exception:
        ctx.close()
        raise
    return ctx


def capture(ctx, native, descriptor, label, out, roles, source_bytes, payload_for, *, staging_size=None):
    case = out / label
    case.mkdir()
    handles = {role: ctx.alloc(len(source_bytes[role])) for role in roles}
    bases = {role: address(ctx, handle) for role, handle in handles.items()}
    for role, raw in source_bytes.items():
        ctx.write(handles[role], 0, raw)
    payload = payload_for(bases)
    size = descriptor["params_size"]
    require(len(payload) == size and struct.unpack_from("<Q", payload)[0] == bases["x"] + PROBE_OFFSET,
            "probe requires the observed output pointer at payload offset zero")
    if staging_size is not None:
        require(size <= staging_size <= MAX_PAYLOAD_BYTES, "invalid slot boundary test")
        payload = payload.ljust(staging_size, b"\xa7")
    (case / "params.bin").write_bytes(payload)
    launch(ctx, native, dict(grid=1, block=1), payload)
    result = ctx.read(handles["x"], 0, len(source_bytes["x"]))
    (case / "x.before.bin").write_bytes(source_bytes["x"])
    (case / "x.after.bin").write_bytes(result)
    require(result[:PROBE_OFFSET] == source_bytes["x"][:PROBE_OFFSET] and
            result[PROBE_OFFSET+PROBE_SIZE:] == source_bytes["x"][PROBE_OFFSET+PROBE_SIZE:], "probe outside output span")
    param, mscratch = struct.unpack_from("<QQ", result, PROBE_OFFSET)
    require(param == mscratch and param >= 0x10000 and param % DEVICE_BASE_ALIGNMENT == 0,
            "AFU staging base differs from MSCRATCH or lacks alignment")
    require(all(not (base < param + MAX_PAYLOAD_BYTES and param < base + len(source_bytes[role]))
                for role, base in bases.items()), "staging slot overlaps a probe allocation")
    fields = {}
    for field in descriptor["params"]:
        width = {"u32": 4, "u64": 8}[field["type"]]
        offset = field["offset"]
        require(width == field["align"] == field["size"] and 0 <= offset <= size - width and (param + offset) % width == 0,
                "actual AFU address misaligned at " + field["name"])
        fields[field["name"]] = dict(address=param + offset, alignment=width, offset=offset)
    more_captures = {}
    for role in roles:
        if role != "x":
            actual = ctx.read(handles[role], 0, len(source_bytes[role]))
            require(actual == source_bytes[role], "probe unexpectedly changed " + role)
            (case / (role + ".bin")).write_bytes(actual)
            more_captures[role] = sha256(case / (role + ".bin"))
        ctx.free(handles[role])
    evidence = dict(status="PASS", a0=param, mscratch=mscratch, slot_size=MAX_PAYLOAD_BYTES, bases=bases,
                    fields=fields, payload_bytes=len(payload), layout_bytes=size, params_sha256=sha256(case / "params.bin"),
                    before_sha256=sha256(case / "x.before.bin"), after_sha256=sha256(case / "x.after.bin"),
                    other_arrays_sha256=more_captures)
    write_json(case / "alignment.json", evidence)
    print(label, len(payload), hex(param), "PASS", flush=True)
    return evidence


def worker(out, binding, built):
    info = receipt(built)
    modules = {}
    for name, row in info.items():
        path = built / "modules" / name
        manifest, _ = validate(path, SIM_LOCK.read_bytes())
        require(manifest["device_parameter_access"] == ALIGNED_PARAMETER_ACCESS and
                manifest["predicate_lowering"] == SAME_PREDICATE_LOWERING and manifest["image_sha256"] == row["merged_image"],
                "formal layout identity differs")
        modules[name] = manifest, read_json(path / "ir.json")
    probe_path = PROBE / "probe/kernel.vxbin"
    record = read_json(PROBE / "summary.json")
    require(record["status"] == "PASS" and record["lock_sha256"] == sha256(SIM_LOCK) and
            sha256(probe_path) == record["probe"]["kernel.vxbin"], "archived bytewise probe identity differs")
    raw = probe_path.read_bytes()
    inspect_vxbin(raw)
    probes = {}
    for batch in ("original", "witness_and_limit"):
        ctx = open_afu(binding, out)
        try:
            native = load_image(ctx, C.create_string_buffer(raw, len(raw)), "bytewise_address_probe")
            if batch == "original":
                for op, spec, frozen in workloads_from_kits():
                    roles = ABI[op][1]
                    inputs = {role: (frozen / (role + ".bin")).read_bytes() for role in roles}
                    label = f"{op}-{spec['n']}"
                    probes[label] = capture(ctx, native, modules[op][0], label, out, roles, inputs,
                                            lambda bases: payload_bytes(op, bases, spec["n"]))
            else:
                for name, limit in ((FORMS, None), (WIDE, None), (WIDE, MAX_PAYLOAD_BYTES), (FORMS, None)):
                    descriptor, ir = modules[name]
                    roles = [field["name"] for field in descriptor["params"] if field["kind"] == "pointer"]
                    inputs = {role: bytes([0x35 + len(role)]) * (192 + 64*i) for i, role in enumerate(roles)}
                    label = f"{name}-{len(probes)}"
                    probes[label] = capture(ctx, native, descriptor, label, out, roles, inputs,
                        lambda bases: pack_arguments(ir, [bases[field["name"]] + PROBE_OFFSET if field["kind"] == "pointer"
                            else 0x56 for field in descriptor["params"]]), staging_size=limit)
            ctx.unload(native)
        finally:
            if ctx.state == "READY":
                ctx.close()
    require(len(probes) == 10 and len({row["a0"] for row in probes.values()}) >= 2, "insufficient AFU staging address coverage")
    # Each context made sequential launches, so the address repeats through the pool.
    require(len({row["a0"] for name, row in probes.items() if name.startswith((FORMS, WIDE))}) == 1,
            "the tested pooled releases did not recycle the slot")
    write_json(out / "capture.json", dict(status="PASS", exit_code=0, vm_support=0, slot_alignment=DEVICE_BASE_ALIGNMENT,
               binding_sha256=sha256(binding), probe_image_sha256=sha256(probe_path),
               build_sha256=sha256(built / "summary.json"), probe_launches=len(probes), probes=probes))


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--build", type=Path, required=True)
    cli.add_argument("--trace-build", type=Path)
    cli.add_argument("--output", type=Path, required=True)
    cli.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = cli.parse_args()
    out, built = args.output.resolve(), args.build.resolve()
    binding = args.trace_build.resolve() / "binding/binding.json" if args.trace_build else FIXED_BINDING
    require(out.parent == PROJECT / "results" and out.name.startswith("local-ptx-same-predicate-afu-align-"),
            "choose a fresh AFU alignment run")
    if args.worker:
        worker(out, binding, built)
        return 0
    out.mkdir()
    report = dict(status="RUNNING", commands=[], started_at=utc_now(), argv=[sys.executable, "-B", *sys.argv],
                  board_execution="NOT_RUN", backend=BACKEND, scope="bytewise native argument-address probe")
    rec = Recorder(out, report, clean_env())
    try:
        info, _ = check_binding(binding, fixed=args.trace_build is None)
        source_audit(rec, out)
        driver_env(rec, info)
        deps = run_stage(rec, "no_vendor_runtime", ["readelf", "-d", Path(info["library_dir"]) / "libvortex-xrt.so"], out)
        require("[libxrtsim.so]" in deps and "libxrt_core" not in deps, "XRT driver does not link only the simulator backend")
        passes = ["--trace-build", args.trace_build.resolve()] if args.trace_build else []
        run_stage(rec, "bytewise_device_probe", [sys.executable, "-B", Path(__file__).resolve(), "--worker", "--build", built,
                  "--output", out, *passes], out, 360)
        capture = read_json(out / "capture.json")
        require(capture["status"] == "PASS" and capture["exit_code"] == 0 and sha256(binding) == capture["binding_sha256"],
                "AFU probe receipt differs")
        report.update(status="PASS", exit_code=0, binding_sha256=sha256(binding), build_sha256=capture["build_sha256"],
                      probe_count=capture["probe_launches"], capture_sha256=sha256(out / "capture.json"))
    except Exception as error:
        report.update(status="FAIL", exit_code=1, error=str(error))
    report["finished_at"] = utc_now()
    rec.save()
    print(report["status"], out, report.get("error", ""))
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
