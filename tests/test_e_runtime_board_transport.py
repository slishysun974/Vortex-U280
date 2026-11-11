"""Board transport failure gates only; no SSH, XRT or device operations."""
import ast
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import e_runtime_board as board


class TransportGates(unittest.TestCase):
    def bundle(self):
        return dict(run_id='e-u280-unseen-test',nonce='unit-test',bdf='0000:b1:00.1',
                    files={},module_names=['copy'],runtime_hashes={})

    def test_host_validation_failure_stops_before_xrt(self):
        with tempfile.TemporaryDirectory() as temp, mock.patch.object(Path,'home',return_value=Path(temp)), \
                mock.patch.object(board.shutil,'which',return_value=sys.executable), \
                mock.patch.object(board.subprocess,'run') as run:
            run.side_effect=[subprocess.CompletedProcess([],0,b'[3,6,8]',b''),
                             subprocess.CompletedProcess([],1,b'',b'invalid module')]
            result=board.remote(self.bundle())
            self.assertEqual(result['status'],'FAIL')
            self.assertEqual(result['board_execution'],'NOT_RUN')
            self.assertEqual([c['label'] for c in result['commands']],['python_version','validate_copy'])
            self.assertEqual(run.call_count,2)

    def test_module_validation_timeout_stops_before_xrt(self):
        with tempfile.TemporaryDirectory() as temp, mock.patch.object(Path,'home',return_value=Path(temp)), \
                mock.patch.object(board.shutil,'which',return_value=sys.executable), \
                mock.patch.object(board.subprocess,'run') as run:
            run.side_effect=[subprocess.CompletedProcess([],0,b'[3,6,8]',b''),
                             subprocess.TimeoutExpired(['module-validation'],30)]
            result=board.remote(self.bundle())
            self.assertTrue(result['commands'][-1]['timed_out'])
            self.assertEqual(result['board_execution'],'NOT_RUN')
            self.assertEqual(run.call_count,2)

    def test_existing_remote_run_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temp, mock.patch.object(Path,'home',return_value=Path(temp)), \
                mock.patch.object(board.subprocess,'run') as run:
            work=Path(temp)/'vortex-e-runtime/e-u280-unseen-test'
            work.mkdir(parents=True);(work/'original.txt').write_bytes(b'original')
            result=board.remote(self.bundle())
            self.assertEqual(result['status'],'FAIL')
            self.assertEqual((work/'original.txt').read_bytes(),b'original')
            run.assert_not_called()

    def test_receiver_refuses_wrong_identity(self):
        with tempfile.TemporaryDirectory() as temp, mock.patch.object(board,'ROOT',Path(temp)):
            run=Path(temp)/'results/e-u280-unseen-test';run.mkdir(parents=True)
            prep=dict(run_id=run.name,nonce='abc',bdf='0000:b1:00.1',script_sha256='123')
            (run/'preparation.json').write_text(json.dumps(prep))
            remote=dict(prep,bdf='0000:b4:00.1')
            (run/'probe.stdout').write_text('E_RUNTIME_BEGIN_abc\n'+json.dumps(remote)+'\nE_RUNTIME_END_abc\n')
            with self.assertRaisesRegex(ValueError,'identity mismatch'):
                board.unpack(type('Args',(),dict(run_id=run.name))())
            self.assertFalse((run/'returned').exists())

    def test_remote_scripts_parse_as_python36(self):
        for path in [ROOT/'scripts/e_runtime_board.py',ROOT/'scripts/c_runtime_board.py',
                     ROOT/'scripts/e_acceptance/runtime_unseen_run.py',
                     ROOT/'scripts/e_acceptance/runtime_unseen_common.py',
                     ROOT/'scripts/e_acceptance/runtime_unseen_check.py']:
            ast.parse(path.read_text(),feature_version=(3,6))


if __name__=='__main__':unittest.main()
