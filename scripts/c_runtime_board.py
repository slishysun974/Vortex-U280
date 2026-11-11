"""Prepare, execute and receive the integrated C runtime U280 smoke.

The remote bootstrap supports existing Python 3.6 using the pinned project-local
dataclasses backport. It never installs software or changes HOST/system settings.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import uuid
import zlib

ROOT = Path(__file__).resolve().parents[1] if '__file__' in globals() else None
if ROOT is not None and ROOT.name == 'results':
    ROOT = ROOT.parent  # archived receiver beside its original run
PY_FILES = ('ptx_frontend_v12.py','ptx_module.py','ptx_launch.py','ptx_runtime.py',
            'runtime_backends.py','ptx_u280.py','u280_board_smoke.py','run_c_runtime_smoke.py')
KERNELS = ('copy','vadd','affine')


def sha(raw):return hashlib.sha256(raw).hexdigest()


def require(ok,message):
    if not ok:raise ValueError(message)


def safe_member(name):
    require(isinstance(name,str) and re.fullmatch(r'[A-Za-z0-9_./-]+',name)
            and not name.startswith('/') and all(p not in ('','..','.') for p in name.split('/')),
            'unsafe member: '+str(name))
    return name


def encode(files):
    return {safe_member(name):dict(sha256=sha(raw),base64=base64.b64encode(raw).decode('ascii')) for name,raw in files.items()}


def decode_into(files,root):
    for name,item in files.items():
        path=Path(root)/safe_member(name)
        raw=base64.b64decode(item['base64'],validate=True)
        require(sha(raw)==item['sha256'],'file hash mismatch: '+name)
        path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('xb') as stream:stream.write(raw)


class Blocked(RuntimeError):pass


def remote(bundle):
    result=dict(schema_version='c-u280-runtime-run-v1',run_id=bundle['run_id'],nonce=bundle['nonce'],
        status='FAIL',exit_code=1,board_execution='NOT_RUN',commands=[],kernels={},bdf=bundle['bdf'],
        source_run=bundle['source_run'],source_summary_sha256=bundle['source_summary_sha256'],
        independent_E='NOT_RUN',recovery='NOT_RUN',timing7='OPEN')
    work=Path.home()/'vortex-c-runtime'/bundle['run_id']
    def command(label,argv,env=None,seconds=30):
        item=dict(label=label,argv=[str(x) for x in argv],exit_code=None,timeout_seconds=seconds)
        result['commands'].append(item)
        start=time.monotonic()
        try:
            done=subprocess.run(item['argv'],cwd=str(work),env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=seconds)
            item.update(exit_code=done.returncode,stdout=done.stdout.decode(errors='replace'),stderr=done.stderr.decode(errors='replace'))
        except subprocess.TimeoutExpired as error:
            item.update(timed_out=True,stdout=(error.stdout or b'').decode(errors='replace'),stderr=(error.stderr or b'').decode(errors='replace'))
        item['seconds']=round(time.monotonic()-start,3)
        return item
    try:
        work.mkdir(parents=True,exist_ok=False)
        decode_into(bundle['files'],work)
        env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',VORTEX_PROFILING='0')
        env.pop('XCL_EMULATION_MODE',None)
        candidates=[shutil.which(n) for n in ('python3.12','python3.11','python3.10','python3.9','python3.8','python3.7','python3')]
        candidates += [str(Path.home()/p) for p in ('.local/bin/python3','miniconda3/bin/python','anaconda3/bin/python')]
        python=None
        for candidate in dict.fromkeys(p for p in candidates if p and Path(p).is_file()):
            probe="import sys,json; assert sys.version_info >= (3,6); print(json.dumps(list(sys.version_info[:3])))"
            check=command('python_probe',[candidate,'-B','-c',probe])
            if check['exit_code']==0:
                python=candidate
                version=json.loads(check['stdout'])
                if version[:2]==[3,6]:
                    env['PYTHONPATH']=str(work/'vendor/dataclasses-0.8')
                else:
                    env.pop('PYTHONPATH',None)
                result['python_version']=version
                break
        if python is None:raise Blocked('No existing Python >=3.6 found; no software installed and no device opened')
        result['python']=python
        compat=command('host_compatibility',[python,'-B',work/'scripts/check_c_runtime_compat.py',
            '--modules',work/'modules','--lock',work/'target_lock.json'],env)
        require(compat['exit_code']==0,'host compatibility checks failed before device access')
        result['host_compatibility']=json.loads(compat['stdout'])
        libs=Path.home()/'vortex-u280-runtime/u280-runtime-20261109-v4/build/lib'
        bit=Path.home()/'vortex-u280-builds/u280-link-20261109-103830-671/out/vortex_afu.xclbin'
        env.update(VORTEX_DRIVER='xrt',XCLBIN_PATH=str(bit),LD_LIBRARY_PATH=str(libs)+':'+env.get('LD_LIBRARY_PATH',''))
        for name,expected in bundle['runtime_hashes'].items():require(sha((libs/name).read_bytes())==expected,'D12 library changed: '+name)
        require(sha(bit.read_bytes())==bundle['xclbin_sha256'],'D10 bitstream changed')
        for name in bundle['runtime_hashes']:
            dep=command('ldd_'+name,['ldd',libs/name],env)
            require(dep['exit_code']==0 and 'not found' not in dep['stdout'],'unresolved physical runtime dependency')
        compiler='/opt/rh/devtoolset-9/root/usr/bin/g++'
        query=work/'xrt_bdf'
        build=command('compile_bdf_query',[compiler,'-std=c++17','-O2','-I/opt/xilinx/xrt/include',
            work/'query.cpp','-L/opt/xilinx/xrt/lib','-lxrt_coreutil','-o',query],env,60)
        require(build['exit_code']==0,'XRT BDF query compile failed')
        result['query_sha256']=sha(query.read_bytes())
        listing=command('enumerate',['xbutil','examine','--format','JSON','--output',work/'devices.json'],env)
        require(listing['exit_code']==0,'XRT enumeration failed')
        devices=json.loads((work/'devices.json').read_text())['system']['host']['devices']
        indices=[i for i,d in enumerate(devices) if d['bdf']==bundle['bdf'] and d['is_ready']=='true']
        if len(indices)!=1:raise Blocked('Requested BDF is not uniquely ready; no device opened')
        result['xrt_index']=indices[0];env['XRT_DEVICE_INDEX']=str(indices[0])
        bind=command('bind_physical',[python,'-B',work/'scripts/ptx_u280.py','--output',work/'binding',
            '--lock',work/'target_lock.json','--hardware',work/'hardware.json','--library-dir',libs,'--xclbin',bit,
            '--query',query,'--bdf',bundle['bdf'],'--index',str(indices[0])],env)
        require(bind['exit_code']==0,'physical binding creation failed')
        for kernel in KERNELS:
            output=work/'execution'/kernel
            result['board_execution']='FAIL'
            run=command('execute_'+kernel,[python,'-B',work/'scripts/run_c_runtime_smoke.py',
                '--kernel',kernel,'--backend','u280-xrt','--module',work/'modules'/kernel,
                '--binding',work/'binding/binding.json','--target-lock',work/'target_lock.json','--output',output],env,180)
            require(run['exit_code']==0,'C runtime failed: '+kernel+'; no subsequent kernel submitted')
            actual=json.loads((output/'result.json').read_text())
            expected=bundle['model_results'][kernel]
            require(actual['status']=='PASS' and actual['backend']=='u280-xrt' and actual['u280']=='PASS'
                    and actual['image_sha256']==expected['image_sha256'] and actual['passed']==expected['passed'],
                    'physical kernel identity/count differs')
            require(len(actual['cases'])==len(expected['cases']),'case count differs')
            for left,right in zip(actual['cases'],expected['cases']):
                for key in ('n','block','grid','alpha','offset_bytes'):
                    require(left[key]==right[key],'physical launch geometry differs')
                require({k:v for k,v in left['files'].items() if k!='payload.bin'} ==
                        {k:v for k,v in right['files'].items() if k!='payload.bin'},'physical capture differs from models')
            gate=json.loads((work/'binding/sessions'/kernel/'gate.json').read_text())
            require(gate['status']=='PASS' and gate['open_gate']=='PASS' and gate['close_gate']=='PASS','board gates did not pass')
            result['kernels'][kernel]=dict(status='PASS',passed=actual['passed'],result_sha256=sha((output/'result.json').read_bytes()),
                                          gate_sha256=sha((work/'binding/sessions'/kernel/'gate.json').read_bytes()))
        result.update(status='PASS',exit_code=0,board_execution='PASS',passed=sum(k['passed'] for k in result['kernels'].values()))
    except Blocked as error:
        result.update(status='BLOCKED',error=str(error))
    except Exception as error:
        result['error']=repr(error)
    if work.is_dir():
        exported={p.relative_to(work).as_posix():p.read_bytes() for p in work.rglob('*') if p.is_file()
                  and (p.relative_to(work).parts[0] in ('execution','binding') or p.name=='devices.json')}
        result['export']=encode(exported)
    return result


def prepare(run_id,source_run,bdf):
    from ptx_module import validate
    from ptx_u280 import QUERY_SOURCE, RUNTIME_SHAS, XCLBIN_SHA, BUSES
    require(re.fullmatch(r'c-u280-runtime-[A-Za-z0-9_.-]{1,70}',run_id),'invalid run_id')
    require(re.fullmatch(r'c-runtime-merge-[A-Za-z0-9_.-]{1,70}',source_run),'invalid source run')
    require(bdf in ['0000:'+bus+':00.1' for bus in BUSES],'BDF outside current allowed list')
    source=ROOT/'results'/source_run
    raw=(source/'summary.json').read_bytes();summary=json.loads(raw)
    require(summary['status']=='PASS' and summary['sim_board_image_equality']=='PASS' and summary['new_executions']==123,'successful merged module execution required')
    for item in summary['commands']:
        require(item['returncode']==0 and not item['timed_out'] and sha((source/item['log']).read_bytes())==item['log_sha256'], 'source command/log is invalid')
    for name in PY_FILES:
        require(sha((ROOT/'scripts'/name).read_bytes())==summary['implementation']['scripts/'+name], 'runtime changed since model validation: '+name)
    lock=ROOT/'configs/candidates/u280-hbm32-v1/target_lock.json'
    files={'scripts/'+name:(ROOT/'scripts'/name).read_bytes() for name in PY_FILES}
    files.update({'target_lock.json':lock.read_bytes(),'hardware.json':lock.with_name('fpga.json').read_bytes(),'query.cpp':QUERY_SOURCE.encode()})
    files['scripts/check_c_runtime_compat.py']=(ROOT/'scripts/check_c_runtime_compat.py').read_bytes()
    vendor=ROOT/'third_party/dataclasses-0.8'
    provenance=json.loads((vendor/'provenance.json').read_bytes())
    require(provenance['wheel_sha256']=='0201d89fa866f68c8ebd9d08ee6ff50c0b255f8ec63a71c16fda7af82bb887bf',
            'dataclasses release identity differs')
    for name,expected in provenance['files'].items():
        raw_dependency=(vendor/safe_member(name)).read_bytes()
        require(sha(raw_dependency)==expected,'vendored dependency changed')
        files['vendor/dataclasses-0.8/'+name]=raw_dependency
    files['vendor/dataclasses-0.8/provenance.json']=(vendor/'provenance.json').read_bytes()
    model_results={}
    for kernel in KERNELS:
        module=source/'modules/board'/kernel
        manifest,image=validate(module,lock.read_bytes())
        require(sha(image)==summary['modules']['board_'+kernel]['image_sha256'],'board module differs from build receipt')
        require(sha((module/'manifest.json').read_bytes())==summary['modules']['board_'+kernel]['manifest_sha256'],'module manifest changed')
        for name in ('manifest.json',*manifest['files']):files['modules/'+kernel+'/'+name]=(module/name).read_bytes()
        records=[]
        for backend in ('simx','rtlsim','xrtsim'):
            item=next(r for r in summary['runs'] if r['kernel']==kernel and r['backend']==backend)
            path=ROOT/item['result'];require(sha(path.read_bytes())==item['result_sha256'],'model record changed')
            record=json.loads(path.read_bytes())
            for index,case in enumerate(record['cases']):
                for name,digest in case['files'].items():
                    require(sha((path.parent/('case-%02d'%index)/name).read_bytes())==digest,'model capture changed')
            records.append(record)
        model_results[kernel]=records[0]
    bundle=dict(run_id=run_id,nonce=uuid.uuid4().hex,source_run=source_run,source_summary_sha256=sha(raw),
                bdf=bdf,files=encode(files),model_results=model_results,runtime_hashes=RUNTIME_SHAS,xclbin_sha256=XCLBIN_SHA)
    code=Path(__file__).read_bytes()
    payload="""import base64,hashlib,json,zlib
code=base64.b64decode(%r)
assert hashlib.sha256(code).hexdigest()==%r
scope={'__name__':'c_runtime_remote'}
exec(compile(code,'c_runtime_board.py','exec'),scope)
bundle=json.loads(zlib.decompress(base64.b64decode(%r)))
result=scope['remote'](bundle)
result['script_sha256']=hashlib.sha256(code).hexdigest()
print('C_RUNTIME_BEGIN_'+bundle['nonce'])
print(json.dumps(result))
print('C_RUNTIME_END_'+bundle['nonce'])
"""%(base64.b64encode(code).decode('ascii'),sha(code),base64.b64encode(zlib.compress(json.dumps(bundle).encode())).decode('ascii'))
    run=ROOT/'results'/run_id;run.mkdir()
    (run/'payload.py').write_bytes(payload.encode('ascii'))
    (run/'preparation.json').write_text(json.dumps(dict(status='PASS',scope='offline preparation; no board access',
        run_id=run_id,nonce=bundle['nonce'],source_run=source_run,bdf=bdf,script_sha256=sha(code),
        payload_sha256=sha(payload.encode('ascii')),inputs={n:sha(v) for n,v in files.items()}),indent=2)+'\n')
    (run/'model_results.json').write_text(json.dumps(model_results,indent=2)+'\n')
    for name in ('c_runtime_board.py','wlan_ssh_proxy.py','Invoke-CU280Runtime.ps1'):
        shutil.copyfile(ROOT/'scripts'/name,run/name)
    print(str(run))


def unpack(run_id):
    require(re.fullmatch(r'c-u280-runtime-[A-Za-z0-9_.-]{1,70}',run_id),'invalid run_id')
    run=ROOT/'results'/run_id
    prep=json.loads((run/'preparation.json').read_text())
    text=(run/'probe.stdout').read_text(encoding='utf-8-sig')
    match=re.search(r'(?ms)^C_RUNTIME_BEGIN_'+prep['nonce']+r'\r?\n(.*?)^C_RUNTIME_END_'+prep['nonce']+r'\s*$',text)
    require(match is not None,'missing result frame')
    result=json.loads(match.group(1))
    for key in ('run_id','nonce','script_sha256','source_run','bdf'):require(result[key]==prep[key],'remote identity mismatch: '+key)
    (run/'remote-result.json').write_text(match.group(1))
    output=run/'returned';output.mkdir()
    decode_into(result.pop('export',{}),output)
    if result['status']=='PASS':
        models=json.loads((run/'model_results.json').read_text())
        require(result.get('passed')==41 and set(result['kernels'])==set(KERNELS),'unexpected physical coverage')
        for kernel in KERNELS:
            actual=json.loads((output/'execution'/kernel/'result.json').read_text())
            expected=models[kernel]
            require(actual['status']=='PASS' and actual['backend']=='u280-xrt'
                    and actual['image_sha256']==expected['image_sha256']
                    and len(actual['cases'])==len(expected['cases']),'returned kernel identity differs')
            for index,(left,right) in enumerate(zip(actual['cases'],expected['cases'])):
                for name,digest in left['files'].items():
                    safe_member(name)
                    require('/' not in name and sha((output/'execution'/kernel/('case-%02d'%index)/name).read_bytes())==digest,
                            'returned raw capture hash differs')
                require({k:v for k,v in left['files'].items() if k!='payload.bin'} ==
                        {k:v for k,v in right['files'].items() if k!='payload.bin'},'returned bytes differ from model')
            gate=json.loads((output/'binding/sessions'/kernel/'gate.json').read_text())
            require(gate['status']=='PASS' and gate['open_gate']=='PASS' and gate['close_gate']=='PASS','returned board gates differ')
    result['returned_files']={p.relative_to(output).as_posix():sha(p.read_bytes()) for p in output.rglob('*') if p.is_file()}
    (run/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:result.get(k) for k in ('status','passed','error')}))
    return result['exit_code']


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('prepare','unpack'))
    parser.add_argument('run_id')
    parser.add_argument('--source-run')
    parser.add_argument('--bdf',default='0000:b1:00.1')
    args=parser.parse_args()
    if args.action=='prepare':prepare(args.run_id,args.source_run,args.bdf)
    else:raise SystemExit(unpack(args.run_id))
