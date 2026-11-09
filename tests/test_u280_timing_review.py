"""Prevent empty rule tables from turning severe warnings into zero counts."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from review_u280_timing import rule_table


class TimingReviewTests(unittest.TestCase):
    def test_real_reports_include_toc_and_totals(self):
        folder = ROOT / "results/u280-archive-20261109-v5/returned/reports/link/imp"
        if not folder.is_dir():
            self.skipTest("Archived Vivado reports are required")
        for name, total, critical in (("methodology_drc", 100, 9), ("drc", 343, 0)):
            rows = rule_table((folder / ("impl_1_hw_bb_locked_" + name + "_routed.rpt")).read_text())
            self.assertEqual(sum(r["count"] for r in rows), total)
            self.assertEqual(sum(r["count"] for r in rows if r["severity"] == "Critical Warning"), critical)

    def test_empty_or_count_mismatch_is_error(self):
        for text in ("Violations found: 0\n", "Violations found: 2\n| TIMING-1 | Critical Warning | issue | 1 |"):
            with self.assertRaises(ValueError):
                rule_table(text)

    def test_duplicate_rules_are_error(self):
        row = "| TIMING-1 | Critical Warning | issue | 1 |\n"
        with self.assertRaises(ValueError):
            rule_table("Violations found: 2\n" + row * 2)


if __name__ == "__main__":
    unittest.main()
