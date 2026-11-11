"""Execute a compiled PTX vadd through the project runtime on real SimX.

Author-owned functional oracle, not E's independent acceptance or FPGA evidence.
The program image is supplied by the module builder, never a CPU implementation.
"""
import argparse
import json
import os
from pathlib import Path
import random
import struct
import sys
import traceback

from ptx_module import digest, write_json, ModuleError
from ptx_launch import BufferSlice
from ptx_runtime import Context, RuntimeError


def words(values):
    return struct.pack('<%dI' % len(values), *values)


def expect_error(code, operation):
    try:
        operation()
    except ModuleError as error:
        if error.code != code:
            raise AssertionError('expected %s, got %s' % (code, error.code)) from error
        return error.to_dict()
    raise AssertionError('expected rejection ' + code)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--module', type=Path, required=True)
    parser.add_argument('--binding', type=Path, required=True)
    parser.add_argument('--target-lock', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    for name in ('module','binding','target_lock','output'):
        setattr(args,name,getattr(args,name).resolve())
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    (output / 'cases').mkdir()
    result = dict(schema_version='ptx-vadd-simx-run-v1', run_id=output.name,
                  status='RUNNING', backend='simx', scope='PTX vadd author functional validation',
                  independent_acceptance='NOT_RUN', rtlsim='NOT_RUN', u280='NOT_RUN',
                  invocation=sys.argv, invocation_cwd=str(Path.cwd()), target_lock_hash=digest(args.target_lock.read_bytes()),
                  binding_sha256=digest(args.binding.read_bytes()),
                  module_manifest_sha256=digest((args.module/'manifest.json').read_bytes()),
                  cases=[], rejections=[], recovery=None)
    def save():
        write_json(output / 'result.json', result)
    save()
    # Ramulator emits a stats log in cwd; keep backend side effects with this
    # run's evidence instead of writing into the source checkout.
    os.chdir(output)
    ctx = None
    code = 1
    try:
        ctx = Context(args.binding, args.target_lock, run_id=output.name)
        result['caps'] = ctx.query_caps()
        module = ctx.load(args.module)
        if [p['type'] for p in module.manifest['params']] != ['u64','u64','u64','u32']:
            raise ValueError('vadd harness requires ordered x/y/z pointer and n:u32 parameters')
        buffers = [ctx.alloc(1056 * 4) for _ in range(3)]
        result['rejections'].append(expect_error('E_LAUNCH_LIMIT', lambda:ctx.launch(module,module.manifest['entry'],
            (1,1,1),(17,1,1),[BufferSlice(b,32,4,'rw') for b in buffers]+[1])))
        for n in (0,1,7,15,16,17,31,32,33,65,257,1024):
            for block in (1,4,7,16):
                for dataset in range(2):
                    case_id = '%04d' % len(result['cases'])
                    offset = 8 if dataset == 0 else 4
                    rng = random.Random(20261110 + len(result['cases']))
                    x = [rng.getrandbits(32) for _ in range(1056)]
                    y = [rng.getrandbits(32) for _ in range(1056)]
                    # Guaranteed carry/signedness boundary plus unseen inputs.
                    x[offset], y[offset] = 0xffffffff, 0x80000001
                    z = [0xdeadbeef ^ len(result['cases'])] * 1056
                    expected = list(z)
                    for i in range(n):
                        expected[offset+i] = (x[offset+i]+y[offset+i]) & 0xffffffff
                    capture = output / 'cases' / case_id
                    capture.mkdir()
                    for name, data in [('x',x),('y',y),('z',z),('expected',expected)]:
                        (capture/(name+'.bin')).write_bytes(words(data))
                    for handle,data in zip(buffers,(x,y,z)):
                        ctx.write(handle,0,words(data))
                    values = [BufferSlice(b,offset*4,n*4,access) for b,access in zip(buffers,('r','r','w'))]+[n]
                    grid = max(1,(n+block-1)//block)
                    event = ctx.launch(module,module.manifest['entry'],(grid,1,1),(block,1,1),values)
                    if not result['cases']:
                        result['rejections'].append(expect_error('E_BUSY',lambda:ctx.free(buffers[0])))
                        result['rejections'].append(expect_error('E_BUSY',lambda:ctx.unload(module)))
                        result['rejections'].append(expect_error('E_BUSY',lambda:ctx.read(buffers[2],0,4)))
                        result['rejections'].append(expect_error('E_BUSY',ctx.close))
                    completion = ctx.wait(event)
                    observed = [ctx.read(b,0,1056*4) for b in buffers]
                    for name,data in zip(('observed_x','observed_y','observed_z'),observed):
                        (capture/(name+'.bin')).write_bytes(data)
                    passed = observed == [words(x),words(y),words(expected)]
                    record = dict(id=case_id,n=n,block=block,grid=grid,dataset=dataset,offset_bytes=offset*4,
                                  status='PASS' if passed else 'FAIL',completion=completion,
                                  files={p.name:digest(p.read_bytes()) for p in capture.iterdir()})
                    result['cases'].append(record)
                    save()
                    if not passed:
                        raise AssertionError('vadd output/input/guard mismatch in '+case_id)
                    print('PASS',case_id,'n=',n,'block=',block,flush=True)
        # Exercise a real zero-time wait; successful completion is also legal.
        values = [BufferSlice(b,0,1024*4,access) for b,access in zip(buffers,('r','r','w'))]+[1024]
        event = ctx.launch(module,module.manifest['entry'],(64,1,1),(16,1,1),values)
        try:
            ctx.wait(event,0)
            result['recovery'] = dict(status='NOT_TRIGGERED',reason='event completed before zero-time wait')
        except RuntimeError as error:
            if error.code != 'E_TIMEOUT':
                raise
            timeout = error.to_dict()
            expect_error('E_BUSY',ctx.close)
            drained = ctx.recover(60000)
            expect_error('E_INVALID_BUFFER',lambda:ctx.free(buffers[0]))
            expect_error('E_EVENT',lambda:ctx.wait(event))
            # Reallocate/reload after generation change, then execute and compare.
            module = ctx.load(args.module)
            buffers = [ctx.alloc(4) for _ in range(3)]
            for b,value in zip(buffers,(0xffffffff,2,0)):
                ctx.write(b,0,words([value]))
            event = ctx.launch(module,module.manifest['entry'],(1,1,1),(1,1,1),
                               [BufferSlice(b,0,4,'rw') for b in buffers]+[1])
            ctx.wait(event)
            if ctx.read(buffers[2],0,4) != words([1]):
                raise AssertionError('post-recovery result mismatch')
            result['recovery'] = dict(status='PASS',timeout=timeout,drained=drained,post_recovery_execution='PASS')
        ctx.close()
        result.update(status='PASS',passed=len(result['cases']),exit_code=0)
        code=0
    except Exception as error:
        result.update(status='FAIL',exit_code=1,error=error.to_dict() if isinstance(error,ModuleError) else str(error),
                      traceback=traceback.format_exc(),device_state=ctx.state if ctx else None)
        if ctx and ctx.state == 'READY':
            ctx.close()
    finally:
        save()
    print(json.dumps(dict(status=result['status'],cases=len(result['cases']),result=str(output/'result.json'))),flush=True)
    return code


if __name__ == '__main__':
    sys.exit(main())
