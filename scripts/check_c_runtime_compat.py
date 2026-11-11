"""Check host semantics with actual packaged modules, before any device access."""
import argparse
import ctypes
import dataclasses
import json
from pathlib import Path
import struct
import sys

from ptx_frontend_v12 import Token
from ptx_launch import BufferHandle, BufferRegistry, BufferSlice
from ptx_module import ModuleError, validate
from ptx_runtime import Event, Module


def check(modules, lock):
    assert sys.version_info >= (3, 6)
    token = Token('mov.u32', 1, 2)
    assert token == Token('mov.u32', 1, 2) and hash(token) == hash(Token('mov.u32', 1, 2))
    try:
        token.line = 3
    except dataclasses.FrozenInstanceError:
        pass
    else:
        raise AssertionError('frozen Token mutated')
    assert len({BufferHandle(), BufferHandle()}) == 2
    checked = []
    for kernel in ('copy', 'vadd', 'affine'):
        manifest, image = validate(Path(modules)/kernel, Path(lock).read_bytes())
        registry = BufferRegistry()
        args, expected = [], bytearray(manifest['params_size'])
        for index, param in enumerate(manifest['params']):
            if param['kind'] == 'pointer':
                address = 0x10000 + 0x2000 * index
                handle = registry.register_native(address, 4192)
                args.append(BufferSlice(handle, 32, 132, 'rw'))
                struct.pack_into('<Q', expected, param['offset'], address+32)
            else:
                value = 33 if param['name'] == 'n' else 0xffffffff
                args.append(value)
                struct.pack_into('<I', expected, param['offset'], value)
        plan = registry.prepare(manifest, manifest['entry'], (2,1,1), (32,1,1), args)
        assert plan.payload == bytes(expected)
        module = Module(manifest, ctypes.c_void_p(), ctypes.c_void_p())
        event = Event(1, ctypes.c_void_p(), module, plan, bytes(expected))
        assert not event.completed and len({event, Event(1,None,module,plan,None)}) == 2
        event.completed = True
        assert event.completed
        registry.pin(plan)
        try:
            registry.retire(args[0].buffer)
        except ModuleError as error:
            assert error.code == 'E_BUSY'
        else:
            raise AssertionError('in-flight handle retired')
        registry.complete(plan)
        registry.retire(args[0].buffer)
        checked.append(kernel)
    return dict(status='PASS',python=sys.version,dataclasses=dataclasses.__file__,
                modules=checked,scope='module validation, dataclass identity/frozen/defaults and payload/resource checks; no device access')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--modules',type=Path,required=True)
    parser.add_argument('--lock',type=Path,required=True)
    args = parser.parse_args()
    print(json.dumps(check(args.modules,args.lock)))
