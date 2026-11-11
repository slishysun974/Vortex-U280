"""Real simulator timeout/drain and CP-poll fault containment experiments.

No mock status, no hardware access, no modification of pinned native libraries.
Fault workers terminate their own process without releasing uncertain resources.
That is simulator-process isolation, never evidence of physical DMA isolation.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


class TraceNative:
    """Observe calls and real return codes without substituting any result."""
    def __init__(self, native):
        self.native, self.calls = native, []

    def __getattr__(self, name):
        function = getattr(self.native, name)
        def call(*args):
            start = time.monotonic()
            status = function(*args)
            self.calls.append(dict(name=name, status=status, seconds=time.monotonic()-start))
            return status
        return call


def worker(args):
    from ptx_runtime import Context
    from ptx_launch import BufferSlice
    from ptx_module import ModuleError
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    os.chdir(out)
    result = dict(status='RUNNING', backend=args.backend, mode=args.mode,
                  board_execution='NOT_RUN', checks=[], cycles=[],
                  runtime_sha256=sha(ROOT/'scripts/ptx_runtime.py'),
                  image_sha256=sha(args.module/'kernel.vxbin'),
                  binding_sha256=sha(args.binding), scope='real native simulation only')
    ctx = None
    def checkpoint():
        if ctx is not None:
            result['diagnostic'] = ctx.query_caps()
            result['native_calls'] = ctx.lib.calls
        save(out/'result.json', result)
    def reject(code, label, fn):
        start = time.monotonic()
        try:
            fn()
        except ModuleError as error:
            if error.code != code:
                raise AssertionError((label, code, error.to_dict()))
            result['checks'].append(dict(label=label, error=error.to_dict(), seconds=time.monotonic()-start))
        else:
            raise AssertionError('expected '+code+': '+label)
        checkpoint()
    def setup(n, seed):
        module = ctx.load(args.module)
        count = n+19
        x = struct.pack('<%dI'%count, *[((i*0x45d9f3b)^seed)&0xffffffff for i in range(count)])
        z = struct.pack('<%dI'%count, *([seed^0xa55aa55a]*count))
        handles = [ctx.alloc(len(x)), ctx.alloc(len(z))]
        for handle, data in zip(handles,(x,z)):
            ctx.write(handle,0,data)
        params = [BufferSlice(handles[0],20,n*4,'r'),BufferSlice(handles[1],20,n*4,'w'),n]
        return module, handles, params, x, z
    def canary(seed, label):
        module, handles, params, x, z = setup(37,seed)
        event = ctx.launch(module,module.manifest['entry'],(6,1,1),(7,1,1),params)
        ctx.wait(event,60000)
        observed = [ctx.read(h,0,len(x)) for h in handles]
        expected = z[:20]+x[20:20+37*4]+z[20+37*4:]
        for name,data in (('input_x',x),('input_z',z),('actual_x',observed[0]),('actual_z',observed[1]),('expected_z',expected)):
            (out/(label+'-'+name+'.bin')).write_bytes(data)
        if observed != [x,expected]:
            raise AssertionError('post-recovery input/output/guard contamination')
        for handle in handles:ctx.free(handle)
        ctx.unload(module)
        result['cycles'].append(dict(label=label,status='PASS',generation=ctx.registry.generation))
        checkpoint()
    try:
        if args.backend not in ('simx','rtlsim','xrtsim'):
            raise ValueError('fault harness is simulation-only')
        os.environ.pop('VORTEX_CP_POLL_TIMEOUT_S',None)
        ctx = Context(args.binding,args.lock,backend=args.backend,run_id=out.name)
        ctx.lib = TraceNative(ctx.lib)
        if args.mode == 'canary':
            canary(0x20261111,'fresh-process')
        elif args.mode == 'timeout':
            for cycle in range(2):
                module, handles, params, x, z = setup(4096,0x87231000+cycle)
                (out/('timeout-%d-input-x.bin'%cycle)).write_bytes(x)
                (out/('timeout-%d-input-z.bin'%cycle)).write_bytes(z)
                event=ctx.launch(module,module.manifest['entry'],(128,1,1),(32,1,1),params)
                reject('E_TIMEOUT','real-event-timeout-%d'%cycle,lambda:ctx.wait(event,0))
                before=len(ctx.lib.calls)
                for label,fn in (('read',lambda:ctx.read(handles[0],0,4)),
                                 ('free',lambda:ctx.free(handles[0])),
                                 ('unload',lambda:ctx.unload(module)),
                                 ('launch',lambda:ctx.launch(module,module.manifest['entry'],(1,1,1),(1,1,1),params))):
                    reject('E_UNAVAILABLE',label,fn)
                reject('E_BUSY','close',ctx.close)
                if len(ctx.lib.calls)!=before:raise AssertionError('unsafe native operation after timeout')
                reject('E_TIMEOUT','real-drain-timeout-%d'%cycle,lambda:ctx.recover(0))
                if ctx.registry.generation!=cycle or not event.payload or any(h not in ctx.buffers for h in handles):
                    raise AssertionError('ownership lost before drain')
                start=time.monotonic()
                recovery=ctx.recover(60000)
                result['cycles'].append(dict(label='drain-%d'%cycle,result=recovery,seconds=time.monotonic()-start))
                if recovery['generation']!=cycle+1:raise AssertionError('generation did not advance once')
                before=len(ctx.lib.calls)
                reject('E_EVENT','stale-event',lambda:ctx.wait(event,0))
                reject('E_INVALID_BUFFER','stale-buffer',lambda:ctx.free(handles[0]))
                reject('E_MODULE_CORRUPT','stale-module',lambda:ctx.unload(module))
                if len(ctx.lib.calls)!=before:raise AssertionError('stale handle reached native layer')
                canary(0xf0ab0000+cycle,'after-drain-%d'%cycle)
        else:
            module,handles,params,_,_=setup(4096,0x31029487)
            # Existing native CP timeout facility: an actual unsuccessful
            # Q_SEQNUM poll returns VX_ERR_DEVICE_LOST, not a fabricated code.
            os.environ['VORTEX_CP_POLL_TIMEOUT_S']='0.000000000001'
            event=ctx.launch(module,module.manifest['entry'],(128,1,1),(32,1,1),params)
            reject('E_DEVICE','native-cp-poll-device-lost',lambda:ctx.wait(event,60000))
            if ctx.query_caps()['device_fault']['native_status']!=6:
                raise AssertionError('expected native VX_ERR_DEVICE_LOST=6')
            before=len(ctx.lib.calls)
            for retry in range(3):reject('E_UNAVAILABLE','recover-retry-%d'%retry,lambda:ctx.recover(10))
            reject('E_UNAVAILABLE','fault-alloc',lambda:ctx.alloc(4))
            reject('E_UNAVAILABLE','fault-read',lambda:ctx.read(handles[0],0,4))
            reject('E_BUSY','fault-close',ctx.close)
            if len(ctx.lib.calls)!=before or ctx.registry.generation!=0 or not event.payload:
                raise AssertionError('fault allowed unsafe reuse/release')
            result['process_disposal']='os._exit; simulator address space only; no physical device'
            result['in_context_recovery']='UNAVAILABLE (expected)'
        if args.mode != 'cp-fault':ctx.close()
        result.update(status='PASS',exit_code=0)
    except Exception as error:
        result.update(status='FAIL',exit_code=1,error=repr(error),traceback=traceback.format_exc())
    checkpoint()
    print(json.dumps({k:result.get(k) for k in ('status','backend','mode','error')}),flush=True)
    sys.stdout.flush();sys.stderr.flush()
    # No native destructors on a failed/in-flight simulation context.
    os._exit(result['exit_code'])


def main(args):
    from run_native_smoke import Recorder, utc_now
    import re
    if not re.fullmatch(r'c-runtime-recovery-[A-Za-z0-9_.-]+',args.run_id):raise ValueError('invalid run_id')
    run=ROOT/'results'/args.run_id
    run.mkdir(exist_ok=False)
    baseline=ROOT/'results/c-runtime-merge-20261111-v3'
    summary=dict(status='RUNNING',run_id=args.run_id,commands=[],started_at=utc_now(),runs=[],
                 hardware_recovery='NOT_RUN',physical_isolation='BLOCKED: no accepted platform isolation mechanism',
                 scope='native simulator timeout/drain and CP poll fault containment; no physical fault injection')
    env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',VORTEX_PROFILING='0',
             VORTEX_SOURCE='/opt/vortex-ab/sources/vortex-7fe19369587c-v1')
    for name in ('VORTEX_CP_POLL_TIMEOUT_S','XCLBIN_PATH','XCL_EMULATION_MODE','LD_LIBRARY_PATH','VORTEX_DRIVER'):
        env.pop(name,None)
    recorder=Recorder(run,summary,env)
    try:
        summary['implementation']={}
        for path in [ROOT/'scripts/ptx_runtime.py',Path(__file__),ROOT/'tests/test_ptx_runtime.py']:
            dest=run/'implementation'/path.relative_to(ROOT)
            dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(path.read_bytes())
            summary['implementation'][path.relative_to(ROOT).as_posix()]=sha(path)
        record,_=recorder.command('python_tests',[sys.executable,'-B','-m','unittest','discover','-s','tests','-v'],ROOT,300)
        if record['returncode']!=0 or record['timed_out']:raise RuntimeError('Python selftests failed')
        for backend in ('simx','rtlsim','xrtsim'):
            binding=baseline/'bindings'/backend/'binding.json'
            identity=json.loads(binding.read_bytes())
            env.update(VORTEX_DRIVER=identity['driver'],LD_LIBRARY_PATH=identity['library_dir'])
            for mode in ('timeout','cp-fault','canary'):
                output=run/(backend+'-'+mode)
                argv=[sys.executable,'-B',Path(__file__),'--worker','--backend',backend,'--mode',mode,
                      '--module',baseline/'modules/sim/copy','--binding',binding,
                      '--lock',ROOT/'configs/candidates/block32-v1/target_lock.json','--output',output]
                record,_=recorder.command(backend+'-'+mode,argv,ROOT,180)
                if record['returncode']!=0 or record['timed_out']:raise RuntimeError('worker failed: '+backend+'-'+mode)
                receipt=json.loads((output/'result.json').read_bytes())
                if receipt['status']!='PASS':raise RuntimeError('worker did not pass')
                summary['runs'].append(dict(backend=backend,mode=mode,result=str(output.relative_to(ROOT)/'result.json'),
                                           sha256=sha(output/'result.json')))
                recorder.save()
        for path,expected in summary['implementation'].items():
            if sha(ROOT/path)!=expected:raise RuntimeError('implementation changed during run')
        summary.update(status='PASS',exit_code=0)
    except Exception as error:
        summary.update(status='FAIL',exit_code=1,error=repr(error),traceback=traceback.format_exc())
    summary['finished_at']=utc_now();recorder.save()
    print(json.dumps({k:summary.get(k) for k in ('status','exit_code','error')}))
    return summary['exit_code']


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id')
    parser.add_argument('--worker',action='store_true')
    parser.add_argument('--backend',choices=('simx','rtlsim','xrtsim'))
    parser.add_argument('--mode',choices=('timeout','cp-fault','canary'))
    for name in ('module','binding','lock','output'):parser.add_argument('--'+name,type=Path)
    args=parser.parse_args()
    if args.worker:worker(args)
    else:sys.exit(main(args))
