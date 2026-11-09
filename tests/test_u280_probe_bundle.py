import base64
import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import prepare_u280_probe as probe


class ProbeBundleTests(unittest.TestCase):
    def fixture(self, root, name="logs/test.stdout", corrupt=False, nonce="testnonce"):
        run = root / "results/test"
        run.mkdir(parents=True)
        (run / "preparation.json").write_text(json.dumps(dict(nonce="testnonce", remote_probe_sha256="sourcehash")))
        data = b"verified output\n"
        item = dict(bytes=len(data), sha256="wrong" if corrupt else hashlib.sha256(data).hexdigest(),
                    base64=base64.b64encode(data).decode("ascii"))
        result = dict(status="PASS", run_id="test", nonce=nonce, remote_probe_sha256="sourcehash", files={name: item})
        text = "banner\nU280_PROBE_BEGIN_testnonce\n" + json.dumps(result) + "\nU280_PROBE_END_testnonce\n"
        (run / "probe.stdout").write_text(text, encoding="utf-16")
        return run

    def test_windows_stdout_decodes_and_artifact_hash_matches(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = self.fixture(root)
            with patch.object(probe, "ROOT", root), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(probe.unpack("test"), 0)
            self.assertEqual((run / "returned/logs/test.stdout").read_bytes(), b"verified output\n")
            self.assertNotIn("base64", json.loads((run / "probe.json").read_text())["files"]["logs/test.stdout"])

    def test_returned_path_cannot_escape_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = self.fixture(root, "../../escape")
            with patch.object(probe, "ROOT", root), self.assertRaisesRegex(ValueError, "unsafe returned file"):
                probe.unpack("test")
            self.assertFalse((root / "results/escape").exists())
            self.assertFalse((run / "probe.json").exists())

    def test_digest_and_nonce_mismatches_are_rejected(self):
        for options, message in ((dict(corrupt=True), "digest mismatch"), (dict(nonce="another"), "identity mismatch")):
            with self.subTest(options=options), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                run = self.fixture(root, **options)
                with patch.object(probe, "ROOT", root), self.assertRaisesRegex(ValueError, message):
                    probe.unpack("test")
                self.assertFalse((run / "probe.json").exists())


if __name__ == "__main__":
    unittest.main()
