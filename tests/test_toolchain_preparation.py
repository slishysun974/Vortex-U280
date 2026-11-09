"""Archive integrity checks for the installer, without compiling Vortex."""

import io
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import prepare_toolchain as preparation
import run_native_smoke as smoke


class ToolchainProfileTests(unittest.TestCase):
    def manifest(self, profile):
        return {"schema_version": "vortex-toolchain-cache-v1", "repository": preparation.REPOSITORY,
                "commit": smoke.TOOLCHAIN_COMMIT, "osversion": "ubuntu/focal", "profile": profile,
                "components": dict.fromkeys(preparation.PROFILES[profile], {})}

    def test_rtlsim_requires_verilator_in_the_fixed_profile(self):
        manifest = self.manifest("rtlsim")
        self.assertIn("verilator", preparation.cache_components(manifest))
        del manifest["components"]["verilator"]
        with self.assertRaisesRegex(ValueError, "component profile"):
            preparation.cache_components(manifest)

    def test_wrong_revision_or_unknown_component_is_rejected(self):
        manifest = self.manifest("simx")
        manifest["commit"] = "0" * 40
        with self.assertRaises(ValueError):
            preparation.cache_components(manifest)
        manifest = self.manifest("rtlsim")
        manifest["components"]["unrequested"] = {}
        with self.assertRaises(ValueError):
            preparation.cache_components(manifest)

    def test_preserved_d2_simx_cache_is_still_readable(self):
        manifest = self.manifest("simx")
        del manifest["profile"]
        self.assertEqual(set(preparation.cache_components(manifest)), set(preparation.COMPONENTS))


@unittest.skipUnless(sys.platform == "linux", "Linux tool extraction")
class ToolchainPreparationTests(unittest.TestCase):
    def archive(self, directory, name="llvm-vortex/bin/tool", link=None):
        archive = directory / "llvm-vortex.tar.bz2"
        with tarfile.open(str(archive), "w:bz2") as stream:
            member = tarfile.TarInfo(name)
            if link is not None:
                member.type = tarfile.SYMTYPE
                member.linkname = link
                stream.addfile(member)
            else:
                content = b"synthetic test data"
                member.size = len(content)
                stream.addfile(member, io.BytesIO(content))
        return {"components": {"llvm-vortex": {"archive": archive.name,
                                                "archive_sha256": smoke.sha256(archive)}}}

    def test_hash_failure_never_extracts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = self.archive(root)
            manifest["components"]["llvm-vortex"]["archive_sha256"] = "0" * 64
            recorder = smoke.Recorder(root, {"commands": []}, dict(os.environ))
            with self.assertRaisesRegex(ValueError, "archive hash differs"):
                preparation.extract_archives(recorder, manifest, root)
            self.assertEqual(recorder.summary["commands"], [])

    def test_escaping_member_and_symlink_never_extract(self):
        for name, link in (("llvm-vortex/../../escape", None),
                           ("llvm-vortex/bin/tool", "../../../escape")):
            with self.subTest(name=name, link=link), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                manifest = self.archive(root, name=name, link=link)
                recorder = smoke.Recorder(root, {"commands": []}, dict(os.environ))
                with self.assertRaisesRegex(ValueError, "unsafe archive member|link leaves its component"):
                    preparation.extract_archives(recorder, manifest, root)
                self.assertEqual(recorder.summary["commands"], [])

    def test_valid_archive_extracts_and_records_command(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = self.archive(root)
            recorder = smoke.Recorder(root, {"commands": []}, dict(os.environ))
            tools = preparation.extract_archives(recorder, manifest, root)
            self.assertEqual((tools / "llvm-vortex/bin/tool").read_bytes(), b"synthetic test data")
            recorded = json.loads((root / "summary.json").read_text())
            self.assertEqual(recorded["commands"][0]["returncode"], 0)

    def test_existing_tool_directory_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = self.archive(root)
            existing = root / "existing-tools"
            existing.mkdir()
            (existing / "sentinel").write_text("keep")
            recorder = smoke.Recorder(root, {"commands": []}, dict(os.environ))
            with self.assertRaises(FileExistsError):
                preparation.extract_archives(recorder, manifest, root, existing)
            self.assertEqual((existing / "sentinel").read_text(), "keep")
            self.assertEqual(recorder.summary["commands"], [])


if __name__ == "__main__":
    unittest.main()
