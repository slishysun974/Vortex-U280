"""Live D10/D12 admission for the frozen aligned PTX pair."""
import ctypes as C
from pathlib import Path
import struct

from ptx_module import (ALIGNED_PARAMETER_ACCESS, BOARD_ALIGNED_SCHEMA, BOARD_LOCK_SHA,
                        SAME_PREDICATE_LOWERING, ModuleError, digest, inspect_vxbin, write_json)

PLAN_SHA256 = "2ec4b4e20b49f34c1ee5b5b566850934d46679cb7c0b63a9bdef9012ba1c31ae"
PROBE_SHA256 = "a2797e5fe64885308a46b079bad8995839d869ea758dab433310e526b88ce16a"
CP_DEV_CAPS = 0x00061001
OPERATORS = ("copy", "vadd", "affine")
COUNTS = (1024, 16381)
ROUTES = ("aligned", "merged")
POINTERS = {"copy": ("x", "z"), "vadd": ("x", "y", "z"), "affine": ("x", "y", "z")}
IMAGES = {
    "copy": ("63d4ff7f35588af1617ba96d479cbf80c59893f4d96935508dc5c19ac26fd05c",
             "54279b4dfda7522f4931a1685e8dec1cda26cc422dbad8a970acdd4b00ea5243",
             "8855a231375529d723155c16ab432600af6cd9d188ddb1f374a1e2a31b8168bc"),
    "vadd": ("d5cb5a0a6d3745fede0c4375d5fb11e77babec02baa6b57a03ed914228aa7bc1",
             "94733e4bd8ee44d228bcd4e0db0de506368545ced429a4e2396011e8bce90c7a",
             "f99f49a9555b0ba630273c6762dc3b1e7bec5012b2a7f58f565eb0bacc98e30b"),
    "affine": ("51065e89d9aba0bd58c01e250186835acf1f9f99e0ff23e85b3201d58c25b0c3",
               "cc482ad7b537dbbbbce697d9c6da0d1258c5d1f01e5158b5524a6dc094325f10",
               "6cbec62a3f61a1e0ded99df496a8bc0e063520aeae96d9974e4045c956f11e67"),
}


def require(condition, message):
    if not condition:
        raise ModuleError("E_TARGET_MISMATCH", message, "u280_alignment")


def observe_open(ctx):
    process = C.CDLL(None)
    try:
        begin = process.u280_cp_caps_begin
        end = process.u280_cp_caps_end
    except AttributeError as error:
        raise ModuleError("E_TARGET_MISMATCH", "missing D12 CP_DEV_CAPS observer", "open") from error
    begin.argtypes, begin.restype = [], None
    end.argtypes, end.restype = [C.POINTER(C.c_uint32)], C.c_uint
    raw = C.c_uint32()
    begin()
    try:
        status = ctx.lib.vx_device_open(0, C.byref(ctx.device))
    finally:
        count = end(C.byref(raw))
    return status, dict(offset=0x1008, reads=count, raw=raw.value)


def verify_cp_read(observation):
    require(observation and observation.get("offset") == 0x1008 and observation.get("reads") == 1,
            "missing or ambiguous CP_DEV_CAPS read in vx_device_open")
    require(observation.get("raw") != 0xffffffff, "CP_DEV_CAPS all-ones fallback")
    require(observation.get("raw") == CP_DEV_CAPS, "CP_DEV_CAPS differs from the fixed D10 decoder")


def verify_vm_query(query):
    require(query and query.get("exit_code") == 0 and query.get("value") == 0,
            "requires a successful D12 VX_CAPS_VM_SUPPORT=0 query")


def verify_module(manifest, image=None):
    op, separator, suffix = manifest["entry"].rpartition("_")
    route = "merged" if manifest.get("predicate_lowering") == SAME_PREDICATE_LOWERING else "aligned"
    require(separator == "_" and suffix == "u32" and op in IMAGES
            and manifest.get("schema_version") == BOARD_ALIGNED_SCHEMA
            and manifest.get("target_lock_hash") == BOARD_LOCK_SHA
            and manifest.get("device_parameter_access") == ALIGNED_PARAMETER_ACCESS,
            "requires a fixed U280 aligned-pair module")
    source, *images = IMAGES[op]
    require(manifest.get("source_sha256") == source
            and manifest.get("image_sha256") == images[ROUTES.index(route)]
            and (image is None or digest(image) == manifest["image_sha256"]),
            "aligned-pair source or image differs from the frozen module")
    pointers = POINTERS[op]
    fields = [(name, "pointer", "u64", 8 * i, 8, 8) for i, name in enumerate(pointers)]
    fields.append(("n", "scalar", "u32", 8 * len(pointers), 4, 4))
    if op == "affine":
        fields.append(("alpha", "scalar", "u32", 28, 4, 4))
    keys = ("name", "kind", "type", "offset", "size", "align")
    require(manifest.get("abi_version") == "ptx-vx-args-v1" and manifest.get("params_align") == 8
            and manifest.get("params_size") == (24 if op == "copy" else 32)
            and [tuple(field.get(key) for key in keys) for field in manifest.get("params", ())] == fields,
            "aligned-pair parameter ABI differs from the frozen module")
    return op, route


def session(ctx):
    return ctx.board_gate, ctx.device, ctx.queue, ctx.registry.generation


def require_admitted(ctx, manifest, image=None):
    require(ctx.backend == "u280-xrt" and getattr(ctx, "_u280_aligned_session", None) is not None
            and ctx._u280_aligned_session == session(ctx),
            "fresh same-context U280 staging evidence required before aligned load or launch")
    verify_module(manifest, image)


def probe_observation(manifest, payload, before, after, offset):
    fields = manifest["params"]
    end = offset + 16 * (1 + len(fields))
    require(len(payload) == manifest["params_size"] and 0 < len(payload) <= 4096
            and before.keys() == after.keys() and "x" in after and 0 <= offset < end <= len(after["x"]),
            "incomplete bytewise staging probe capture")
    require(all(before[role] == after[role] for role in before if role != "x")
            and before["x"][:offset] == after["x"][:offset] and before["x"][end:] == after["x"][end:],
            "bytewise staging probe changed bytes outside its report")
    raw = after["x"][offset:end]
    a0, mscratch = struct.unpack_from("<QQ", raw)
    require(a0 == mscratch and a0 > 0 and a0 % 64 == 0 and a0 <= 2**64 - 4096,
            "bytewise probe requires a0 == MSCRATCH and a nonzero 64-byte-aligned slot")
    rows = []
    for field, (address, value) in zip(fields, struct.iter_unpack("<QQ", raw[16:])):
        start, width = field["offset"], field["size"]
        require(width in (4, 8) and 0 <= start <= len(payload) - width
                and address == a0 + start and address % width == 0 and field["align"] == width,
                "bytewise probe field address differs: " + field["name"])
        require(value == int.from_bytes(payload[start:start + width], "little"),
                "bytewise probe field value differs: " + field["name"])
        rows.append(dict(name=field["name"], address=address, value=value))
    return dict(a0=a0, mscratch=mscratch, fields=rows)


def exercise_probe(ctx, bundle, manifests, probe_image, output, counters=None):
    """Capture two retired launches per frozen ABI and size."""
    from ptx_launch import BufferSlice
    require(digest(probe_image) == PROBE_SHA256, "fixed bytewise probe image differs")
    inspect_vxbin(probe_image)
    evidence = []
    for selector, op in enumerate(OPERATORS, 1):
        manifest = manifests[op, "aligned"]
        require(verify_module(manifest) == (op, "aligned"), "probe ABI differs from frozen pair")
        probe = ctx._load_verified_image(dict(manifest, entry="staging_probe", schema_version=None), probe_image)
        pointers = [field["name"] for field in manifest["params"] if field["kind"] == "pointer"]
        for n in COUNTS:
            path = Path(bundle) / "inputs" / op / str(n)
            initial = {role: (path / (role + ".bin")).read_bytes() for role in pointers}
            handles = {role: ctx.alloc(len(data)) for role, data in initial.items()}
            offset = 64
            scalars = dict(n=n, alpha=0x9e3779b9)
            args = [BufferSlice(handles[name], offset, len(initial[name]) - offset, "rw")
                    if name in handles else scalars[name] for name in (p["name"] for p in manifest["params"])]
            results = []
            for attempt, marker in enumerate((0xff, 0xee), 1):
                expected = dict(initial)
                end = offset + 16 * (1 + len(manifest["params"]))
                x = expected["x"]
                expected["x"] = x[:offset] + bytes([marker]) * (end - offset) + x[end:]
                for role, data in expected.items():
                    ctx.write(handles[role], 0, data)
                sample_counters = counters if selector == 1 and n == COUNTS[0] else None
                sample = dict(scope="probe", operator=op, n=n, attempt=attempt)
                before = sample_counters.before(sample) if sample_counters is not None else None
                event = ctx.launch(probe, "staging_probe", (1, 1, 1), (selector, 1, 1), args)
                ctx.wait(event)
                if sample_counters is not None:
                    sample_counters.after(sample, before)
                actual = {role: ctx.read(handle, 0, len(expected[role])) for role, handle in handles.items()}
                capture = output / "probe" / op / str(n) / str(attempt)
                capture.mkdir(parents=True)
                (capture / "params.bin").write_bytes(event.plan.payload)
                for role, data in actual.items():
                    (capture / (role + ".before.bin")).write_bytes(expected[role])
                    (capture / (role + ".after.bin")).write_bytes(data)
                results.append(probe_observation(manifest, event.plan.payload, expected, actual, offset))
            require(results[0]["a0"] == results[1]["a0"], "retired argument slot was not reused")
            evidence.append(dict(operator=op, n=n, attempts=results))
            for handle in handles.values():
                ctx.free(handle)
        ctx.unload(probe)
    return evidence


def qualify(ctx, bundle, manifests, probe_image, output, counters=None):
    """Authorize aligned loads only after same-context U280 observations."""
    with ctx.mutex:
        ctx.ready("u280_alignment")
        require(ctx.backend == "u280-xrt" and digest(ctx.lock_bytes) == BOARD_LOCK_SHA
                and not ctx.modules and ctx._u280_aligned_session is None
                and ctx.board_gate.record.get("open_gate") == "PASS", "requires a fresh fixed U280 context")
        gate = ctx.board_gate
        verify_cp_read(gate.record.get("cp_dev_caps"))
        verify_vm_query(gate.record.get("vm_query"))
        evidence = exercise_probe(ctx, bundle, manifests, probe_image, output, counters)
        receipt = dict(schema="u280-aligned-staging-gate-v1", status="PASS", run_id=ctx.run_id,
                       binding_sha256=gate.record["binding_sha256"], probe_sha256=PROBE_SHA256,
                       cp_dev_caps=gate.record["cp_dev_caps"], vm_query=gate.record["vm_query"], workloads=evidence)
        write_json(output / "alignment.json", receipt)
        gate.record["aligned_staging"] = dict(status="PASS", sha256=digest((output / "alignment.json").read_bytes()))
        gate.save()
        ctx._u280_aligned_session = session(ctx)
        return receipt
