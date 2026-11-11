"""Safety checks for the runner; these are not Vortex kernel acceptance tests."""

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/run_native_smoke.py"
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("run_native_smoke", SCRIPT)
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)


class RunnerSafetyTests(unittest.TestCase):
    def test_pass_requires_exact_marker_zero_exit_and_no_timeout(self):
        self.assertTrue(smoke.demo_passed(0, False, "verify result\nPASSED!\n"))
        for code, timed_out, text in (
            (1, False, "PASSED!\n"), (0, True, "PASSED!\n"),
            (0, False, "NOT PASSED!\n"), (0, False, "PASSED! not really\n"),
            (0, False, "build completed\n"),
        ):
            with self.subTest(code=code, timed_out=timed_out, text=text):
                self.assertFalse(smoke.demo_passed(code, timed_out, text))

    def test_unsafe_make_paths_rejected(self):
        self.assertTrue(smoke.safe_build_path("/mnt/d/Vortex-U280"))
        for path in ("/tmp/with space", "/tmp/$HOME", "/tmp/a'b", "/tmp/a|b", "/tmp/a\nb"):
            self.assertFalse(smoke.safe_build_path(path), path)

    def test_existing_run_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp) / "existing"
            run.mkdir()
            (run / "sentinel").write_text("keep")
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                smoke.main(["--tooldir", str(Path(temp) / "tools"), "--results-dir", temp,
                            "--run-id", "existing", "--check-only"])
            self.assertEqual(error.exception.code, 2)
            self.assertEqual((run / "sentinel").read_text(), "keep")

    def test_run_id_cannot_escape_results(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            smoke.main(["--tooldir", ".", "--run-id", "../escape", "--check-only"])
        self.assertEqual(error.exception.code, 2)

    def test_build_directory_cannot_pollute_source_or_tools(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for label in ("source", "tools"):
                with self.subTest(tree=label), contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as error:
                        smoke.main(["--source", str(root / "source"), "--tooldir", str(root / "tools"),
                                    "--build-dir", str(root / label / "build"), "--results-dir", str(root / "results"),
                                    "--run-id", "isolation", "--check-only"])
                    self.assertEqual(error.exception.code, 2)
                    self.assertFalse((root / "results/isolation").exists())

    def test_command_failure_preserves_raw_output_and_code(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            summary = {"commands": []}
            recorder = smoke.Recorder(directory, summary, dict(os.environ))
            record, output = recorder.command("deliberate_failure", [sys.executable, "-c",
                "import sys; print('failure evidence'); sys.exit(7)"], directory)
            self.assertEqual(record["returncode"], 7)
            self.assertIn("failure evidence", output)
            self.assertEqual(record["log_sha256"], smoke.sha256(directory / record["log"]))
            self.assertEqual(json.loads((directory / "summary.json").read_text())["commands"][0]["returncode"], 7)

    def test_spooled_failure_preserves_exact_bytes_and_exit_code(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            scratch = directory / 'scratch'
            scratch.mkdir()
            recorder = smoke.Recorder(directory, {"commands": []}, dict(os.environ), scratch_logs=scratch)
            record, _ = recorder.command('spooled_failure', [sys.executable, '-c',
                "import os; os.write(1,b'raw\\x00\\xff\\r\\n'); os.write(2,b'error\\n'); raise SystemExit(7)"], directory)
            self.assertEqual(record['returncode'], 7)
            self.assertEqual((directory / record['log']).read_bytes(), b'raw\x00\xff\r\nerror\n')
            self.assertEqual(record['log_sha256'], smoke.sha256(Path(record['scratch_log'])))

    def test_spooled_timeout_keeps_partial_output(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            scratch = directory / 'scratch'
            scratch.mkdir()
            recorder = smoke.Recorder(directory, {"commands": []}, dict(os.environ), scratch_logs=scratch)
            record, output = recorder.command('spooled_timeout', [sys.executable, '-c',
                "import time; print('partial evidence',flush=True); time.sleep(60)"], directory, timeout=1)
            self.assertTrue(record['timed_out'])
            self.assertNotEqual(record['returncode'], 0)
            self.assertIn('partial evidence', output)
            self.assertEqual(record['log_sha256'], smoke.sha256(directory / record['log']))

    @unittest.skipUnless(os.name == "posix", "Linux process-group test")
    def test_timeout_kills_child_process_group(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            recorder = smoke.Recorder(directory, {"commands": []}, dict(os.environ))
            program = ("import subprocess,sys,time; "
                       "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
                       "print(p.pid,flush=True); time.sleep(60)")
            record, output = recorder.command("timeout_child", [sys.executable, "-c", program], directory, timeout=1)
            self.assertTrue(record["timed_out"])
            self.assertNotEqual(record["returncode"], 0)
            child_stat = Path("/proc") / output.strip() / "stat"
            if child_stat.exists():
                self.assertEqual(child_stat.read_text().split()[2], "Z")

    @unittest.skipIf(sys.platform == "linux", "Windows negative preflight")
    def test_check_only_wrong_platform_is_blocked_never_pass(self):
        with tempfile.TemporaryDirectory() as temp, contextlib.redirect_stdout(io.StringIO()):
            code = smoke.main(["--tooldir", str(Path(temp) / "tools"), "--results-dir", temp,
                               "--run-id", "platform-negative", "--check-only"])
            result = json.loads((Path(temp) / "platform-negative/summary.json").read_text(encoding="utf-8"))
            self.assertEqual(code, 2)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertEqual(result["upstream_smoke"], "NOT_RUN")
            self.assertEqual(result["p0_three_kernels"], "NOT_RUN")
            self.assertFalse((Path(temp) / "platform-negative/build").exists())


if __name__ == "__main__":
    unittest.main()
