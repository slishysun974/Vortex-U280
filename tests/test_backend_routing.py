"""Check that the AFU-model entry point cannot select physical XRT hardware."""
import contextlib
import io
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_native_smoke as smoke


class BackendRoutingTests(unittest.TestCase):
    def test_xrtsim_forces_model_target_on_every_make_command(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = root / "result"
            result.mkdir()
            calls = []
            summary = {"demo_execution": "NOT_RUN"}

            def command(label, argv, cwd, timeout=30):
                calls.append((label, [str(arg) for arg in argv]))
                return {"returncode": 0, "timed_out": False}, "PASSED!\n" if label == "demo_run" else "-DVX_CFG_XLEN=64\n"

            def stage(source, build, dependencies, manifest_path=None):
                path = build / "third_party"
                path.mkdir()
                manifest_path.write_text("{}\n")
                return path

            recorder = SimpleNamespace(directory=result, summary=summary, command=command)
            args = SimpleNamespace(build_dir=root / "build", source=root / "source", tooldir=root / "tools",
                                   jobs=2, timeout=30, backend="xrtsim", ramulator_deps=root / "deps")
            with patch.object(smoke, "stage_third_party", side_effect=stage):
                passed, step = smoke.run_build(recorder, args, "-DVX_CFG_NUM_THREADS=4")
            self.assertTrue(passed)
            self.assertEqual(step, "demo_run")
            self.assertEqual(summary["demo_execution"], "PASS")
            make_calls = [(label, argv) for label, argv in calls if argv[0] == "make"]
            self.assertTrue(make_calls)
            for label, argv in make_calls:
                self.assertIn("TARGET=xrtsim", argv, label)
                self.assertNotIn("TARGET=hw", argv)
                self.assertNotIn("TARGET=hw_emu", argv)
            self.assertIn("runtime-xrt", dict(make_calls)["runtime_build"])
            self.assertIn("run-xrt", dict(make_calls)["demo_run"])
            self.assertEqual(summary["effective_backend_configuration"]["simulation_controls"],
                             ["NOXRT", "XRTSIM", "TARGET=xrtsim"])

    def test_ambiguous_xrt_backend_is_not_an_accepted_cli_option(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            smoke.main(["--backend", "xrt", "--tooldir", ".", "--check-only"])
        self.assertEqual(error.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
