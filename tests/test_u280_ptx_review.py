"""Fault injection into archived board results without modifying evidence files."""
import base64
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import review_u280_ptx_results as review


BOARD = review.ROOT / "results/u280-board-ptx-suite-20261110-v1"


@unittest.skipUnless((BOARD / "result.json").is_file() and (review.AFU / "summary.json").is_file(),
                     "archived local board/AFU evidence required")
class PtxReviewFaultTests(unittest.TestCase):
    def verify_modified(self, change):
        original_read = review.read
        board = copy.deepcopy(original_read(BOARD / "result.json"))
        change(board)

        def altered_read(path):
            return board if path == BOARD / "result.json" else original_read(path)

        with patch.object(review, "read", side_effect=altered_read):
            review.verify(BOARD, dict(cases={}))

    def test_original_three_case_board_batch(self):
        result = dict(cases={})
        review.verify(BOARD, result)
        self.assertEqual((result["passed_cases"], result["array_files"], result["parameter_files"]), (3, 8, 3))

    def test_self_consistent_parameter_corruption_is_rejected(self):
        def change(board):
            launch = board["jobs"]["copy_u32"]["ptx_launch"]
            launch["args"]["n"] -= 1
            ir = review.read(review.ROOT / "results/ptx-copy-trace-20261110-v1/module/frontend/ir.json")
            payload = review.pack_arguments(ir, tuple(launch["args"][p["name"]] for p in ir["params"]))
            launch.update(payload_base64=base64.b64encode(payload).decode("ascii"), payload_sha256=review.sha(payload))

        with self.assertRaisesRegex(RuntimeError, "four-way parameter bytes differ"):
            self.verify_modified(change)

    def test_self_consistent_output_corruption_is_rejected(self):
        def change(board):
            output = board["jobs"]["copy_u32"]["outputs"]["0106_z.bin"]
            payload = bytearray(base64.b64decode(output["base64"]))
            payload[0] ^= 1
            output.update(base64=base64.b64encode(payload).decode("ascii"), sha256=review.sha(payload))

        with self.assertRaisesRegex(RuntimeError, "captured bytes differ"):
            self.verify_modified(change)

    def test_incomplete_batch_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "incomplete or failed board batch"):
            self.verify_modified(lambda board: board.update(passed_cases=2))
