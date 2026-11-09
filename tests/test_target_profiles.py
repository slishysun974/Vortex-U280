"""A valid hash chain must not allow the wrong hardware profile to run."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_native_smoke as smoke


class TargetProfileTests(unittest.TestCase):
    def test_profile_mismatch_is_blocked_even_with_consistent_hashes(self):
        for warps, accepted in ((8, True), (4, False)):
            with self.subTest(warps=warps), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                config_dir, target_id, defines = smoke.PROFILES["block32-v1"]
                config = root / config_dir
                config.mkdir(parents=True)
                source = root / "source"
                source.mkdir()
                (source / "VX_config.toml").write_text("fixed")
                (root / "source_manifest.json").write_text("[]")
                def write(name, data):
                    (config / name).write_text(json.dumps(data))
                write("native_smoke.json", dict(target_id=target_id, xlen=64, simx_mode="timing",
                      defines=dict(defines, VX_CFG_NUM_WARPS=warps),
                      source_config_sha256=smoke.sha256(source / "VX_config.toml")))
                write("target_lock.json", dict(target_id=target_id, xlen=64, vortex={"commit": smoke.COMMIT},
                      hardware_config_sha256=smoke.sha256(config / "native_smoke.json"), evidence=".",
                      source_manifest_sha256=smoke.sha256(root / "source_manifest.json")))
                write("target_caps.json", dict(target_id=target_id, xlen=64,
                      target_lock_hash=smoke.sha256(config / "target_lock.json")))
                run = root / "run"
                run.mkdir()
                summary = dict(target_profile="block32-v1", source={"path": str(source)},
                               preflight=[], blockers=[], config_file_sha256={})
                recorder = smoke.Recorder(run, summary, {})
                with patch.object(smoke, "PROJECT", root):
                    smoke.load_configuration(recorder)
                self.assertEqual(not summary["blockers"], accepted)
                if not accepted:
                    self.assertIn("fixed_target", summary["blockers"][0])


if __name__ == "__main__":
    unittest.main()
