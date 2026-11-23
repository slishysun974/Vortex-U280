"""Reject invalid U280 staging evidence using synthetic transports only."""
import ctypes as C
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from test_ptx_runtime import context
from ptx_module import ALIGNED_PARAMETER_ACCESS, BOARD_ALIGNED_SCHEMA, BOARD_LOCK_SHA, ModuleError
import ptx_runtime
import ptx_u280_aligned as aligned
import u280_aligned_pair as pair
from u280_aligned_counters import CounterCapture

PROJECT = Path(__file__).resolve().parents[1]
BUNDLE = PROJECT / "results/u280-aligned-predicate-preflight-20261121-v1/bundle"
PLAN = json.loads((BUNDLE / "plan.json").read_bytes())
VM_OFF = dict(exit_code=0, value=0)
VALID_CP = dict(offset=0x1008, reads=1, raw=aligned.CP_DEV_CAPS)


def manifest(op, route):
    member = PLAN["images"][op][route]
    return dict(entry=op + "_u32", native_entry="main", schema_version=BOARD_ALIGNED_SCHEMA,
                device_parameter_access=ALIGNED_PARAMETER_ACCESS, target_lock_hash=BOARD_LOCK_SHA,
                predicate_lowering=member["predicate_lowering"], source_sha256=aligned.IMAGES[op][0],
                image_sha256=member["image_sha256"], params_size=member["layout"]["bytes"],
                abi_version="ptx-vx-args-v1", params_align=8,
                params=[dict(f, kind="pointer" if f["size"] == 8 else "scalar", type="u" + str(8 * f["size"]))
                        for f in member["layout"]["fields"]],
                launch_limits=dict(max_block_x=32))


class FakeQueue:
    def __init__(self, mutation):
        self.mutation = mutation
        self.memory, self.launches, self.probes = {}, [], []

    def alloc(self, size):
        handle = 1 + max(self.memory, default=0)
        self.memory[handle] = bytes(size)
        return handle

    def write(self, handle, offset, data):
        assert offset == 0 and len(self.memory[handle]) == len(data)
        self.memory[handle] = data

    def read(self, handle, offset, size):
        return self.memory[handle][offset:offset + size]

    def free(self, handle):
        del self.memory[handle]

    def launch(self, module, entry, grid, block, args):
        metadata = module.manifest
        payload = bytearray(metadata["params_size"])
        for field, arg in zip(metadata["params"], args):
            value = arg.buffer * 0x100000 + arg.offset if field["kind"] == "pointer" else arg
            payload[field["offset"]:field["offset"] + field["size"]] = value.to_bytes(field["size"], "little")
        if entry == "staging_probe":
            self.probes.append(block[0])
            a0 = mscratch = 0x20000
            if self.mutation == "reuse" and len(self.probes) == 2:
                a0 = mscratch = a0 + 64
            if self.mutation == "misalign":
                a0 = mscratch = a0 + 8
            if self.mutation == "scratch":
                mscratch += 64
            report = bytearray(struct.pack("<QQ", a0, mscratch))
            for field in metadata["params"]:
                offset, width = field["offset"], field["size"]
                address = a0 + offset + (4 if self.mutation == "field" and field["name"] == "n" else 0)
                value = int.from_bytes(payload[offset:offset + width], "little")
                if self.mutation == "value" and field["name"] == "n":
                    value ^= 1
                report.extend(struct.pack("<QQ", address, value))
            handle, offset = args[0].buffer, args[0].offset
            old = self.memory[handle]
            self.memory[handle] = old[:offset] + report + old[offset + len(report):]
        else:
            op = entry[:-4]
            width = sum(f["kind"] == "pointer" for f in metadata["params"])
            n = args[width]
            route = "merged" if metadata["predicate_lowering"] else "aligned"
            self.launches.append((op, n, route))
            data = (BUNDLE / "inputs" / op / str(n) / "expected.bin").read_bytes()
            self.memory[args[width - 1].buffer] = bytes([data[0] ^ 1]) + data[1:] if self.mutation == "sentinel" else data
        return SimpleNamespace(plan=SimpleNamespace(payload=bytes(payload)))


class AlignedPairTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.output = Path(directory.name)
        self.ctx = context()
        self.ctx.backend = "u280-xrt"
        self.ctx.lock_bytes = (BUNDLE / "target_lock.json").read_bytes()
        self.ctx.caps["warps"] = 8
        self.ctx._u280_aligned_session = None
        self.ctx.board_gate = SimpleNamespace(record=dict(open_gate="PASS", binding_sha256="offline-example",
                        cp_dev_caps=dict(VALID_CP), vm_query=dict(VM_OFF)), save=lambda: None)
        self.manifests = {(op, route): manifest(op, route) for op in aligned.OPERATORS for route in aligned.ROUTES}
        self.probe = (BUNDLE / "probe/kernel.vxbin").read_bytes()

    def qualify(self, mutation=None):
        fake = FakeQueue(mutation)
        self.fake = fake
        for name in ("alloc", "write", "read", "free", "launch"):
            setattr(self.ctx, name, getattr(fake, name))
        self.ctx.wait = lambda event: None
        with patch.object(aligned, "PROBE_SHA256", aligned.digest(self.probe)):
            aligned.qualify(self.ctx, BUNDLE, self.manifests, self.probe, self.output)

    def load(self):
        image = (BUNDLE / "candidates/copy/merged/kernel.vxbin").read_bytes()
        with patch.object(ptx_runtime, "validate", return_value=(self.manifests["copy", "merged"], image)):
            return self.ctx.load("formal-module")

    def assert_blocked(self, message, mutation=None, probes=0):
        with self.assertRaisesRegex(ModuleError, message):
            self.qualify(mutation)
        self.assertIsNone(self.ctx._u280_aligned_session)
        # The fake Context may still own the diagnostic image on a failure;
        # detach that fixture to exercise the aligned loader's own gate too.
        self.ctx.modules.clear()
        with self.assertRaisesRegex(ModuleError, "fresh same-context"):
            self.load()
        self.assertEqual(self.ctx.lib.calls.count("vx_module_load_bytes"), probes)

    def test_fallback_all_ones_is_rejected_even_with_vm_off(self):
        self.ctx.board_gate.record["cp_dev_caps"]["raw"] = 0xffffffff
        self.assert_blocked("all-ones fallback")

    def test_missing_raw_cp_read_is_rejected(self):
        del self.ctx.board_gate.record["cp_dev_caps"]
        self.assert_blocked("missing or ambiguous CP_DEV_CAPS")

    def test_other_cp_values_are_rejected(self):
        for raw in (0, aligned.CP_DEV_CAPS | (1 << 24), aligned.CP_DEV_CAPS ^ 1):
            with self.subTest(raw=raw), self.assertRaisesRegex(ModuleError, "fixed D10 decoder"):
                aligned.verify_cp_read(dict(VALID_CP, raw=raw))

    def test_missing_vm_evidence_is_rejected(self):
        del self.ctx.board_gate.record["vm_query"]
        self.assert_blocked("VX_CAPS_VM_SUPPORT=0")

    def test_vm_enabled_is_rejected(self):
        self.ctx.board_gate.record["vm_query"]["value"] = 1
        self.assert_blocked("VX_CAPS_VM_SUPPORT=0")

    def test_missing_staging_evidence_cannot_be_replaced_by_receipt(self):
        (self.output / "alignment.json").write_text('{"status":"PASS"}')
        with self.assertRaisesRegex(ModuleError, "fresh same-context"):
            self.load()
        self.assertNotIn("vx_module_load_bytes", self.ctx.lib.calls)

    def test_alignment_failure_is_rejected(self):
        self.assert_blocked("64-byte-aligned", "misalign", probes=1)

    def test_a0_mismatch_is_rejected(self):
        self.assert_blocked("a0 == MSCRATCH", "scratch", probes=1)

    def test_field_address_failure_is_rejected(self):
        self.assert_blocked("field address differs", "field", probes=1)

    def test_field_value_failure_is_rejected(self):
        self.assert_blocked("field value differs", "value", probes=1)

    def test_probe_cannot_admit_with_a_field_missing_from_fixed_abi(self):
        self.manifests["copy", "aligned"]["params"].pop()
        self.assert_blocked("parameter ABI differs")

    def test_reuse_failure_is_rejected(self):
        self.assert_blocked("was not reused", "reuse", probes=1)

    def test_positive_probe_admits_both_routes_on_same_queue_only(self):
        self.qualify()
        self.assertEqual(self.fake.probes, [1] * 4 + [2] * 4 + [3] * 4)
        module = self.load()
        self.ctx.unload(module)
        self.ctx.queue = C.c_void_p(self.ctx.queue.value)
        with self.assertRaisesRegex(ModuleError, "fresh same-context"):
            self.load()
        self.assertEqual(self.ctx.lib.calls.count("vx_module_load_bytes"), 4)

    def test_full_synthetic_schedule_loads_both_routes_via_gated_context(self):
        self.qualify()

        def validate(directory, lock):
            op, route = directory.parts[-2:]
            return self.manifests[op, route], (BUNDLE / "candidates" / op / route / "kernel.vxbin").read_bytes()

        with patch.object(ptx_runtime, "validate", side_effect=validate):
            result = pair.measure(self.ctx, BUNDLE, self.output, self.output, PLAN, self.manifests)
        schedule = json.loads((BUNDLE / "pair-schedule.json").read_bytes())
        self.assertEqual(self.fake.launches, [(r["operator"], r["n"], route) for r in schedule for route in r["order"]])
        self.assertEqual(result["launches"], 420)
        self.assertEqual(self.ctx.lib.calls.count("vx_module_load_bytes"), 423)

    def test_sentinel_failure_stops_before_next_route(self):
        self.qualify("sentinel")
        image = (BUNDLE / "candidates/copy/aligned/kernel.vxbin").read_bytes()
        with patch.object(ptx_runtime, "validate", return_value=(self.manifests["copy", "aligned"], image)):
            with self.assertRaisesRegex(ValueError, "output or sentinel differs"):
                pair.measure(self.ctx, BUNDLE, self.output, self.output, PLAN, self.manifests)
        self.assertEqual(self.fake.launches, [("copy", 1024, "aligned")])


class CounterCaptureTests(unittest.TestCase):
    def capture(self, responses):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.ctx = context()
        values = iter(responses)

        def read(device, group, address, core, pointer):
            self.assertEqual((group, core), (0, 0))
            self.assertIn(address, (0xB00, 0xB02))
            code, value = next(values)
            if value is not None:
                C.cast(pointer, C.POINTER(C.c_uint64))[0] = value
            return code

        self.ctx.lib.vx_device_mpm_query = read
        return CounterCapture(self.ctx, self.root)

    def test_counts_are_deltas_after_idle_stability_is_verified(self):
        first = (10, 5, 10, 5, 110, 75, 110, 75)
        second = (110, 75, 110, 75, 213, 145, 213, 145)
        c = self.capture([(0, n) for n in (*first, *second)])
        for i, cycles in enumerate((100, 103), 1):
            row = dict(scope="probe", operator="copy", n=1024, attempt=i)
            self.assertEqual(c.after(row, c.before(row)), dict(cycles=cycles, instret=70))
        c.close(0)
        self.assertEqual(c.record["status"], "PASS")
        self.assertEqual(len((self.root / "counter-reads.jsonl").read_bytes().splitlines()), 16)

    def test_stale_counts_are_blocked_with_native_values_preserved(self):
        c = self.capture([(0, 0)] * 8)
        row = dict(scope="probe", operator="copy", n=1024, attempt=1)
        self.assertIsNone(c.after(row, c.before(row)))
        c.close(420)
        self.assertEqual(c.record["status"], "BLOCKED")
        self.assertEqual(len((self.root / "counter-reads.jsonl").read_bytes().splitlines()), 8)

    def test_failed_dcr_read_is_logged_before_runtime_stops(self):
        c = self.capture([(7, None)])
        try:
            with self.assertRaises(ModuleError):
                c.before(dict(scope="probe", operator="copy", n=1024, attempt=1))
        finally:
            c.close(420)
        self.assertEqual(c.record["status"], "BLOCKED")
        self.assertEqual(self.ctx.state, "NEEDS_RECOVERY")
        raw = json.loads((self.root / "counter-reads.jsonl").read_text())
        self.assertEqual((raw["exit_code"], raw["raw"]), (7, 2**64 - 1))


@unittest.skipUnless(sys.platform.startswith("linux") and shutil.which("g++"), "requires Linux g++")
class ObserverTests(unittest.TestCase):
    def test_observer_records_real_call_and_does_not_replace_raw_return(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            observer = root / "observer.so"
            provider = root / "libxrt_coreutil.so.2"
            source = root / "provider.cpp"
            source.write_text('extern "C" unsigned read_reg(void*, unsigned) asm("_ZNK3xrt2ip13read_registerEj");\n'
                              'extern "C" unsigned read_reg(void*, unsigned offset) { return offset == 0x1008 ? 0xffffffffu : 7u; }\n')
            consumer = root / "consumer.cpp"
            consumer.write_text('extern "C" unsigned read_reg(void*, unsigned) asm("_ZNK3xrt2ip13read_registerEj");\n'
                                'extern "C" unsigned fake_open(unsigned offset) { return read_reg(nullptr, offset); }\n')
            argv = ["g++", "-shared", "-fPIC"]
            subprocess.run([*argv, source, "-Wl,-soname,libxrt_coreutil.so.2", "-o", provider], check=True)
            subprocess.run([*argv, "-std=c++11", PROJECT / "native/u280_cp_caps_observer.cpp", "-o", observer, "-ldl"], check=True)
            library = root / "consumer.so"
            subprocess.run([*argv, consumer, provider, "-Wl,-rpath," + directory, "-o", library], check=True)
            script = ("import ctypes as C, sys; p=C.CDLL(None); lib=C.CDLL(sys.argv[1]); "
                      "lib.fake_open.restype=C.c_uint32; p.u280_cp_caps_begin(); "
                      "assert lib.fake_open(0x1004)==7; assert lib.fake_open(0x1008)==0xffffffff; "
                      "raw=C.c_uint32(); assert p.u280_cp_caps_end(C.byref(raw))==1; assert raw.value==0xffffffff")
            subprocess.run([sys.executable, "-B", "-c", script, library],
                           env=dict(os.environ, LD_PRELOAD=str(observer)), check=True)
