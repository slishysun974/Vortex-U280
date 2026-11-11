from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from u280_board_smoke import verify_ptx_launch
import u280_board_smoke as board


class U280PtxDeviceLaunchTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.work = Path(directory.name)
        (self.work / "output").mkdir()

    def test_affine_preserves_unsigned_scalar_and_rejects_a_different_value(self):
        case = dict(id="0322", n=65, block=32, grid=3, words=81, alpha=0xffffffff)
        bundle = dict(cases=[case["id"]], ptx=dict(entry="affine_u32", image_sha256="example",
                      runtime_entry_pc=1234, case=case))
        (self.work / "output/0322_params.bin").write_bytes(struct.pack("<QQQII", 0x1020, 0x2020, 0x3020, 65, 0xffffffff))
        stdout = ("PTX_COPY_ENTRY 1234\nPTX_COPY_ARGS x=4128 y=8224 z=12320 n=65 alpha=4294967295\n"
                  "CAPTURED 0322 n=65 block=32 grid=3\n")
        result = {}
        verify_ptx_launch(self.work, bundle, result, stdout)
        self.assertEqual(result["ptx_launch"]["args"]["alpha"], 0xffffffff)
        with self.assertRaisesRegex(RuntimeError, "unexpected PTX scalar"):
            verify_ptx_launch(self.work, bundle, {}, stdout.replace("4294967295", "0"))

    def test_vadd_rejects_overlapping_guarded_buffers(self):
        case = dict(id="0106", n=65, block=32, grid=3, words=81)
        bundle = dict(cases=[case["id"]], ptx=dict(entry="vadd_u32", image_sha256="example",
                      runtime_entry_pc=1234, case=case))
        (self.work / "output/0106_params.bin").write_bytes(struct.pack("<QQQI4x", 0x1020, 0x1060, 0x2020, 65))
        stdout = ("PTX_COPY_ENTRY 1234\nPTX_COPY_ARGS x=4128 y=4192 z=8224 n=65\n"
                  "CAPTURED 0106 n=65 block=32 grid=3\n")
        with self.assertRaisesRegex(RuntimeError, "overlapping PTX buffers"):
            verify_ptx_launch(self.work, bundle, {}, stdout)


class U280PtxSuiteTests(unittest.TestCase):
    def setUp(self):
        self.bdf = "0000:b1:00.1"
        self.suite = dict(run_id="suite", nonce="nonce", mode="ptx-suite",
                          jobs=[dict(ptx=dict(source_run=source, entry=entry, case=dict(id=case)))
                                for source, entry, case in board.PTX_SUITE])
        self.success = dict(status="PASS", selected_bdf=self.bdf,
                            sysfs=dict(after=dict(kdsstat="outstanding execs: 0\ncontexts: 0\nclient pid:\n")))

    def test_runs_in_order_and_pins_the_card_after_first_case(self):
        with patch.object(board, "remote", return_value=self.success) as remote:
            result = board.remote_ptx_suite(self.suite)
        self.assertEqual([call.args[0]["pinned_bdf"] for call in remote.call_args_list], [None, self.bdf, self.bdf])
        self.assertEqual([call.args[0]["run_id"] for call in remote.call_args_list],
                         ["suite-copy_u32", "suite-vadd_u32", "suite-affine_u32"])
        self.assertEqual((result["status"], result["passed_cases"]), ("PASS", 3))

    def test_preserves_partial_result_after_failure(self):
        with patch.object(board, "remote", side_effect=[self.success, dict(status="BLOCKED", error="busy")]) as remote:
            result = board.remote_ptx_suite(self.suite)
        self.assertEqual(remote.call_count, 2)
        self.assertEqual((result["status"], result["passed_cases"]), ("BLOCKED", 1))
        self.assertEqual(result["jobs"]["affine_u32"]["status"], "NOT_RUN")

    def test_stops_if_card_is_not_idle_after_a_case(self):
        busy = dict(self.success, sysfs=dict(after=dict(kdsstat="outstanding execs: 1\ncontexts: 0\nclient pid:\n")))
        with patch.object(board, "remote", return_value=busy) as remote:
            result = board.remote_ptx_suite(self.suite)
        self.assertEqual(remote.call_count, 1)
        self.assertEqual((result["status"], result["passed_cases"]), ("FAIL", 0))

    def regression(self):
        return dict(run_id="regression", nonce="nonce", mode="ptx-regression",
                    jobs=[dict(ptx=dict(source_run=source, entry=entry, case=dict(id=case)))
                          for source, entry, case in board.PTX_REGRESSION])

    def test_regression_keeps_repeated_entries_and_case_ids_distinct(self):
        with patch.object(board, "remote", return_value=self.success) as remote:
            result = board.remote_ptx_suite(self.regression())
        self.assertEqual((result["status"], result["passed_cases"], len(result["jobs"])), ("PASS", 15, 15))
        runs = [call.args[0]["run_id"] for call in remote.call_args_list]
        self.assertEqual(len(set(runs)), 15)
        self.assertIn("regression-copy_u32-0010", runs)
        self.assertIn("regression-vadd_u32-0010", runs)
        self.assertEqual([call.args[0]["pinned_bdf"] for call in remote.call_args_list], [None] + [self.bdf] * 14)

    def test_rejects_changed_case_order_before_open(self):
        suite = self.regression()
        suite["jobs"][0], suite["jobs"][1] = suite["jobs"][1], suite["jobs"][0]
        with patch.object(board, "remote") as remote:
            with self.assertRaisesRegex(RuntimeError, "job order"):
                board.remote_ptx_suite(suite)
        remote.assert_not_called()

    def test_regression_failure_preserves_completed_and_unrun_cases(self):
        with patch.object(board, "remote", side_effect=[self.success, dict(status="FAIL", error="capture mismatch")]) as remote:
            result = board.remote_ptx_suite(self.regression())
        self.assertEqual((remote.call_count, result["passed_cases"], result["status"]), (2, 1, "FAIL"))
        self.assertEqual(result["jobs"]["copy_u32-0010"]["status"], "PASS")
        self.assertEqual(result["jobs"]["copy_u32-0058"]["status"], "FAIL")
        self.assertEqual(sum(job["status"] == "NOT_RUN" for job in result["jobs"].values()), 13)

    def test_regression_stops_on_changed_card(self):
        changed = dict(self.success, selected_bdf="0000:b4:00.1")
        with patch.object(board, "remote", side_effect=[self.success, changed]) as remote:
            result = board.remote_ptx_suite(self.regression())
        self.assertEqual((remote.call_count, result["passed_cases"], result["status"]), (2, 1, "FAIL"))

    def boundaries(self):
        source = 'ptx-boundaries-test'
        plan = [(source, 'copy_u32', '{:04d}'.format(i)) for i in range(67)]
        jobs = [dict(ptx=dict(source_run=s, entry=e, case=dict(id=c))) for s, e, c in plan]
        return dict(run_id='boundaries', nonce='nonce', mode='ptx-boundaries',
                    source_run=source, boundary_plan=plan, jobs=jobs)

    def test_boundary_batch_pins_card_and_uses_unique_case_names(self):
        with patch.object(board, 'remote', return_value=self.success) as remote:
            result = board.remote_ptx_suite(self.boundaries())
        self.assertEqual((result['status'], result['passed_cases']), ('PASS', 67))
        self.assertEqual(len({c.args[0]['run_id'] for c in remote.call_args_list}), 67)
        self.assertEqual([c.args[0]['pinned_bdf'] for c in remote.call_args_list], [None] + [self.bdf] * 66)

    def test_boundary_rejects_duplicate_plan_before_board_access(self):
        bundle = self.boundaries()
        bundle['boundary_plan'][-1] = bundle['boundary_plan'][0]
        with patch.object(board, 'remote') as remote, self.assertRaisesRegex(RuntimeError, 'boundary plan'):
            board.remote_ptx_suite(bundle)
        remote.assert_not_called()

    def test_boundary_batch_retains_unrun_after_busy_card(self):
        with patch.object(board, 'remote', side_effect=[self.success, dict(status='BLOCKED', error='busy')]) as remote:
            result = board.remote_ptx_suite(self.boundaries())
        self.assertEqual((remote.call_count, result['status'], result['passed_cases']), (2, 'BLOCKED', 1))
        self.assertEqual(sum(j['status'] == 'NOT_RUN' for j in result['jobs'].values()), 65)
