"""Artifact identity gates; these tests do not execute vendor tools or hardware."""
import ast
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import tarfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import u280_remote_archive as archive
from unpack_u280_reports import unpack


class ArchiveTests(unittest.TestCase):
    def test_compressed_reports_roundtrip_and_reject_tampering(self):
        for bad in (False, True):
            with self.subTest(tampered=bad), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                data = b"timing report\n" * 1000
                manifest = [dict(path="link/imp/timing.rpt", bytes=len(data), sha256=hashlib.sha256(data).hexdigest())]
                if bad:
                    manifest[0]["sha256"] = "0" * 64
                with tarfile.open(root / "reports.tar.gz", "w:gz") as tar:
                    member = tarfile.TarInfo(manifest[0]["path"])
                    member.size = len(data)
                    tar.addfile(member, io.BytesIO(data))
                if bad:
                    with self.assertRaisesRegex(ValueError, "hash mismatch"):
                        unpack(root / "reports.tar.gz", manifest, root / "out")
                else:
                    self.assertEqual(unpack(root / "reports.tar.gz", manifest, root / "out"), 1)
                    self.assertEqual((root / "out/link/imp/timing.rpt").read_bytes(), data)
                    with self.assertRaises(FileExistsError):
                        unpack(root / "reports.tar.gz", manifest, root / "out")

    def test_report_escape_duplicate_and_symlink_rejected(self):
        for name, symlink in (("../escape", False), ("link.rpt", True)):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                manifest = [dict(path=name, bytes=0, sha256=hashlib.sha256(b"").hexdigest())]
                with tarfile.open(root / "reports.tar.gz", "w:gz") as tar:
                    member = tarfile.TarInfo(name)
                    if symlink:
                        member.type = tarfile.SYMTYPE
                        member.linkname = "../escape"
                    tar.addfile(member, io.BytesIO(b""))
                with self.assertRaises(ValueError):
                    unpack(root / "reports.tar.gz", manifest, root / "out")
                self.assertFalse((root / "out").exists())
                with self.assertRaises(ValueError):
                    unpack(root / "reports.tar.gz", manifest * 2, root / "out")

    def fixture(self, root):
        (root / "out").mkdir()
        data = b"test xclbin bytes"
        (root / "out/vortex_afu.xclbin").write_bytes(data)
        artifact = dict(path="out/vortex_afu.xclbin", bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
        (root / "result.json").write_text(json.dumps(dict(status="PASS", exit_code=0, stage="link", artifact=artifact)))
        return dict(accepted_result_sha256=archive.digest(root / "result.json"), artifact=artifact)

    def test_python36_syntax(self):
        ast.parse((ROOT / "scripts/u280_remote_archive.py").read_text(), feature_version=(3, 6))

    def test_changed_artifact_rejected_and_original_record_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            bundle = self.fixture(root)
            before = (root / "result.json").read_bytes()
            self.assertEqual(archive.validate_build(root, bundle), root / "out/vortex_afu.xclbin")
            (root / "out/vortex_afu.xclbin").write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "xclbin identity"):
                archive.validate_build(root, bundle)
            self.assertEqual((root / "result.json").read_bytes(), before)

    def test_changed_result_and_failed_build_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            bundle = self.fixture(root)
            path = root / "result.json"
            result = json.loads(path.read_text())
            result["status"] = "FAIL"
            path.write_text(json.dumps(result))
            with self.assertRaisesRegex(ValueError, "result changed"):
                archive.validate_build(root, bundle)
            bundle["accepted_result_sha256"] = archive.digest(path)
            with self.assertRaisesRegex(ValueError, "successful link"):
                archive.validate_build(root, bundle)

    @unittest.skipUnless(sys.platform == "linux", "symlink semantics")
    def test_symlink_escape_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            bundle = self.fixture(root)
            source = root / "out/vortex_afu.xclbin"
            source.rename(root / "external")
            source.symlink_to(root / "external")
            with self.assertRaisesRegex(ValueError, "symlink"):
                archive.validate_build(root, bundle)


if __name__ == "__main__":
    unittest.main()
