"""Fault sensitivity of the HOST evidence checker, not device execution tests."""
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import ptx_frontend as ptx
import run_ptx_frontend_validation as validation


class HostEvidenceTests(unittest.TestCase):
    def setup_case(self, root):
        ir = ptx.parse((ptx.PROJECT / "ptx/samples/copy_u32.ptx").read_text())
        with patch.object(validation, "N_VALUES", (0,)), patch.object(validation, "BLOCKS", (4,)):
            data = validation.corpus(root, ir, "copy")
        for path in (root / "expected").iterdir():
            shutil.copy2(path, root / "actual" / path.name)
        (root / "actual/counts.tsv").write_text("0000\t4\t0\t0\n0001\t4\t0\t0\n")
        (root / "actual/trace.tsv").write_text("")
        self.assertEqual(validation.compare(root, data)["status"], "PASS")
        return data

    def test_changed_reference_and_matching_capture_fail_integrity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = self.setup_case(root)
            ref = root / "expected/0000_z.bin"
            old = ref.read_bytes()
            changed = bytes([old[0] ^ 1]) + old[1:]
            ref.write_bytes(changed)
            (root / "actual/0000_z.bin").write_bytes(changed)
            result = validation.compare(root, data)
            self.assertEqual(result["status"], "FAIL")
            self.assertFalse(result["corpus_unchanged"])

    def test_false_predicate_access_or_missing_capture_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = self.setup_case(root)
            (root / "actual/trace.tsv").write_text("0000\t0\t0\tload\t4096\t0\n")
            self.assertEqual(validation.compare(root, data)["status"], "FAIL")
            (root / "actual/trace.tsv").write_text("")
            (root / "actual/0000_z.bin").unlink()
            self.assertEqual(validation.compare(root, data)["status"], "FAIL")
