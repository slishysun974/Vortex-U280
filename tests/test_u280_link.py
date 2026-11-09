"""Detached controller tests only; none invoke FPGA tools or claim hardware PASS."""
import ast
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import u280_remote_link as link


class LinkControllerTests(unittest.TestCase):
    def test_resource_gate_requires_both_budgets(self):
        memory = "MemAvailable:       67108864 kB\n"
        self.assertTrue(link.resource_gate(memory, 50 * 1024 ** 3)["pass_minimums"])
        for mem, disk in ((memory, 50 * 1024 ** 3 - 1),
                          ("MemAvailable: 67108863 kB\n", 50 * 1024 ** 3),
                          ("MemFree: 999999999 kB\n", 50 * 1024 ** 3)):
            self.assertFalse(link.resource_gate(mem, disk)["pass_minimums"])

    def test_remote_python36_syntax(self):
        ast.parse((ROOT / "scripts/u280_remote_link.py").read_text(encoding="utf-8"), feature_version=(3, 6))
        ast.parse(link.WORKER, feature_version=(3, 6))

    @unittest.skipUnless(sys.platform == "linux", "Linux flock/account semantics")
    def test_existing_run_is_never_rewritten(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            job = base / "vortex-u280-link-jobs/build1"
            job.mkdir(parents=True)
            evidence = job / "launch.json"
            original = b'{"status":"FAIL","original":true}\n'
            evidence.write_bytes(original)
            with mock.patch("pwd.getpwuid", return_value=SimpleNamespace(pw_name="u280user", pw_dir=folder)):
                with self.assertRaisesRegex(ValueError, "already exists"):
                    link.collect(dict(run_id="capture1", build_run="build1", xo_run="xo1",
                                      nonce="test", mode="start", authorized=True))
            self.assertEqual(evidence.read_bytes(), original)

    @unittest.skipUnless(sys.platform == "linux", "Linux flock/account semantics")
    def test_changed_builder_stops_before_build_and_records_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            inputs = base / "vortex-u280-probes/xo1"
            inputs.mkdir(parents=True)
            (inputs / "build_prepared.py").write_text("raise RuntimeError('must never execute')")
            with mock.patch("pwd.getpwuid", return_value=SimpleNamespace(pw_name="u280user", pw_dir=folder)):
                result = link.collect(dict(run_id="build1", build_run="build1", xo_run="xo1",
                                          nonce="test", mode="start", authorized=True, builder_sha256="0" * 64))
            self.assertEqual(result["status"], "FAIL")
            self.assertEqual(result["build_status"], "NOT_RUN")
            self.assertIn("builder identity", result["error"])
            self.assertFalse((base / "vortex-u280-builds/build1").exists())
            self.assertEqual(json.loads((base / "vortex-u280-link-jobs/build1/launch.json").read_text())["status"], "FAIL")

    @unittest.skipUnless(sys.platform == "linux", "Linux detached process and flock semantics")
    def test_worker_retains_lock_and_reports_actual_exit(self):
        import fcntl
        for code, build_status, expected in ((0, "PASS", "PASS"), (1, "FAIL", "FAIL"), (0, "FAIL", "FAIL")):
            with self.subTest(code=code, build_status=build_status), tempfile.TemporaryDirectory() as folder:
                job = Path(folder)
                build = job / "build"
                build.mkdir()
                (build / "result.json").write_text(json.dumps(dict(status=build_status)))
                (job / "worker.py").write_text(link.WORKER)
                command = [sys.executable, "-B", "-c",
                           "import time,pathlib,sys\np=pathlib.Path('release')\nwhile not p.exists(): time.sleep(0.02)\nsys.exit(%d)" % code]
                (job / "request.json").write_text(json.dumps(dict(argv=command, build_directory=str(build))))
                lock = (job / "active.lock").open("a+")
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                worker = subprocess.Popen([sys.executable, "-B", str(job / "worker.py"), str(job), str(lock.fileno())],
                                          cwd=str(job), start_new_session=True, pass_fds=(lock.fileno(),))
                lock.close()
                try:
                    deadline = time.monotonic() + 10
                    while not (job / "worker.json").exists() and time.monotonic() < deadline:
                        time.sleep(0.02)
                    self.assertEqual(json.loads((job / "worker.json").read_text())["status"], "RUNNING")
                    with (job / "active.lock").open("a+") as other:
                        with self.assertRaises(BlockingIOError):
                            fcntl.flock(other.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    (job / "release").touch()
                    worker.wait(timeout=10)
                    state = json.loads((job / "worker.json").read_text())
                    self.assertEqual(state["status"], expected)
                    self.assertEqual(state["exit_code"], code)
                    with (job / "active.lock").open("a+") as other:
                        fcntl.flock(other.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                finally:
                    (job / "release").touch()
                    worker.wait(timeout=10)

    @unittest.skipUnless(sys.platform == "linux", "Linux account semantics")
    def test_status_never_starts_unknown_job(self):
        with tempfile.TemporaryDirectory() as folder:
            with mock.patch("pwd.getpwuid", return_value=SimpleNamespace(pw_name="u280user", pw_dir=folder)):
                with self.assertRaisesRegex(ValueError, "unknown job"):
                    link.collect(dict(run_id="capture1", build_run="build1", xo_run="xo1", nonce="test", mode="status"))
            self.assertFalse((Path(folder) / "vortex-u280-builds").exists())


if __name__ == "__main__":
    unittest.main()
