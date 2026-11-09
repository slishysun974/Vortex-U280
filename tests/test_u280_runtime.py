"""Runtime binding and input preservation gates; no device calls."""
import ast
import json
from pathlib import Path
import runpy
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from prepare_u280_runtime import check_binding, flag_map
BUILD = runpy.run_path(str(ROOT / "environment/u280-fpga/build_runtime.py"))


class RuntimeBindingTests(unittest.TestCase):
    def test_only_clock_metadata_may_change(self):
        flags = ROOT / "results/ab-d8-u280-source-20261109-v1/candidate_merged/resolved_config.cflags"
        if not flags.is_file():
            self.skipTest("Archived D8 configuration flags are required")
        original = flags.read_text()
        current = original.replace("-DVX_CFG_PLATFORM_CLOCK_RATE=400", "-DVX_CFG_PLATFORM_CLOCK_RATE=200")
        self.assertEqual(check_binding(original, current), {"VX_CFG_PLATFORM_CLOCK_RATE": ["400", "200"]})
        for bad in (original, current.replace("-DVX_CFG_NUM_WARPS=8", "-DVX_CFG_NUM_WARPS=4"),
                    current.replace("-DVX_CFG_PLATFORM_MEMORY_ADDR_WIDTH=33", "-DVX_CFG_PLATFORM_MEMORY_ADDR_WIDTH=48")):
            with self.assertRaises(ValueError):
                check_binding(original, bad)

    def test_conflicting_or_non_define_flags_rejected(self):
        for bad in ("-DX=1 -DX=2", "-DX=1 -include /tmp/injected.h"):
            with self.assertRaises(ValueError):
                flag_map(bad)

    def test_remote_builder_python36_syntax(self):
        ast.parse((ROOT / "environment/u280-fpga/build_runtime.py").read_text(), feature_version=(3, 6))

    def test_unsafe_manifest_paths_rejected_without_writes(self):
        for name in ("../outside", "/absolute", "C:/outside", "bad\\path", "dir//file"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                data = json.dumps([dict(path=name, bytes=1, sha256="0" * 64)])
                (root / "manifest.json").write_text(data)
                with self.assertRaises(ValueError):
                    BUILD["validate"](root)
                self.assertEqual((root / "manifest.json").read_text(), data)
                self.assertEqual(len(list(root.iterdir())), 1)


if __name__ == "__main__":
    unittest.main()
