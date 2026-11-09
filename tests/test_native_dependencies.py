"""Dependency integrity and staging tests; no Vortex execution evidence."""

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import native_dependencies as dependencies
import run_native_smoke as smoke


def fixture(root):
    bundle = {"schema_version": "ramulator-dependencies-v1",
              "ramulator_commit": dependencies.RAMULATOR_COMMIT, "dependencies": {}}
    for name, pin in dependencies.DEPENDENCIES.items():
        directory = root / name
        (directory / "include").mkdir(parents=True)
        (directory / "CMakeLists.txt").write_text("# test fixture\n", encoding="utf-8")
        (directory / "include/header.h").write_text("// test fixture\n", encoding="utf-8")
        bundle["dependencies"][name] = dict(pin, files=dependencies.source_manifest(directory))
    (root / "bundle.json").write_text(json.dumps(bundle), encoding="utf-8")
    return bundle


class NativeDependencyTests(unittest.TestCase):
    def test_changed_added_or_missing_source_is_rejected(self):
        for mutation in ("changed", "added", "missing"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                fixture(root)
                dependencies.validate_bundle(root)
                header = root / "yaml-cpp/include/header.h"
                if mutation == "changed":
                    header.write_text("changed", encoding="utf-8")
                elif mutation == "added":
                    (header.parent / "unexpected.h").write_text("extra", encoding="utf-8")
                else:
                    header.unlink()
                with self.assertRaisesRegex(ValueError, "file hashes differ"):
                    dependencies.validate_bundle(root)

    def test_wrong_commit_or_dependency_set_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bundle = fixture(root)
            altered = copy.deepcopy(bundle)
            altered["dependencies"]["spdlog"]["commit"] = "0" * 40
            (root / "bundle.json").write_text(json.dumps(altered), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "identity differs"):
                dependencies.validate_bundle(root)
            del bundle["dependencies"]["argparse"]
            (root / "bundle.json").write_text(json.dumps(bundle), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "schema or Ramulator identity"):
                dependencies.validate_bundle(root)

    def test_staging_preserves_source_and_dependency_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            third_party = source / "third_party"
            (third_party / "ramulator/ext").mkdir(parents=True)
            (third_party / "ramulator/build").mkdir()
            (third_party / "ramulator/build/stale").write_text("old build")
            (third_party / "ramulator/ext/unpinned").write_text("ignore source ext")
            (third_party / "ramulator/CMakeLists.txt").write_text("# fixture")
            (third_party / "softfloat/build/Linux-x86_64-GCC").mkdir(parents=True)
            (third_party / "softfloat/build/Linux-x86_64-GCC/Makefile").write_text("# keep build recipe")
            (third_party / "Makefile").write_text("# fixture")
            cache = root / "cache"
            fixture(cache)
            (cache / "yaml-cpp/.git").mkdir()
            (cache / "yaml-cpp/.git/config").write_text("Git metadata")
            source_before = dependencies.source_manifest(source)
            cache_before = dependencies.source_manifest(cache)
            build = root / "run/build"
            build.mkdir(parents=True)
            staged = smoke.stage_third_party(source, build, cache)
            self.assertEqual(source_before, dependencies.source_manifest(source))
            self.assertEqual(cache_before, dependencies.source_manifest(cache))
            self.assertFalse((staged / "ramulator/build").exists())
            self.assertFalse((staged / "ramulator/ext/unpinned").exists())
            self.assertFalse((staged / "ramulator/ext/yaml-cpp/.git").exists())
            self.assertTrue((staged / "softfloat/build/Linux-x86_64-GCC/Makefile").is_file())
            for name in dependencies.DEPENDENCIES:
                self.assertEqual(dependencies.source_manifest(cache / name),
                                 dependencies.source_manifest(staged / "ramulator/ext" / name))
            self.assertTrue((build.parent / "third_party_sources.json").is_file())

    def test_staging_rejects_tampering_before_creating_build_sources(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cache = root / "cache"
            fixture(cache)
            (cache / "argparse/include/header.h").write_text("tampered")
            build = root / "build"
            build.mkdir()
            with self.assertRaisesRegex(ValueError, "file hashes differ"):
                smoke.stage_third_party(root / "source", build, cache)
            self.assertFalse((build / "third_party").exists())


if __name__ == "__main__":
    unittest.main()
