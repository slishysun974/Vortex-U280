"""Build and validate the locally integrated C runtime without board access."""
import argparse
import json
import os
from pathlib import Path
import sys
import traceback

from run_native_smoke import PROJECT, Recorder, sha256, utc_now


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id',required=True)
    args=parser.parse_args()
    if not __import__('re').fullmatch(r'c-runtime-merge-[A-Za-z0-9_.-]{1,70}',args.run_id):
        raise ValueError('invalid run_id')
    run=PROJECT/'results'/args.run_id
    run.mkdir(exist_ok=False)
    env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',VORTEX_PROFILING='0',
             VORTEX_SOURCE='/opt/vortex-ab/sources/vortex-7fe19369587c-v1')
    for name in ('XCLBIN_PATH','XCL_EMULATION_MODE','LD_LIBRARY_PATH','VORTEX_DRIVER'):
        env.pop(name,None)
    summary=dict(schema_version='c-runtime-merge-validation-v1',status='RUNNING',commands=[],
        run_id=args.run_id,started_at=utc_now(),board_execution='NOT_RUN',independent_E='NOT_RUN',
        scope='local source integration, fresh module builds, simulator executions and physical-gate mocks',
        modules={},runs=[],protected={})
    recorder=Recorder(run,summary,env)
    def command(label,argv,timeout=300):
        record,text=recorder.command(label,argv,PROJECT,timeout)
        if record['returncode'] != 0 or record['timed_out']:raise RuntimeError('failed: '+label)
        return text
    try:
        origin=json.loads((PROJECT/'results/c-runtime-import-20261111-v1/result.json').read_text())
        frozen=json.loads((PROJECT/'results/c-ab-integration-20261111-v3/summary.json').read_text())
        summary['protected']=dict(origin['protected'])
        summary['protected'].update({p:v['ab'] for p,v in frozen['contract_identity'].items()})
        for p,h in summary['protected'].items():
            if sha256(PROJECT/p)!=h:raise ValueError('protected input differs: '+p)
        snapshot=run/'implementation';snapshot.mkdir()
        summary['implementation']={}
        for path in sorted((PROJECT/'scripts').glob('*.py'))+sorted((PROJECT/'tests').glob('*.py')):
            rel=path.relative_to(PROJECT)
            dest=snapshot/rel;dest.parent.mkdir(exist_ok=True)
            dest.write_bytes(path.read_bytes())
            summary['implementation'][rel.as_posix()]=sha256(path)
        command('merged_python_tests',[sys.executable,'-B','-m','unittest','discover','-s','tests','-v'])
        configurations={'sim':PROJECT/'configs/candidates/block32-v1','board':PROJECT/'configs/candidates/u280-hbm32-v1'}
        for kind,config in configurations.items():
            for kernel in ('copy','vadd','affine'):
                module=run/'modules'/kind/kernel
                command('prepare_'+kind+'_'+kernel,[sys.executable,'-B',PROJECT/'scripts/ptx_module.py','prepare',
                    PROJECT/'ptx/samples'/(kernel+'_u32.ptx'),'--output',module,'--target-lock',config/'target_lock.json',
                    '--hardware',config/('native_smoke.json' if kind=='sim' else 'fpga.json')])
                command('build_'+kind+'_'+kernel,[sys.executable,'-B',PROJECT/'scripts/ptx_module.py','build',module,
                    '--target-lock',config/'target_lock.json','--vortex-source',env['VORTEX_SOURCE'],
                    '--tooldir','/opt/vortex-ab/toolchains/8c64cf921d3c6c456e80f00d24482d0aa2153a82-rtlsim-d3-v1',
                    '--build-root',PROJECT/'build'/args.run_id/kind/kernel],timeout=600)
                command('validate_'+kind+'_'+kernel,[sys.executable,'-B',PROJECT/'scripts/ptx_module.py','validate',module,
                    '--target-lock',config/'target_lock.json'])
                summary['modules'][kind+'_'+kernel]=dict(path=module.relative_to(PROJECT).as_posix(),
                    image_sha256=sha256(module/'kernel.vxbin'),manifest_sha256=sha256(module/'manifest.json'))
                recorder.save()
        for kernel in ('copy','vadd','affine'):
            if summary['modules']['sim_'+kernel]['image_sha256'] != summary['modules']['board_'+kernel]['image_sha256']:
                raise ValueError('sim/board module code differs: '+kernel)
        summary['sim_board_image_equality']='PASS'
        for backend in ('simx','rtlsim','xrtsim'):
            binding=run/'bindings'/backend
            command('bind_'+backend,[sys.executable,'-B',PROJECT/'scripts/bind_simx_runtime.py',
                '--summary',PROJECT/'results'/('ab-d5-block32-20261108-v1-'+backend)/'summary.json',
                '--target-lock',configurations['sim']/'target_lock.json',
                '--hardware',configurations['sim']/'native_smoke.json','--output',binding])
            identity=json.loads((binding/'binding.json').read_text())
            env.update(LD_LIBRARY_PATH=identity['library_dir'],VORTEX_DRIVER=identity['driver'])
            for kernel in ('copy','vadd','affine'):
                output=run/'execution'/(backend+'-'+kernel)
                command('run_'+backend+'_'+kernel,[sys.executable,'-B',PROJECT/'scripts/run_c_runtime_smoke.py',
                    '--kernel',kernel,'--backend',backend,'--module',run/'modules/sim'/kernel,
                    '--binding',binding/'binding.json','--target-lock',configurations['sim']/'target_lock.json',
                    '--output',output])
                result=json.loads((output/'result.json').read_text())
                if result['status']!='PASS':raise ValueError('worker did not pass')
                summary['runs'].append(dict(backend=backend,kernel=kernel,passed=result['passed'],
                    rejections=len(result['rejections']),result=output.relative_to(PROJECT).as_posix()+'/result.json',
                    result_sha256=sha256(output/'result.json')))
        for kernel in ('copy','vadd','affine'):
            runs=[json.loads((run/'execution'/(b+'-'+kernel)/'result.json').read_text()) for b in ('simx','rtlsim','xrtsim')]
            captures=[[{k:v for k,v in c['files'].items() if k!='payload.bin'} for c in r['cases']] for r in runs]
            if captures[1:] != [captures[0],captures[0]]:raise ValueError('cross-backend arrays differ')
        for p,h in summary['protected'].items():
            if sha256(PROJECT/p)!=h:raise ValueError('protected input changed: '+p)
        for p,h in summary['implementation'].items():
            if sha256(PROJECT/p)!=h:raise ValueError('implementation changed during validation: '+p)
        summary.update(status='PASS',exit_code=0,new_executions=sum(r['passed'] for r in summary['runs']),
                       cross_backend_arrays='PASS')
    except Exception as error:
        summary.update(status='FAIL',exit_code=1,error=str(error),traceback=traceback.format_exc())
    summary['finished_at']=utc_now();recorder.save()
    print(json.dumps({k:summary.get(k) for k in ('status','exit_code','new_executions','error')}),flush=True)
    return summary['exit_code']


if __name__=='__main__':sys.exit(main())
