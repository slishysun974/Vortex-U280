"""Runtime ownership/failure tests with a fake transport; no kernel execution."""
import ctypes as C
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from threading import RLock
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import ptx_runtime as runtime
from ptx_launch import BufferRegistry, BufferSlice
from ptx_module import ModuleError


class Transport:
    def __init__(self):
        self.wait_status = self.finish_status = 0
        self.calls = []
        self.counter = 10

    def __getattr__(self, name):
        def call(*args):
            self.calls.append(name)
            if name == 'vx_buffer_create':
                self.counter += 1
                C.cast(args[-1], C.POINTER(C.c_void_p))[0] = self.counter
            elif name == 'vx_buffer_address':
                C.cast(args[-1], C.POINTER(C.c_uint64))[0] = args[0].value * 4096
            elif name == 'vx_enqueue_launch':
                C.cast(args[-1], C.POINTER(C.c_void_p))[0] = 100
            elif name == 'vx_event_wait_value':
                return self.wait_status
            elif name == 'vx_queue_finish':
                return self.finish_status
            return 0
        return call


def context():
    # Constructor/library identity is exercised in the real SimX integration.
    result = runtime.Context.__new__(runtime.Context)
    result.backend, result.run_id = 'mock', 'runtime-author-tests'
    result.registry, result.mutex = BufferRegistry(), RLock()
    result.state, result.active, result.first_error = 'READY', None, None
    result.buffers, result.modules, result.events = {}, set(), set()
    result.device, result.queue, result.sequence = C.c_void_p(1), C.c_void_p(2), 0
    result.lib = Transport()
    result.caps = dict(threads=4, warps=4)
    return result


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.ctx = context()
        self.buffer = self.ctx.alloc(64)
        self.module = runtime.Module(dict(entry='arbitrary', native_entry='main',
            params=[dict(name='ptr', kind='pointer', size=8, offset=0)], params_size=8,
            launch_limits=dict(max_block_x=16,max_grid_x=2**31-1,max_total_threads=2**32)),
            C.c_void_p(4), C.c_void_p(5))
        self.ctx.modules.add(self.module)

    def launch(self):
        return self.ctx.launch(self.module, 'arbitrary', (1,1,1), (4,1,1), [BufferSlice(self.buffer,0,4,'rw')])

    def reject(self, code, fn):
        with self.assertRaises(ModuleError) as caught:
            fn()
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def test_busy_operations_do_not_reach_native_api(self):
        event = self.launch()
        count = len(self.ctx.lib.calls)
        for fn in (self.launch, lambda:self.ctx.free(self.buffer), lambda:self.ctx.unload(self.module),
                   self.ctx.close, lambda:self.ctx.read(self.buffer,0,4),lambda:self.ctx.write(self.buffer,0,b'1234')):
            self.reject('E_BUSY',fn)
        self.assertEqual(len(self.ctx.lib.calls), count)
        self.ctx.wait(event)
        self.ctx.free(self.buffer)
        self.ctx.unload(self.module)
        self.ctx.close()
        self.assertEqual(self.ctx.state,'CLOSED')

    def test_wait_timeout_keeps_resources_until_drain(self):
        event = self.launch()
        self.ctx.lib.wait_status = 7
        error = self.reject('E_TIMEOUT',lambda:self.ctx.wait(event,0))
        self.assertEqual(error.to_dict()['backend'],'mock')
        self.assertEqual(error.to_dict()['native_status'],7)
        self.assertEqual(self.ctx.state,'NEEDS_RECOVERY')
        self.assertIsNotNone(event.payload)
        self.reject('E_UNAVAILABLE',lambda:self.ctx.read(self.buffer,0,4))
        self.reject('E_BUSY',self.ctx.close)
        self.ctx.lib.finish_status = 7
        before = self.ctx.lib.calls.count('vx_buffer_release')
        self.reject('E_TIMEOUT',lambda:self.ctx.recover(0))
        self.assertEqual(self.ctx.lib.calls.count('vx_buffer_release'),before)
        self.ctx.lib.finish_status = 0
        self.ctx.lib.wait_status = 0
        result = self.ctx.recover(1)
        self.assertTrue(result['isolated'])
        self.assertEqual(result['generation'],1)
        self.reject('E_INVALID_BUFFER',lambda:self.ctx.free(self.buffer))
        self.reject('E_EVENT',lambda:self.ctx.wait(event))
        self.assertEqual(self.ctx.first_error,dict(native_status=7,phase='wait'))
        self.ctx.close()

    def test_wait_is_idempotent_and_launch_repeats(self):
        first = self.launch()
        self.ctx.wait(first)
        before = len(self.ctx.lib.calls)
        self.ctx.wait(first)
        self.assertEqual(len(self.ctx.lib.calls),before)
        second = self.launch()
        self.assertNotEqual(first.id,second.id)
        self.ctx.wait(second)
        self.ctx.close()

    def test_bad_transfer_and_launch_have_no_side_effects(self):
        before = len(self.ctx.lib.calls)
        self.reject('E_PARAM_LAYOUT',lambda:self.ctx.write(self.buffer,0,64))
        self.reject('E_ADDRESS_RANGE',lambda:self.ctx.write(self.buffer,63,b'1234'))
        self.reject('E_ADDRESS_RANGE',lambda:self.ctx.read(self.buffer,0,65))
        self.reject('E_LAUNCH_LIMIT',lambda:self.ctx.launch(self.module,'arbitrary',(1,1,1),(17,1,1),[BufferSlice(self.buffer,0,4,'r')]))
        self.assertEqual(len(self.ctx.lib.calls),before)
        self.assertEqual(self.ctx.state,'READY')
        self.ctx.close()

    def test_frontend_errors_have_runtime_context(self):
        self.ctx.free(self.buffer)
        error = self.reject('E_INVALID_BUFFER',lambda:self.ctx.read(self.buffer,0,4))
        self.assertEqual(error.to_dict()['phase'],'read')
        self.assertEqual(error.to_dict()['backend'],'mock')
        self.assertEqual(error.to_dict()['run_id'],'runtime-author-tests')
        self.ctx.close()

    def test_transfer_timeout_keeps_host_storage(self):
        self.ctx.lib.finish_status = 7
        self.reject('E_TIMEOUT',lambda:self.ctx.write(self.buffer,0,b'1234'))
        self.assertEqual(self.ctx.pending_transfer.raw[:4],b'1234')
        self.reject('E_BUSY',self.ctx.close)
        self.ctx.lib.finish_status = 0
        self.ctx.recover(1)
        self.assertIsNone(self.ctx.pending_transfer)
        self.ctx.close()

    def test_timeout_bounds_and_closed_state(self):
        for value in (-1,True,1.5,2**64):
            self.reject('E_PARAM_LAYOUT',lambda:runtime.Context.timeout_ns(value))
        self.ctx.close()
        self.ctx.close()
        self.reject('E_UNAVAILABLE',lambda:self.ctx.alloc(4))

    def test_second_module_is_rejected_before_io_or_native_load(self):
        before=list(self.ctx.lib.calls)
        self.reject('E_BUSY',lambda:self.ctx.load('/does-not-exist/module'))
        self.assertEqual(self.ctx.lib.calls,before)
        self.assertEqual(self.ctx.query_caps()['max_modules'],1)
        self.ctx.close()

    def test_first_fault_is_queryable_and_cannot_be_mutated_by_caller(self):
        event=self.launch()
        self.ctx.lib.wait_status=7
        self.reject('E_TIMEOUT',lambda:self.ctx.wait(event,0))
        caps=self.ctx.query_caps()
        self.assertEqual(caps['first_error'],dict(native_status=7,phase='wait'))
        caps['first_error']['native_status']=999
        self.ctx.lib.finish_status=4
        self.reject('E_DEVICE',lambda:self.ctx.recover(1))
        self.assertEqual(self.ctx.query_caps()['first_error']['native_status'],7)
        self.assertEqual(self.ctx.query_caps()['device_state'],'NEEDS_RECOVERY')
        self.ctx.lib.finish_status=0
        before=list(self.ctx.lib.calls)
        self.reject('E_UNAVAILABLE',lambda:self.ctx.recover(1))
        self.assertEqual(self.ctx.lib.calls,before)
        self.assertEqual(self.ctx.registry.generation,0)
        self.assertIn(self.buffer,self.ctx.buffers)
        self.reject('E_BUSY',self.ctx.close)

    def test_barrier_success_does_not_override_failed_original_event(self):
        event=self.launch()
        self.ctx.lib.wait_status=7
        self.reject('E_TIMEOUT',lambda:self.ctx.wait(event,0))
        self.ctx.lib.wait_status=9
        self.ctx.lib.finish_status=0
        self.reject('E_DEVICE',lambda:self.ctx.recover(1))
        self.assertEqual(self.ctx.query_caps()['device_fault'],dict(native_status=9,phase='recover_event'))
        self.ctx.lib.wait_status=0
        before=list(self.ctx.lib.calls)
        for _ in range(3):self.reject('E_UNAVAILABLE',lambda:self.ctx.recover(1))
        self.assertEqual(self.ctx.lib.calls,before)
        self.assertEqual(self.ctx.registry.generation,0)
        self.assertIsNotNone(event.payload)

    def test_device_fault_blocks_all_recovery_retries_and_normal_operations(self):
        event=self.launch()
        self.ctx.lib.wait_status=9
        self.reject('E_DEVICE',lambda:self.ctx.wait(event,1))
        before=list(self.ctx.lib.calls)
        self.ctx.lib.wait_status=self.ctx.lib.finish_status=0
        for fn in (lambda:self.ctx.recover(1),lambda:self.ctx.alloc(4),
                   lambda:self.ctx.read(self.buffer,0,4),lambda:self.ctx.free(self.buffer),
                   lambda:self.ctx.unload(self.module),self.launch):
            self.reject('E_UNAVAILABLE',fn)
        self.reject('E_BUSY',self.ctx.close)
        self.assertEqual(self.ctx.lib.calls,before)
        caps=self.ctx.query_caps()
        caps['device_fault']['native_status']=999
        self.assertEqual(self.ctx.query_caps()['device_fault']['native_status'],9)


@unittest.skipUnless(os.environ.get('VORTEX_SOURCE') and shutil.which('g++'), 'pinned native headers/compiler required')
class NativeABITests(unittest.TestCase):
    def test_ctypes_layout_matches_compiled_vortex2_header(self):
        source = Path(os.environ['VORTEX_SOURCE'])
        self.assertEqual(subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip(),runtime.COMMIT)
        lines = ['#include <vortex2.h>','#include <cstdio>','#include <cstddef>','int main() {']
        expected = []
        for native, wrapped in [('vx_queue_info_t',runtime.QueueInfo),('vx_launch_info_t',runtime.LaunchInfo)]:
            lines.append('std::printf("%%zu\\n", sizeof(%s));' % native)
            expected.append(C.sizeof(wrapped))
            for field, _ in wrapped._fields_:
                lines.append('std::printf("%%zu\\n", offsetof(%s,%s));' % (native,field))
                expected.append(getattr(wrapped,field).offset)
        lines.append('}')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'abi.cpp').write_text('\n'.join(lines))
            compile = subprocess.run(['g++','-std=c++17','-Werror','-I',str(source/'sw/runtime/include'),str(root/'abi.cpp'),'-o',str(root/'abi')],capture_output=True,text=True)
            self.assertEqual(compile.returncode,0,compile.stderr)
            actual = subprocess.check_output([str(root/'abi')],text=True)
            self.assertEqual(list(map(int,actual.split())),expected)


if __name__ == '__main__':
    unittest.main()
