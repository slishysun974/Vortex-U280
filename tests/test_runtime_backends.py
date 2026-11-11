"""Fail-closed simulation binding checks; these are not device acceptance."""
import copy
import json
from pathlib import Path
import sys
import unittest
import tempfile
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from ptx_module import COMMIT
from runtime_backends import BACKENDS, validate_native
from ptx_module import digest, ModuleError
from ptx_runtime import Context


def summary(backend='xrtsim'):
    return dict(status='PASS', demo_execution='PASS', backend=backend, check_only=False,
        source=dict(source_commit=COMMIT), config_file_sha256={'target_lock.json':'locked'},
        commands=[dict(label='runtime_build',returncode=0,timed_out=False),
                  dict(label='demo_run',returncode=0,timed_out=False)],
        effective_backend_configuration=dict(raw_configs='-DSIMULATION -DSV_DPI',
            simulation_controls=['NOXRT','XRTSIM','TARGET=xrtsim']))


class BackendTests(unittest.TestCase):
    def test_bad_binding_rejected_before_loading_native_library(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); lock=b'{}\n'; (root/'lock.json').write_bytes(lock)
            native=summary();native['config_file_sha256']['target_lock.json']=digest(lock)
            native['build_artifacts']={'sw/runtime/'+name:{'sha256':'built'} for name in ('libvortex.so',*BACKENDS['xrtsim'][1:])}
            binding=dict(schema_version='ptx-vx-runtime-binding-v3',backend='xrtsim',driver='xrt',
                source_commit=COMMIT,target_lock_hash=digest(lock),libraries={name:'built' for name in ('libvortex.so',*BACKENDS['xrtsim'][1:])})
            for failure in ('driver','summary-hash','simulation-controls','library-hash','legacy-schema','physical-xrt'):
                b=copy.deepcopy(binding); n=copy.deepcopy(native); backend='xrtsim'
                if failure=='driver':b['driver']='simx'
                if failure=='simulation-controls':n['effective_backend_configuration']['simulation_controls']=[]
                if failure=='library-hash':b['libraries']['libxrtsim.so']='changed'
                if failure=='legacy-schema':b['schema_version']='ptx-vx-runtime-binding-v2'
                if failure=='physical-xrt':b['backend']=backend='xrt'
                raw=json.dumps(n).encode();(root/'native-summary.json').write_bytes(raw)
                b['native_summary_sha256']='wrong' if failure=='summary-hash' else digest(raw)
                (root/'binding.json').write_text(json.dumps(b))
                with self.subTest(failure=failure),patch('ptx_runtime.C.CDLL') as loader:
                    with self.assertRaises(ModuleError):Context(root/'binding.json',root/'lock.json',backend=backend)
                    loader.assert_not_called()

    def test_explicit_driver_mapping(self):
        for backend in BACKENDS:
            validate_native(summary(backend), backend, 'locked')
        self.assertEqual(BACKENDS['xrtsim'][0], 'xrt')
        self.assertNotIn('xrt', BACKENDS)
        with self.assertRaises(ValueError):
            validate_native(summary('xrt'), 'xrt', 'locked')

    def test_wrong_target_backend_or_unexecuted_summary_rejected(self):
        good=summary()
        for key,value in [('backend','simx'),('check_only',True),('status','FAIL'),
                          ('demo_execution','NOT_RUN'),('commands',[])]:
            bad=copy.deepcopy(good); bad[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):
                validate_native(bad,'xrtsim','locked')
        with self.assertRaises(ValueError):validate_native(good,'xrtsim','different')

    def test_failed_or_timed_out_demo_rejected(self):
        for key,value in [('returncode',1),('timed_out',True),('label','demo_build')]:
            bad=summary();bad['commands'][-1][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):
                validate_native(bad,'xrtsim','locked')

    def test_hardware_or_incomplete_afu_controls_rejected(self):
        for controls in ([],['NOXRT'],['NOXRT','XRTSIM','TARGET=hw']):
            bad=summary();bad['effective_backend_configuration']['simulation_controls']=controls
            with self.subTest(controls=controls),self.assertRaises(ValueError):
                validate_native(bad,'xrtsim','locked')
        for backend in ('rtlsim','xrtsim'):
            bad=summary(backend);bad['effective_backend_configuration']['raw_configs']='-DSIMULATION'
            with self.assertRaises(ValueError):validate_native(bad,backend,'locked')
