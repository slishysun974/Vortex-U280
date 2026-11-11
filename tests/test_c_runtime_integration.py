"""Version and physical gate negative tests; mocks are not board evidence."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import ptx_frontend
import ptx_frontend_v12
import ptx_module as module
import ptx_u280 as board
from ptx_runtime import Context
from test_ptx_runtime import context


class VersionTests(unittest.TestCase):
    def test_python36_integer_suffix_keeps_original_semantics(self):
        self.assertEqual(ptx_frontend_v12.HOST_COMPATIBILITY,'python36-integer-v1')
        for literal in ('0','0U','00U','077U','0xFFU','0b101U','+123U','-1U',
                        '18446744073709551615U','18446744073709551616U','1UU','U','08U'):
            outcomes=[]
            for frontend in (ptx_frontend,ptx_frontend_v12):
                try:outcomes.append(('value',frontend.Parser(literal,'literal.ptx').integer()))
                except frontend.PtxError as error:outcomes.append(('error',error.code))
            with self.subTest(literal=literal):self.assertEqual(outcomes[0],outcomes[1])

    def test_frontend_versions_are_separate_and_old_bytes_retained(self):
        self.assertEqual(ptx_frontend.COMPILER,'ptx-vx-frontend-v1')
        self.assertEqual(module.frontend.COMPILER,'ptx-vx-frontend-v1.2')
        original=json.loads((ROOT/'results/c-runtime-import-20261111-v1/result.json').read_text())
        self.assertEqual(module.digest((ROOT/'scripts/ptx_frontend.py').read_bytes()),
                         original['protected']['scripts/ptx_frontend.py'])
        source=(ROOT/'ptx/samples/vadd_u32.ptx').read_text()
        legacy,current=ptx_frontend.parse(source),ptx_frontend_v12.parse(source)
        self.assertEqual(legacy.pop('compiler_id'),'ptx-vx-frontend-v1')
        self.assertEqual(current.pop('compiler_id'),'ptx-vx-frontend-v1.2')
        self.assertEqual(legacy,current)
        self.assertNotEqual(ptx_frontend.emit_cpp(ptx_frontend.parse(source))[0],
                            ptx_frontend_v12.emit_cpp(ptx_frontend_v12.parse(source))[0])

    def test_board_module_is_versioned_and_cannot_cross_lock(self):
        lock=ROOT/'configs/candidates/u280-hbm32-v1/target_lock.json'
        hw=lock.with_name('fpga.json')
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)/'module'
            record=module.prepare((ROOT/'ptx/samples/vadd_u32.ptx').read_text(),out,lock,hw)
            self.assertEqual(record['schema_version'],module.BOARD_SCHEMA)
            self.assertEqual(record['target_adapter_version'],module.BOARD_TARGET_ADAPTER)
            module.verify_sources(out,lock.read_bytes())
            with self.assertRaises(module.ModuleError):
                module.verify_sources(out,(ROOT/'configs/candidates/block32-v1/target_lock.json').read_bytes())
            record['schema_version']=module.SCHEMA
            module.write_json(out/'manifest.json',record)
            with self.assertRaises(module.ModuleError):module.verify_sources(out,lock.read_bytes())

    def test_platform_define_cannot_be_removed_or_extended(self):
        lock=json.loads((ROOT/'configs/candidates/u280-hbm32-v1/target_lock.json').read_text())
        hw=json.loads((ROOT/'configs/candidates/u280-hbm32-v1/fpga.json').read_text())
        for mutation in ('drop','extra','boolean'):
            bad=copy.deepcopy(hw)
            if mutation=='drop':del bad['defines']['PLATFORM_MERGED_MEMORY_INTERFACE']
            elif mutation=='extra':bad['defines']['UNREVIEWED']=1
            else:bad['defines']['VX_CFG_NUM_WARPS']=True
            raw=json.dumps(bad).encode()
            altered=dict(lock,hardware_config_sha256=module.digest(raw))
            with self.subTest(mutation=mutation),self.assertRaises(module.ModuleError):
                module.target(json.dumps(altered).encode(),raw)


class BoardGates(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.lock=ROOT/'configs/candidates/u280-hbm32-v1/target_lock.json'
        self.query=self.root/'query';self.query.write_bytes(b'mock query: never executed')
        self.lib=ROOT/'results/u280-runtime-20261109-v4/returned/runtime/lib'
        self.bit=ROOT/'results/u280-archive-20261109-v5/returned/artifacts/vortex_afu.xclbin'
        if not (self.lib/'libvortex.so').is_file() or not self.bit.is_file():
            self.skipTest('Archived physical D10/D12 binaries are required for identity-gate fixtures')
        self.path=self.root/'binding'/'binding.json'
        self.binding=board.create_binding(self.path.parent,self.lock,self.lock.with_name('fpga.json'),
                                         self.lib,self.bit,self.query,'0000:b1:00.1',3)
        self.environment=dict(VORTEX_DRIVER='xrt',XCLBIN_PATH=str(self.bit.resolve()),
                              LD_LIBRARY_PATH=str(self.lib.resolve()),XRT_DEVICE_INDEX='3',XCL_EMULATION_MODE='')

    def test_invalid_binding_cannot_load_native_library(self):
        mutations={'schema_version':'ptx-vx-runtime-binding-v3','bdf':'0000:b5:00.1',
                   'index':True,'clock_mhz':300,'xclbin_sha256':'0'*64,'recovery':'reset',
                   'target_lock_hash':'0'*64,'query_source_sha256':'0'*64}
        for index,(key,value) in enumerate(mutations.items()):
            bad=dict(self.binding);bad[key]=value
            module.write_json(self.path,bad)
            with self.subTest(key=key),patch.dict(os.environ,self.environment),patch('ptx_runtime.C.CDLL') as load:
                with self.assertRaises(module.ModuleError):Context(self.path,self.lock,backend='u280-xrt',run_id='bad-'+str(index))
                load.assert_not_called()

    def test_wrong_bdf_query_blocks_before_native_open(self):
        listing=[{}]*3+[dict(bdf='0000:b1:00.1',is_ready='true')]
        report=dict(pcie_info={'shared_host_mem_size_bytes':268435456})
        with patch.dict(os.environ,self.environment),patch.object(board.BoardGate,'idle'),\
                patch.object(board.BoardGate,'report',side_effect=[listing,report]),\
                patch.object(board.BoardGate,'command',return_value=dict(exit_code=0,stdout='0000:b4:00.1')),\
                patch('ptx_runtime.C.CDLL') as load:
            with self.assertRaises(module.ModuleError):Context(self.path,self.lock,backend='u280-xrt',run_id='wrong-bdf')
            load.assert_not_called()

    def test_loaded_uuid_and_actual_clock_must_match(self):
        with patch.dict(os.environ,self.environment):
            gate=board.BoardGate(self.path,self.lock.read_bytes(),'post-open')
        for uid,clock in [('wrong',200),(board.XCLBIN_UUID,300)]:
            with patch('ptx_u280.snapshot',return_value={'xclbinuuid':uid}),\
                    patch.object(gate,'report',return_value={'platforms':[{'clocks':[{'id':'DATA_CLK','freq_mhz':clock}]}]}):
                with self.assertRaises(module.ModuleError):gate.opened()

    def test_physical_recovery_cannot_free_or_claim_isolation(self):
        ctx=context();ctx.backend='u280-xrt';ctx.state='NEEDS_RECOVERY'
        before=list(ctx.lib.calls)
        with self.assertRaises(module.ModuleError) as caught:ctx.recover(1)
        self.assertEqual(caught.exception.code,'E_UNAVAILABLE')
        self.assertEqual(ctx.lib.calls,before)
        self.assertEqual(ctx.state,'NEEDS_RECOVERY')
        self.assertEqual(ctx.query_caps()['recovery_mode'],'unavailable')
