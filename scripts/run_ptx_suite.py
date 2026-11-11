"""Run copy/vadd/affine PTX on verified simulators and an explicit block32 candidate.

Author-owned oracle; neither independent E acceptance nor hardware performance.
One process per module/binding avoids mixing dynamically loaded configurations.
"""
import argparse
import json
import os
from pathlib import Path
import random
import statistics
import sys
from time import perf_counter_ns
import traceback

from ptx_launch import BufferHandle, BufferSlice
from ptx_module import ModuleError, digest, write_json
from ptx_runtime import Context, RuntimeError
from run_ptx_simx import words, expect_error

LENGTHS = (0, 1, 7, 15, 16, 17, 31, 32, 33, 65, 257, 1024)
CAPACITY = 1056


def expected_words(kernel, x, y, z, offset, n, alpha):
    output = list(z)
    for i in range(offset, offset+n):
        if kernel == 'copy':
            value = x[i]
        elif kernel == 'vadd':
            value = x[i] + y[i]
        elif kernel == 'affine':
            value = alpha*x[i] + y[i]
        else:
            raise ValueError('unknown oracle')
        output[i] = value & 0xffffffff
    return output


def launch_args(kernel, buffers, offset, n, alpha):
    accesses = ('r','w') if kernel == 'copy' else ('r','r','w')
    return [BufferSlice(b,offset*4,n*4,a) for b,a in zip(buffers,accesses)] + [n] + ([alpha] if kernel == 'affine' else [])


def timing_summary(cases):
    return {phase:dict(count=len(cases),min_ns=min(values),median_ns=statistics.median(values),max_ns=max(values))
            for phase in cases[0]['host_timing_ns']
            for values in [[case['host_timing_ns'][phase] for case in cases]]} if cases else {}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel', choices=('copy','vadd','affine'), required=True)
    parser.add_argument('--backend', choices=('simx','rtlsim','xrtsim'), default='simx')
    for name in ('module','binding','target-lock','output'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args(argv)
    for name in ('module','binding','target_lock','output'):
        setattr(args,name,getattr(args,name).resolve())
    output = args.output
    output.mkdir(parents=True,exist_ok=False)
    (output/'cases').mkdir()
    result = dict(schema_version='ptx-suite-simulation-v2',run_id=output.name,status='RUNNING',kernel=args.kernel,
        backend=args.backend,scope='author functional PTX execution and host wall-clock measurements; xrtsim is the NOXRT AFU model, not vendor hw_emu or a board',
        independent_acceptance='NOT_RUN',u280='NOT_RUN',
        invocation=[sys.executable,str(Path(__file__).resolve()),*(argv if argv is not None else sys.argv[1:])],
        invocation_cwd=str(Path.cwd()),target_lock_hash=digest(args.target_lock.read_bytes()),
        binding_sha256=digest(args.binding.read_bytes()),module_manifest_sha256=digest((args.module/'manifest.json').read_bytes()),
        timing_scope='perf_counter_ns on host; synchronous transfers; launch+wait includes simulator/host overhead; no warmup exclusion; not device cycles or FPGA throughput',
        cases=[],rejections=[],recovery=None,setup_host_timing_ns={})
    def save(): write_json(output/'result.json',result)
    def timed(record,phase,call):
        start=perf_counter_ns()
        try: return call()
        finally: record[phase]=perf_counter_ns()-start
    def reject(label,code,call):
        result['rejections'].append(dict(check=label,error=expect_error(code,call)))
    ctx=None
    save()
    os.chdir(output)
    try:
        ctx=timed(result['setup_host_timing_ns'],'open',lambda:Context(args.binding,args.target_lock,backend=args.backend,run_id=output.name))
        result['caps']=ctx.query_caps()
        module=timed(result['setup_host_timing_ns'],'load',lambda:ctx.load(args.module))
        required={'copy':['u64','u64','u32'],'vadd':['u64','u64','u64','u32'],'affine':['u64','u64','u64','u32','u32']}[args.kernel]
        if [p['type'] for p in module.manifest['params']] != required:
            raise ValueError('kernel harness parameter signature mismatch')
        limit=module.manifest['launch_limits']['max_block_x']
        if limit not in (16,32): raise ValueError('suite requires an explicit 16 or 32 thread target')
        blocks=[1,4,7,16]+([17,31,32] if limit == 32 else [])
        result['blocks']=blocks
        buffers=[ctx.alloc(CAPACITY*4) for _ in range(2 if args.kernel=='copy' else 3)]
        values=launch_args(args.kernel,buffers,4,1,1)
        launch=lambda b=1,v=values:ctx.launch(module,module.manifest['entry'],(1,1,1),(b,1,1),v)
        for bad in sorted({limit+1,64}): reject('block-'+str(bad),'E_LAUNCH_LIMIT',lambda b=bad:launch(b))
        reject('second-module','E_BUSY',lambda:ctx.load(args.module))
        reject('write-out-of-range','E_ADDRESS_RANGE',lambda:ctx.write(buffers[0],CAPACITY*4,b'1234'))
        reject('read-out-of-range','E_ADDRESS_RANGE',lambda:ctx.read(buffers[0],CAPACITY*4,4))
        reject('foreign-buffer','E_INVALID_BUFFER',lambda:ctx.read(BufferHandle(),0,4))
        bad=list(values); bad[0]=BufferSlice(buffers[0],1,4,'r')
        reject('unaligned-pointer','E_ADDRESS_RANGE',lambda:launch(v=bad))
        reject('missing-parameter','E_PARAM_LAYOUT',lambda:launch(v=values[:-1]))
        for n in LENGTHS:
            for block in blocks:
                for alpha in ((0,1,0xffffffff) if args.kernel=='affine' else (1,)):
                    for dataset in range(2):
                        case_id='%04d'%len(result['cases'])
                        offset=8 if dataset==0 else 4
                        rng=random.Random(20261111+len(result['cases']))
                        x=[rng.getrandbits(32) for _ in range(CAPACITY)]
                        y=[rng.getrandbits(32) for _ in range(CAPACITY)]
                        x[offset],y[offset]=0xffffffff,0x80000001
                        z=[0xdeadbeef ^ len(result['cases'])]*CAPACITY
                        expected=expected_words(args.kernel,x,y,z,offset,n,alpha)
                        arrays=(x,z) if args.kernel=='copy' else (x,y,z)
                        names=('x','z') if args.kernel=='copy' else ('x','y','z')
                        capture=output/'cases'/case_id
                        capture.mkdir()
                        raw=[words(a) for a in arrays]
                        for name,data in zip(names,raw): (capture/(name+'.bin')).write_bytes(data)
                        (capture/'expected.bin').write_bytes(words(expected))
                        times={}
                        timed(times,'h2d',lambda:[ctx.write(b,0,data) for b,data in zip(buffers,raw)])
                        params=launch_args(args.kernel,buffers,offset,n,alpha)
                        grid=max(1,(n+block-1)//block)
                        event=timed(times,'launch',lambda:ctx.launch(module,module.manifest['entry'],(grid,1,1),(block,1,1),params))
                        if not result['cases']:
                            for label,call in [('free',lambda:ctx.free(buffers[0])),('unload',lambda:ctx.unload(module)),
                                ('read',lambda:ctx.read(buffers[-1],0,4)),('write',lambda:ctx.write(buffers[0],0,b'1234')),
                                ('second-launch',lambda:launch()),('close',ctx.close)]: reject('in-flight-'+label,'E_BUSY',call)
                        completion=timed(times,'wait',lambda:ctx.wait(event))
                        observed=timed(times,'d2h',lambda:[ctx.read(b,0,CAPACITY*4) for b in buffers])
                        expected_raw=raw[:-1]+[words(expected)]
                        passed=timed(times,'compare',lambda:observed==expected_raw)
                        for name,data in zip(names,observed): (capture/('observed_'+name+'.bin')).write_bytes(data)
                        result['cases'].append(dict(id=case_id,n=n,block=block,grid=grid,dataset=dataset,alpha=alpha,
                            offset_bytes=offset*4,status='PASS' if passed else 'FAIL',completion=completion,
                            host_timing_ns=times,files={p.name:digest(p.read_bytes()) for p in capture.iterdir()}))
                        save()
                        if not passed: raise AssertionError('output/input/guard mismatch in '+case_id)
            print('PASS',args.kernel,'n=',n,'cases=',len(result['cases']),flush=True)
        event=ctx.launch(module,module.manifest['entry'],(1024//limit,1,1),(limit,1,1),launch_args(args.kernel,buffers,0,1024,1))
        try:
            ctx.wait(event,0)
            result['recovery']=dict(status='NOT_TRIGGERED',reason='completed before zero-time wait')
        except RuntimeError as error:
            if error.code!='E_TIMEOUT': raise
            timeout=error.to_dict()
            reject('timeout-close','E_BUSY',ctx.close)
            reject('timeout-alloc','E_UNAVAILABLE',lambda:ctx.alloc(4))
            result['timeout_caps']=ctx.query_caps()
            drained=ctx.recover(60000)
            reject('stale-buffer','E_INVALID_BUFFER',lambda:ctx.free(buffers[0]))
            reject('stale-event','E_EVENT',lambda:ctx.wait(event))
            reject('stale-module','E_MODULE_CORRUPT',lambda:launch())
            module=ctx.load(args.module)
            buffers=[ctx.alloc(4) for _ in arrays]
            tiny=[0xffffffff,0] if args.kernel=='copy' else [0xffffffff,2,0]
            for b,value in zip(buffers,tiny):ctx.write(b,0,words([value]))
            params=launch_args(args.kernel,buffers,0,1,0xffffffff)
            event=ctx.launch(module,module.manifest['entry'],(1,1,1),(1,1,1),params)
            ctx.wait(event)
            expected=expected_words(args.kernel,[0xffffffff],[2],[0],0,1,0xffffffff)
            actual=ctx.read(buffers[-1],0,4)
            if actual!=words(expected):raise AssertionError('post-recovery computation differs')
            result['recovery']=dict(status='PASS',timeout=timeout,drained=drained,observed_hex=actual.hex(),expected_hex=words(expected).hex())
        ctx.close()
        result.update(status='PASS',exit_code=0,passed=len(result['cases']),host_timing_summary=timing_summary(result['cases']))
    except Exception as error:
        result.update(status='FAIL',exit_code=1,error=error.to_dict() if isinstance(error,ModuleError) else str(error),traceback=traceback.format_exc())
        if ctx and ctx.state=='READY':ctx.close()
    finally:save()
    print(json.dumps({k:result.get(k) for k in ('status','kernel','passed','exit_code')}),flush=True)
    return result['exit_code']


if __name__=='__main__':sys.exit(main())
