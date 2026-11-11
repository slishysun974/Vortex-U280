import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from run_ptx_copy_trace import LOAD_PC, PARAM_PC, analyze_trace


class PtxCopyTraceTests(unittest.TestCase):
    def test_zero_array_access_still_requires_a_real_launch(self):
        case = dict(n=0, block=4, grid=1, words=17, expected_loads=0, expected_stores=0)
        addresses = dict(x=0x1020, z=0x2020)
        dispatch = "DEBUG *** dispatch CTA warp: cid=0, wid=0, cta_id=0, blockIdx=(0,0)\n"
        parameter = (f"TRACE 1: core0-pipeline decode: cta_id=0, PC={PARAM_PC:#x}, ex=LSU (#1)\n"
                     "TRACE 2: core0-lsu mem-req: op=LD, mask=1111, addr={0x3000, 0x3000, 0x3000, 0x3000}, tag=0x0, cid=0 (#1)\n")
        self.assertEqual(analyze_trace(dispatch, "simx", case, addresses)["status"], "FAIL")
        self.assertEqual(analyze_trace(dispatch + parameter, "simx", case, addresses)["status"], "PASS")

    def test_global_pc_catches_address_outside_both_allocations(self):
        case = dict(n=0, block=4, grid=1, words=17, expected_loads=0, expected_stores=0)
        addresses = dict(x=0x1020, z=0x2020)
        launch = ("115: kmu cta-fire: cta_id=0, block_idx=[0,0,0]\n"
                  f"123: core0-lsu0 Rd Req: wid=0, cta_id=0, PC={PARAM_PC:#x}, tmask=1111, "
                  "addr={0x3000, 0x3000, 0x3000, 0x3000}\n")
        stray_read = (f"125: core0-lsu0 Rd Req: wid=0, cta_id=0, PC={LOAD_PC:#x}, tmask=0001, "
                      "addr={0x1020, 0x1024, 0x1028, 0x1030e0}\n")
        result = analyze_trace(launch + stray_read, "rtlsim", case, addresses)
        self.assertTrue(result["geometry_match"])
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual([row["address"] for row in result["unexpected"]], ["0x1030e0"])


if __name__ == "__main__":
    unittest.main()
