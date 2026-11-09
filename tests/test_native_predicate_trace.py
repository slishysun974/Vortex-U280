import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from native_predicate_trace import parse_request, analyze


class NativeTraceChecks(unittest.TestCase):
    def test_lane_order_and_mask_holes(self):
        # Format observed in the actual pinned SimX trace: BitVector renders low bit first.
        self.assertEqual(parse_request("DEBUG 5: core0-lsu0 mem-req: op=LD, mask=1010, addr={0x100, -, 0x108, -}, tag=0", "simx"),
                         [("LD", 0x100), ("LD", 0x108)])
        self.assertEqual(parse_request("0: core0-lsu0 Rd Req: wid=0, tmask=0101, addr={0xdead, 0x108, 0xbad, 0x100}, attr={0}", "rtlsim"),
                         [("LD", 0x108), ("LD", 0x100)])

    def test_unknown_request_fails_closed(self):
        with self.assertRaises(ValueError):
            parse_request("DEBUG 5: lsu0 mem-req: op=LD, mask=0101, addr={bad}", "simx")
        self.assertIsNone(parse_request("DEBUG 5: dcache mem-req: something unrelated", "simx"))

    def test_empty_trace_and_extra_false_lane_read_rejected(self):
        case = dict(id="000", label="all_false", operation=0, n=4, block=4, grid=1, predicate=1)
        corpus = dict(cases=[case])
        self.assertEqual(analyze("", corpus, "simx")["status"], "FAIL")
        setup = "".join(f"BUFFER {j} address={65536 + j * 16384}\n" for j in range(4))
        audit = "DEBUG 0: lsu0 mem-req: op=ST, mask=1, addr={0x1c020}, tag=0\n"
        end = "CAPTURED 000 n=4 block=4 grid=1\n"
        self.assertEqual(analyze(setup + audit + end, corpus, "simx")["status"], "PASS")
        wrong = "DEBUG 1: lsu0 mem-req: op=LD, mask=1, addr={0x10020}, tag=0\n"
        result = analyze(setup + audit + wrong + end, corpus, "simx")
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["cases"][0]["unexpected"], [dict(op="LD", address="0x10020", count=1)])


if __name__ == "__main__":
    unittest.main()
