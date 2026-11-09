"""Regression evidence must reject missing, corrupted and changed references."""
import json
import contextlib
import io
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import native_boundary as boundary
import run_native_smoke as smoke


class NativeBoundaryTests(unittest.TestCase):
    def test_block32_corpus_has_tail_and_mixed_predicates_within_capacity(self):
        with tempfile.TemporaryDirectory() as temp:
            corpus = boundary.create_corpus(Path(temp), "block32-v1")
            self.assertEqual(len(corpus["cases"]), 152)
            self.assertEqual({c["block"] for c in corpus["cases"]}, {1, 4, 7, 16, 31, 32})
            for case in corpus["cases"]:
                self.assertLessEqual(case["block"] * case["grid"], 1024)
                self.assertLessEqual(case["audit_words"], 4112)
            self.assertTrue(any(c["n"] == 0 and c["block"] == 32 and c["grid"] == 1
                                for c in corpus["cases"]))
            self.assertEqual({c["predicate"] for c in corpus["cases"] if c["block"] == 32}, {0, 1, 2})

    def test_pending_or_failed_boundary_does_not_inherit_demo_pass(self):
        with tempfile.TemporaryDirectory() as temp, contextlib.redirect_stdout(io.StringIO()):
            root = Path(temp)

            def demo(recorder, args, configs):
                recorder.summary["demo_execution"] = "PASS"
                return True, "demo_run"

            def failed_boundary(recorder, args, configs):
                self.assertEqual(recorder.summary["status"], "RUNNING")
                recorder.summary["native_boundary"] = {"status": "FAIL"}
                return False, "boundary_run"

            with patch.object(smoke, "load_configuration", return_value=""), \
                    patch.object(smoke, "preflight"), patch.object(smoke, "run_build", side_effect=demo), \
                    patch.object(boundary, "run_boundary", side_effect=failed_boundary):
                code = smoke.main(["--tooldir", str(root / "tools"), "--source", str(root / "source"),
                                   "--results-dir", str(root), "--run-id", "failure", "--native-boundary"])
            result = json.loads((root / "failure/summary.json").read_text())
            self.assertEqual(code, 1)
            self.assertEqual(result["status"], "FAIL")
            self.assertEqual(result["upstream_smoke"], "PASS")
            self.assertEqual(result["native_boundary"]["status"], "FAIL")
            self.assertEqual(result["p0_three_kernels"], "NOT_RUN")

    def test_unsigned_reference_known_overflow_and_predication(self):
        case = dict(sequence=0, n=8, block=16, grid=1, repeat=0,
                    words=32, audit_words=80, predicate=0, operation=1, alpha=boundary.MASK)
        src, ref = boundary.make_vectors(case)
        self.assertEqual(ref["z"][9], 0xfffffffd)  # max + (max-1)
        case["operation"] = 2
        src, ref = boundary.make_vectors(case)
        self.assertEqual(ref["z"][9], 0xffffffff)  # max*max + (max-1)
        case["predicate"] = 1
        src, ref = boundary.make_vectors(case)
        self.assertEqual(ref["z"], src["z"])
        self.assertNotEqual(ref["audit"], src["audit"])
        case.update(n=0, predicate=0)
        src, ref = boundary.make_vectors(case)
        self.assertEqual(ref["z"], src["z"])
        self.assertEqual(ref["audit"][8:12], [0, 0, 16, 1])

    def test_corpus_captures_and_integrity_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            corpus = boundary.create_corpus(root)
            self.assertEqual(len(corpus["cases"]), 140)
            self.assertEqual({c["n"] for c in corpus["cases"]}, set(boundary.N_VALUES))
            self.assertEqual({c["block"] for c in corpus["cases"]}, {1, 4, 7, 16})
            self.assertEqual(boundary.compare_captures(root, corpus)["passed"], 0)
            shutil.copytree(root / "expected", root / "actual")
            self.assertEqual(boundary.compare_captures(root, corpus)["status"], "PASS")
            output = root / "actual/000_z.bin"
            original = output.read_bytes()
            output.write_bytes(bytes([original[0] ^ 1]) + original[1:])
            self.assertEqual(boundary.compare_captures(root, corpus)["passed"], 139)
            output.write_bytes(original)
            reference = root / "expected/000_z.bin"
            reference.write_bytes(bytes([original[0] ^ 1]) + original[1:])
            output.write_bytes(reference.read_bytes())
            result = boundary.compare_captures(root, corpus)
            self.assertEqual(result["status"], "FAIL")
            self.assertIn("corpus_changed", json.dumps(result))
            reference.write_bytes(original)
            output.write_bytes(original)
            (root / "inputs/cases.tsv").write_text("changed\n")
            self.assertFalse(boundary.compare_captures(root, corpus)["case_table_unchanged"])


if __name__ == "__main__":
    unittest.main()
