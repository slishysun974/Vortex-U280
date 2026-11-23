"""Negative controls for the D probe's frontend diagnostics and lane evidence."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import ptx_frontend_v12 as frontend
from run_d_guarded_wide import AUDIT, BASE_BIAS, LOAD, SOURCE, STORE, check_trace


class ProbeDiagnostics(unittest.TestCase):
    def reject(self, before, after, code):
        source = SOURCE.read_text(encoding="utf-8")
        self.assertEqual(source.count(before), 1)
        with self.assertRaises(frontend.PtxError) as caught:
            frontend.parse(source.replace(before, after), "probe.ptx")
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(caught.exception.location["file"], "probe.ptx")
        self.assertGreater(caught.exception.location["column"], 0)

    def test_misaligned_negative_displacement(self):
        self.reject("[addr-4]", "[addr-2]", "E_TYPE")

    def test_wrong_wide_destination(self):
        self.reject("mul.wide.u32 offset, index", "mul.wide.u32 value, index", "E_TYPE")

    def test_integer_offset_as_global_pointer(self):
        self.reject("global_ptr, input_ptr;", "global_ptr, offset;", "E_TYPE")

    def test_masked_load_cannot_define_value_for_all_lanes(self):
        self.reject("mov.u32 value, 0xa5a55a5a;", "", "E_TYPE")

    def test_scalar_parameter_displacement(self):
        self.reject("[bias]", "[bias+4]", "E_PARAM_LAYOUT")

    def test_unlisted_load_modifier(self):
        self.reject("ld.global.u32 value", "ld.global.ca.u32 value", "E_UNSUPPORTED")


class LaneControls(unittest.TestCase):
    pointers = dict(x=0x1020, z=0x2020, audit=0x3020)
    case = dict(block=4, grid=1, n=4, skip_lane=1, bias=BASE_BIAS, words=13)

    def fixture(self, backend):
        requests = [(LOAD, "LD", [0x1020, None, 0x1028, 0x102c]),
                    (STORE, "ST", [0x2024, None, 0x202c, 0x2030]),
                    (AUDIT, "ST", [0x3020, 0x3024, 0x3028, 0x302c])]
        lines = []
        if backend == "simx":
            lines.append("DEBUG *** dispatch CTA warp: cid=0, wid=0, cta_id=0, rank=0/1, blockIdx=(0,0)")
        else:
            lines.extend(["1: kmu cta-fire: cta_id=0, block_idx=[0,0,0], PC=0x100, param=0x300,",
                          "1: cluster0-socket0-core0-scheduler-cta_dispatch kmu-accept: cta_id=3, PC=0x100, param=0x300,"])
        for uid, (pc, op, addresses) in enumerate(requests):
            lanes = addresses if backend == "simx" else addresses[::-1]
            mask = "".join("0" if addr is None else "1" for addr in lanes)
            data = ", ".join(hex(addr) if addr is not None else "-" for addr in lanes)
            if backend == "simx":
                lines.append(f"TRACE 2: cluster0-socket0-core0-pipeline decode: cid=0, wid=0, cta_id=0, PC={pc:#x}, ex=LSU (#{uid})")
                lines.append(f"TRACE 3: core0-lsu mem-req: op={op}, mask={mask}, addr={{{data}}} (#{uid})")
            else:
                direction = "Rd" if op == "LD" else "Wr"
                lines.append(f"3: cluster0-socket0-core0-execute-lsu0 {direction} Req: wid=0, cta_id=3, PC={pc:#x}, tmask={mask}, addr={{{data}}}")
        if backend == "simx":
            lines.append("TRACE 4: cluster0-socket0-core0 warp-state: wid=0, tmask=0000")
        else:
            lines.append("4: cluster0-socket0-core0-scheduler-cta_dispatch warp-done: wid=0, cta_id=3, rem_warps=0, cta_done=1")
        return "\n".join(lines) + "\n"

    def test_opposite_display_order_matches_same_logical_lanes(self):
        for backend in ("simx", "rtlsim"):
            with self.subTest(backend=backend):
                checked = check_trace(self.fixture(backend), backend, self.case, self.pointers)
                self.assertEqual(checked["status"], "PASS")
                self.assertEqual(checked["counts"], dict(guarded_load=3, guarded_store=3, audit_store=4))

    def test_same_address_multiset_with_swapped_lanes_is_rejected(self):
        for backend in ("simx", "rtlsim"):
            raw = self.fixture(backend)
            swapped = raw.replace("0x1020", "SWAP").replace("0x1028", "0x1020").replace("SWAP", "0x1028")
            with self.subTest(backend=backend):
                self.assertEqual(check_trace(swapped, backend, self.case, self.pointers)["status"], "FAIL")

    def test_masked_lane_access_outside_all_allocations_is_rejected(self):
        raw = self.fixture("simx").replace("mask=1011, addr={0x1020, -", "mask=1111, addr={0x1020, 0x100001020")
        self.assertEqual(check_trace(raw, "simx", self.case, self.pointers)["status"], "FAIL")

    def test_missing_audit_for_masked_lane_is_rejected(self):
        raw = self.fixture("simx").replace("mask=1111, addr={0x3020, 0x3024", "mask=1011, addr={0x3020, -")
        self.assertEqual(check_trace(raw, "simx", self.case, self.pointers)["status"], "FAIL")
