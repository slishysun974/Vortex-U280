"""Evidence and extraction gates for server compilation; never opens a card."""
import ast
import base64
import copy
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from u280_remote_runtime import decode, unpack_archive, validate_result


class RemoteRuntimeTests(unittest.TestCase):
    def test_python36_syntax(self):
        ast.parse((ROOT / "scripts/u280_remote_runtime.py").read_text(), feature_version=(3, 6))

    def test_transfer_corruption_rejected(self):
        item = dict(base64=base64.b64encode(b"fixed").decode(), bytes=5,
                    sha256=hashlib.sha256(b"fixed").hexdigest())
        self.assertEqual(decode(item), b"fixed")
        for key, bad in (("bytes", 0), ("sha256", "0" * 64), ("base64", "@")):
            with self.assertRaises(ValueError):
                decode(dict(item, **{key: bad}))

    def test_archive_traversal_links_duplicates_and_collisions_rejected_before_writes(self):
        normal = "u280-runtime200-input/file"
        cases = [([name], False) for name in ("../out", "/out", "other/file",
                  "u280-runtime200-input/../out", "u280-runtime200-input/C:/out",
                  "u280-runtime200-input/a\\b", "u280-runtime200-input/a//b")]
        cases += [([normal, normal], False), ([normal, normal + "/child"], False), ([normal], True)]
        for names, symlink in cases:
            with self.subTest(names=names, symlink=symlink), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                archive = root / "input.tar.gz"
                with tarfile.open(archive, "w:gz") as tar:
                    for name in names:
                        member = tarfile.TarInfo(name)
                        if symlink:
                            member.type, member.linkname = tarfile.SYMTYPE, "/outside"
                            tar.addfile(member)
                        else:
                            member.size = 1
                            tar.addfile(member, io.BytesIO(b"x"))
                with self.assertRaises(ValueError):
                    unpack_archive(archive, root / "extracted")
                self.assertFalse((root / "extracted").exists())

    def test_real_package_and_existing_directory(self):
        archive = ROOT / "results/u280-runtime-prepare-20261109-v1/u280-runtime200-input.tar.gz"
        if not archive.is_file():
            self.skipTest("Archived runtime input is required")
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "input"
            source = unpack_archive(archive, target)
            manifest = json.loads((source / "manifest.json").read_text())
            self.assertEqual(len(manifest), 116)
            for item in manifest:
                self.assertEqual(hashlib.sha256((source / item["path"]).read_bytes()).hexdigest(), item["sha256"])
            with self.assertRaises(FileExistsError):
                unpack_archive(archive, target)

    def test_missing_library_or_failed_evidence_cannot_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "lib").mkdir()
            artifacts = []
            for name in ("libvortex.so", "libvortex-xrt.so"):
                (root / "lib" / name).write_bytes(b"fixture")
                artifacts.append(dict(path="lib/" + name, bytes=7, sha256=hashlib.sha256(b"fixture").hexdigest()))
            good = dict(status="PASS", exit_code=0, stub_only=False, xrt_backend="PASS", binding={"clock": 200},
                artifacts=artifacts, commands=[dict(label=l, exit_code=0, timed_out=False) for l in
                ("compiler", "glibc", "stub", "xrt", "ldd_libvortex", "ldd_libvortex-xrt")])
            validate_result(root, good, {"clock": 200})
            for key, value in (("artifacts", artifacts[:1]), ("commands", good["commands"][:3]),
                               ("stub_only", True), ("binding", {"clock": 400}), ("exit_code", 1)):
                with self.assertRaises(ValueError):
                    validate_result(root, dict(good, **{key: value}), {"clock": 200})
            failed = copy.deepcopy(good)
            failed["commands"][3]["exit_code"] = 2
            with self.assertRaises(ValueError):
                validate_result(root, failed, {"clock": 200})
            (root / "lib/libvortex-xrt.so").write_bytes(b"changed")
            with self.assertRaises(ValueError):
                validate_result(root, good, {"clock": 200})


if __name__ == "__main__":
    unittest.main()
