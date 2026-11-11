"""Adversarial checks of sequence evidence; these tests are not DUT execution."""
import ast
import hashlib
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from ptx_sequence_contract import verify_capture
from ptx_sequence_trace import bind_rtl_dispatches
import u280_board_smoke as board


class PtxSequenceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.work = Path(temp.name)
        self.output = self.work / 'output'
        self.output.mkdir()
        fields = [dict(name=name, size=size, offset=offset) for name, size, offset in
                  (('x', 8, 0), ('z', 8, 8), ('n', 4, 16))]
        self.contract = dict(buffer_bytes=64, abi={'copy_u32': dict(size=24, fields=fields)},
                             cases=[dict(id='0000', entry='copy_u32', pc=6442450996, n=0, block=32,
                                         grid=1, generation=1, reject=True)], expected={})
        for name in ('x', 'y', 'z', 'reject_x', 'reject_y', 'reject_z'):
            data = bytes(range(64))
            fname = '0000_' + name + '.bin'
            (self.output / fname).write_bytes(data)
            self.contract['expected'][fname] = hashlib.sha256(data).hexdigest()
        (self.output / '0000_params.bin').write_bytes(struct.pack('<QQI4x', 4128, 12320, 0))
        self.stdout = ('SEQUENCE_DEVICE_OPEN 1\nSEQUENCE_BUFFERS generation=1 x=4128 y=8224 z=12320\n'
                       'SEQUENCE_BEGIN 0000\nSEQUENCE_MODULE 0000 entry=copy_u32\n'
                       'SEQUENCE_REJECT 0000 block=33 rc=3 event_null=1\n'
                       'SEQUENCE_REJECT 0000 block=64 rc=3 event_null=1\n'
                       'SEQUENCE_LAUNCH 0000 entry=copy_u32 pc=6442450996 n=0 block=32 grid=1 generation=1\n'
                       'CAPTURED 0000 n=0 block=32 grid=1\nSEQUENCE_END 0000\n'
                       'SEQUENCE_DEVICE_CLOSE 1\nCAPTURE_COMPLETE 1\n')

    def test_positive_and_board_capture_adapter(self):
        result = verify_capture(self.contract, self.stdout, self.output)
        self.assertEqual((result['launches'], result['rejected_launches'], result['checked_files']), (1, 2, 7))
        bundle = dict(sequence=self.contract, cases=['0000'], expected=self.contract['expected'])
        out = dict(outputs={}, case_results={})
        board.compare_outputs(self.work, bundle, out, self.stdout)
        self.assertEqual((out['passed_cases'], out['unexpected_outputs']), (1, []))

    def test_rejects_stale_output_and_modified_rejection_snapshot(self):
        for name in ('0000_z.bin', '0000_reject_x.bin'):
            path = self.output / name
            original = path.read_bytes()
            path.write_bytes(b'X' + original[1:])
            with self.assertRaisesRegex(RuntimeError, 'captured bytes differ'):
                verify_capture(self.contract, self.stdout, self.output)
            path.write_bytes(original)

    def test_rejects_parameter_padding_change(self):
        path = self.output / '0000_params.bin'
        path.write_bytes(path.read_bytes()[:-1] + b'X')
        with self.assertRaisesRegex(RuntimeError, 'parameter bytes mismatch'):
            verify_capture(self.contract, self.stdout, self.output)

    def test_rejects_overlap_missing_completion_and_extra_open(self):
        for text, message in (
            (self.stdout.replace('y=8224', 'y=4160'), 'overlapping'),
            (self.stdout.replace('SEQUENCE_END 0000\n', ''), 'partial'),
            ('SEQUENCE_DEVICE_OPEN 1\n' + self.stdout, 'exactly one'),
            (self.stdout.replace('SEQUENCE_MODULE 0000 entry=copy_u32', 'SEQUENCE_MODULE 0000 entry=vadd_u32'), 'module reload')):
            with self.subTest(message=message), self.assertRaisesRegex(RuntimeError, message):
                verify_capture(self.contract, text, self.output)

    def test_rejects_success_or_event_from_invalid_launch(self):
        for change in ('rc=0 event_null=1', 'rc=3 event_null=0'):
            with self.subTest(change=change), self.assertRaisesRegex(RuntimeError, 'rejection mismatch'):
                verify_capture(self.contract, self.stdout.replace('rc=3 event_null=1', change, 1), self.output)

    def test_partial_board_capture_remains_not_run(self):
        bundle = dict(sequence=self.contract, cases=['0000'], expected=self.contract['expected'])
        result = dict(outputs={}, case_results={})
        board.compare_outputs(self.work, bundle, result, '')
        self.assertEqual((result['passed_cases'], result['case_results']['0000']), (0, 'NOT_RUN'))

    def test_remote_sequence_checker_keeps_python36_compatibility(self):
        script = Path(__file__).resolve().parents[1] / 'scripts/ptx_sequence_contract.py'
        ast.parse(script.read_text(), feature_version=(3, 6))

    def test_extra_or_missing_output_is_rejected(self):
        path = self.output / 'unplanned.bin'
        path.write_bytes(b'not part of this launch')
        with self.assertRaisesRegex(RuntimeError, 'file set mismatch'):
            verify_capture(self.contract, self.stdout, self.output)
        path.unlink()
        (self.output / '0000_y.bin').unlink()
        with self.assertRaisesRegex(RuntimeError, 'file set mismatch'):
            verify_capture(self.contract, self.stdout, self.output)


class SequenceCtaBindingTests(unittest.TestCase):
    RAW = ('2867: kmu cta-fire: cta_id=0, block_idx=[0,0,0], PC=0x180000000, param=0x11000, aligned_lmem_size=0\n'
           '2867: cluster0-socket0-core0-scheduler-cta_dispatch kmu-accept: cta_id=41, PC=0x180000000, param=0x11000, stride=0\n'
           '3311: lsu0 Wr Req: cta_id=41, PC=0x180000038\n')

    def test_binds_observed_internal_id_without_assuming_reset(self):
        normalized, binding = bind_rtl_dispatches(self.RAW, 1)
        self.assertEqual(binding, [dict(cycle=2867, kmu_cta=0, core_cta=41, block=0)])
        self.assertIn('kmu cta-fire: cta_id=41', normalized)
        self.assertIn('lsu0 Wr Req: cta_id=41', normalized)

    def test_rejects_missing_duplicate_or_wrong_cycle_and_payload(self):
        for raw in (self.RAW.splitlines()[0], self.RAW + self.RAW,
                    self.RAW.replace('2867: cluster0', '2868: cluster0'),
                    self.RAW.replace('param=0x11000, stride', 'param=0x12000, stride')):
            with self.subTest(raw=raw), self.assertRaises(RuntimeError):
                bind_rtl_dispatches(raw, 1)


if __name__ == '__main__':
    unittest.main()
