import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('readiness', Path(__file__).resolve().parents[1] / 'scripts/u280_remote_readiness.py')
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
PREP_SPEC = importlib.util.spec_from_file_location('prepare_readiness', SCRIPTS / 'prepare_u280_readiness.py')
PREP = importlib.util.module_from_spec(PREP_SPEC)
PREP_SPEC.loader.exec_module(PREP)


class ReadinessGateTests(unittest.TestCase):
    def clean(self):
        return dict(driver='xocl', ready='0x1\n', interface_uuids=M.INTERFACE_UUID + '\n',
                    device_nodes=['/dev/dri/renderD132'],
                    kdsstat='xclbin:\tabc\noutstanding execs:\t0\ntotal execs:\t42\ncontexts:\t0\nclient pid:\n')

    def test_idle_with_historical_execs(self):
        self.assertTrue(M.idle(self.clean()))

    def test_busy_or_missing_attributes_block(self):
        for key, value in [('ready', '0x0'), ('driver', 'other'), ('interface_uuids', 'other'), ('device_nodes', [])]:
            item = self.clean()
            item[key] = value
            self.assertFalse(M.idle(item), key)
        for key in self.clean():
            item = self.clean()
            item.pop(key)
            self.assertFalse(M.idle(item), key)

    def test_kds_clients_contexts_and_malformed_zero_block(self):
        for old, new in [('outstanding execs:\t0', 'outstanding execs:\t1'),
                         ('contexts:\t0', 'contexts:\t1'), ('client pid:', 'client pid: 123'),
                         ('contexts:\t0', 'contexts:'), ('contexts:\t0', 'contexts:\t0\ncontexts:\t0')]:
            item = self.clean()
            item['kdsstat'] = item['kdsstat'].replace(old, new)
            self.assertFalse(M.idle(item), new)

    def test_final_checkpoint_preference_and_ambiguity(self):
        routed = Path('/build/impl_1/hw_bb_locked_routed.dcp')
        optimized = Path('/build/impl_1/hw_bb_locked_postroute_physopt.dcp')
        self.assertEqual(M.select_final([routed, optimized]), optimized)
        wrapper = Path('/build/impl_1/level0_wrapper_postroute_physopt.dcp')
        self.assertEqual(M.select_final([wrapper, Path('/build/impl_1/level0_wrapper_routed.dcp')]), wrapper)
        with self.assertRaises(ValueError):
            M.select_final([routed, Path('/other/impl_1/hw_bb_locked_routed.dcp')])
        with self.assertRaises(ValueError):
            M.select_final([Path('/build/ip/hw_bb_locked_routed.dcp')])

    def test_timing7_bundle_uses_focused_audit_and_disables_host_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'results').mkdir()
            scripts = root / 'scripts'
            scripts.mkdir()
            for name in ('u280_remote_readiness.py', 'u280_timing7_audit.tcl', 'prepare_u280_readiness.py',
                         'Invoke-U280Readiness.ps1', 'prepare_u280_probe.py', 'wlan_ssh_proxy.py'):
                shutil.copy2(SCRIPTS / name, scripts)
            with patch.object(PREP, 'ROOT', root):
                PREP.prepare('timing7-test', timing7=True)
            run = root / 'results/timing7-test'
            bundle = json.loads((run / 'bundle.json').read_text())
            self.assertTrue(bundle['timing7'])
            self.assertFalse(bundle['configure_host'])
            self.assertEqual(bundle['tcl_sha256'], M.digest(SCRIPTS / 'u280_timing7_audit.tcl'))
            self.assertTrue((run / 'u280_timing7_audit.tcl').is_file())


if __name__ == '__main__':
    unittest.main()
