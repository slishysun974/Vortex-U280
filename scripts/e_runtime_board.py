"""Package E's frozen unseen corpus and return raw U280 evidence to E.

Uses existing D10/D12 artifacts and physical Context gates. No fault injection,
system installation, HOST changes, sudo, or automatic card recovery.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import uuid
import zlib

from c_runtime_board import encode, decode_into, require, sha

ROOT=Path(__file__).resolve().parents[1]


def remote(bundle):
    work=Path.home()/'vortex-e-runtime'/bundle['run_id']
    result=dict(schema='e-u280-unseen-transport-v1',status='FAIL',exit_code=1,
                run_id=bundle['run_id'],nonce=bundle['nonce'],bdf=bundle['bdf'],
                commands=[],board_execution='NOT_RUN',independent_acceptance='PENDING',
                physical_recovery='NOT_RUN',timing7='OPEN')
    def command(label,argv,env=None,timeout=30):
        item=dict(label=label,argv=[str(x) for x in argv],exit_code=None,timeout_seconds=timeout)
        result['commands'].append(item)
        start=time.monotonic()
        try:
            done=subprocess.run(item['argv'],cwd=str(work),env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout)
            item.update(exit_code=done.returncode,stdout=done.stdout.decode(errors='replace'),stderr=done.stderr.decode(errors='replace'))
        except subprocess.TimeoutExpired as error:
            item.update(timed_out=True,stdout=(error.stdout or b'').decode(errors='replace'),stderr=(error.stderr or b'').decode(errors='replace'))
        item['seconds']=time.monotonic()-start
        require(item['exit_code']==0,'command failed: '+label)
        return item
    try:
        work.mkdir(parents=True,exist_ok=False)
        decode_into(bundle['files'],work)
        env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',VORTEX_PROFILING='0')
        env.pop('XCL_EMULATION_MODE',None)
        env.pop('VORTEX_CP_POLL_TIMEOUT_S',None)
        python=shutil.which('python3')
        require(python is not None,'existing Python 3 required')
        probe=command('python_version',[python,'-B','-c','import sys,json; assert sys.version_info >= (3,6); print(json.dumps(list(sys.version_info[:3])))'])
        result['python_version']=json.loads(probe['stdout'])
        env['PYTHONPATH']=str(work/'scripts')
        if result['python_version'][:2]==[3,6]:env['PYTHONPATH']=str(work/'vendor/dataclasses-0.8')+':'+env['PYTHONPATH']
        # Validate every module on the actual host before any device access.
        for name in bundle['module_names']:
            # The build CLI uses argparse's Python >=3.7 required subparser
            # option. The validated library API supports the board's 3.6 host.
            precheck='import sys; from pathlib import Path; from ptx_module import validate; m,b=validate(Path(sys.argv[1]),Path(sys.argv[2]).read_bytes()); print(m["entry"],len(b))'
            command('validate_'+name,[python,'-B','-c',precheck,work/'modules'/name,work/'target_lock.json'],env)
        libs=Path.home()/'vortex-u280-runtime/u280-runtime-20261109-v4/build/lib'
        bit=Path.home()/'vortex-u280-builds/u280-link-20261109-103830-671/out/vortex_afu.xclbin'
        for name,expected in bundle['runtime_hashes'].items():require(sha((libs/name).read_bytes())==expected,'D12 identity mismatch')
        require(sha(bit.read_bytes())==bundle['xclbin_sha256'],'D10 identity mismatch')
        env.update(VORTEX_DRIVER='xrt',XCLBIN_PATH=str(bit),LD_LIBRARY_PATH=str(libs)+':'+env.get('LD_LIBRARY_PATH',''))
        for name in bundle['runtime_hashes']:
            item=command('ldd_'+name,['ldd',libs/name],env)
            require('not found' not in item['stdout'],'unresolved runtime dependency')
        query=work/'xrt_bdf'
        command('compile_bdf_query',['/opt/rh/devtoolset-9/root/usr/bin/g++','-std=c++17','-O2',
                '-I/opt/xilinx/xrt/include',work/'query.cpp','-L/opt/xilinx/xrt/lib','-lxrt_coreutil','-o',query],env,60)
        result['query_sha256']=sha(query.read_bytes())
        command('enumerate',['xbutil','examine','--format','JSON','--output',work/'devices.json'],env)
        devices=json.loads((work/'devices.json').read_text())['system']['host']['devices']
        indices=[i for i,d in enumerate(devices) if d['bdf']==bundle['bdf'] and d['is_ready']=='true']
        require(len(indices)==1,'selected BDF is not uniquely ready')
        result['xrt_index']=indices[0];env['XRT_DEVICE_INDEX']=str(indices[0])
        command('bind_physical',[python,'-B',work/'scripts/ptx_u280.py','--output',work/'binding',
                '--lock',work/'target_lock.json','--hardware',work/'hardware.json','--library-dir',libs,
                '--xclbin',bit,'--query',query,'--bdf',bundle['bdf'],'--index',str(indices[0])],env)
        result['board_execution']='FAIL'
        command('execute_e_unseen',[python,'-B',work/'scripts/e_acceptance/runtime_unseen_run.py',
                '--corpus',work/'corpus','--modules',work/'modules','--binding',work/'binding/binding.json',
                '--target-lock',work/'target_lock.json','--backend','u280-xrt','--out',work/'execution/e-unseen'],env,300)
        # Only execution/transport completion; correctness is signed by E locally.
        capture=json.loads((work/'execution/e-unseen/capture.json').read_text())
        require(capture['status']=='COMPLETE' and len(capture['cases'])==48,'incomplete E execution')
        gate=json.loads((work/'binding/sessions/e-unseen/gate.json').read_text())
        require(gate['status']=='PASS' and gate['open_gate']=='PASS' and gate['close_gate']=='PASS','physical gates failed')
        result.update(status='PASS',exit_code=0,board_execution='PASS',executions=48)
    except Exception as error:
        result['error']=repr(error)
    if work.is_dir():
        result['export']=encode({p.relative_to(work).as_posix():p.read_bytes() for p in work.rglob('*') if p.is_file()
                                 and (p.relative_to(work).parts[0] in ('execution','binding') or p.name=='devices.json')})
    return result


def prepare(args):
    from ptx_module import validate
    from ptx_u280 import RUNTIME_SHAS, XCLBIN_SHA, QUERY_SOURCE, BUSES
    require(re.fullmatch(r'e-u280-unseen-[A-Za-z0-9_.-]+',args.run_id),'invalid run id')
    require(args.bdf in ['0000:'+bus+':00.1' for bus in BUSES],'BDF not allowed')
    corpus=ROOT/'configs/acceptance/e-runtime-unseen-20261111-v1'
    sys_path=__import__('sys').path
    sys_path.insert(0,str(ROOT/'scripts/e_acceptance'))
    from runtime_unseen_common import corpus as verify_corpus, PRODUCTION, FROZEN_SHA256
    manifest=verify_corpus(corpus)
    files={}
    for name in (*PRODUCTION,'u280_board_smoke.py'):
        files['scripts/'+name]=(ROOT/'scripts'/name).read_bytes()
    for name in ('runtime_unseen_common.py','runtime_unseen_run.py','runtime_unseen_check.py'):
        files['scripts/e_acceptance/'+name]=(ROOT/'scripts/e_acceptance'/name).read_bytes()
    for path in corpus.rglob('*'):
        if path.is_file():files['corpus/'+path.relative_to(corpus).as_posix()]=path.read_bytes()
    lock=ROOT/'configs/candidates/u280-hbm32-v1/target_lock.json'
    files.update({'target_lock.json':lock.read_bytes(),'hardware.json':lock.with_name('fpga.json').read_bytes(),'query.cpp':QUERY_SOURCE.encode()})
    images={}
    for name in manifest['sources']:
        directory=args.modules/name
        mm,image=validate(directory,lock.read_bytes())
        require(sha((directory/'source.ptx').read_bytes())==manifest['sources'][name]['sha256'],'module source differs')
        images[name]=sha(image)
        for member in ('manifest.json',*mm['files']):files['modules/'+name+'/'+member]=(directory/member).read_bytes()
    # Require all three independently captured runs and current production bytes.
    local_receipts={}
    model_summary=json.loads((args.executions/'summary.json').read_bytes())
    require(model_summary['status']=='PASS','model run incomplete')
    for item in model_summary['commands']:
        require(item['exit_code']==0 and sha((args.executions/item['log']).read_bytes())==item['log_sha256'],
                'model command/log differs')
    for backend in ('simx','rtlsim','xrtsim'):
        directory=args.executions/backend
        raw=(directory/'capture.json').read_bytes();receipt=json.loads(raw)
        require(receipt['status']=='COMPLETE' and receipt['backend']==backend and len(receipt['cases'])==48,'missing model execution '+backend)
        require(receipt['manifest_sha256']==FROZEN_SHA256,'wrong model corpus')
        for name in PRODUCTION:require(receipt['implementation'][name]==sha(files['scripts/'+name]),'production differs since model execution')
        for name in images:require(receipt['modules'][name]['image_sha256']==images[name],'model/board image differs')
        acceptance=args.executions/(backend+'.acceptance.json')
        # Full independent checker is rerun before preparation by E; bind its raw receipt.
        require(acceptance.is_file(),'E acceptance receipt required: '+str(acceptance))
        accepted=json.loads(acceptance.read_bytes())
        require(accepted['status']=='PASS' and accepted['capture_sha256']==sha(raw),'E model acceptance failed or stale')
        for case in receipt['cases']:
            for name,expected in case['files'].items():
                require(sha((directory/case['id']/name).read_bytes())==expected,'model capture changed')
        local_receipts[backend]=dict(capture_sha256=sha(raw),acceptance_sha256=sha(acceptance.read_bytes()))
    vendor=ROOT/'third_party/dataclasses-0.8'
    provenance=json.loads((vendor/'provenance.json').read_bytes())
    for name,expected in provenance['files'].items():
        raw=(vendor/name).read_bytes();require(sha(raw)==expected,'vendor changed')
        files['vendor/dataclasses-0.8/'+name]=raw
    bundle=dict(run_id=args.run_id,nonce=uuid.uuid4().hex,bdf=args.bdf,files=encode(files),
                module_names=list(manifest['sources']),runtime_hashes=RUNTIME_SHAS,xclbin_sha256=XCLBIN_SHA)
    # Standalone bootstrap embeds its transport helpers before this module.
    common=(ROOT/'scripts/c_runtime_board.py').read_bytes()
    code=Path(__file__).read_bytes()
    payload="""import base64,hashlib,json,zlib,types,sys
common=base64.b64decode(%r)
assert hashlib.sha256(common).hexdigest()==%r
module=types.ModuleType('c_runtime_board')
exec(compile(common,'c_runtime_board.py','exec'),module.__dict__)
sys.modules['c_runtime_board']=module
code=base64.b64decode(%r)
assert hashlib.sha256(code).hexdigest()==%r
scope={'__name__':'e_runtime_remote','__file__':'/tmp/e_runtime_board.py'}
exec(compile(code,'e_runtime_board.py','exec'),scope)
bundle=json.loads(zlib.decompress(base64.b64decode(%r)))
result=scope['remote'](bundle)
result['script_sha256']=hashlib.sha256(code).hexdigest()
print('E_RUNTIME_BEGIN_'+bundle['nonce'])
print(json.dumps(result))
print('E_RUNTIME_END_'+bundle['nonce'])
"""%(base64.b64encode(common).decode('ascii'),sha(common),base64.b64encode(code).decode('ascii'),sha(code),
       base64.b64encode(zlib.compress(json.dumps(bundle).encode())).decode('ascii'))
    run=ROOT/'results'/args.run_id;run.mkdir(exist_ok=False)
    (run/'payload.py').write_bytes(payload.encode('ascii'))
    (run/'preparation.json').write_text(json.dumps(dict(status='PASS',scope='offline preparation',run_id=args.run_id,
        bdf=args.bdf,nonce=bundle['nonce'],script_sha256=sha(code),payload_sha256=sha(payload.encode('ascii')),
        corpus_sha256=FROZEN_SHA256,model_receipts=local_receipts,inputs={n:sha(v) for n,v in files.items()}),indent=2)+'\n')
    for name in ('e_runtime_board.py','wlan_ssh_proxy.py','Invoke-EUnseenU280.ps1'):
        shutil.copyfile(ROOT/'scripts'/name,run/name)
    print(str(run))


def unpack(args):
    run=ROOT/'results'/args.run_id
    prep=json.loads((run/'preparation.json').read_text())
    stdout=(run/'probe.stdout').read_text(encoding='utf-8-sig')
    match=re.search(r'(?ms)^E_RUNTIME_BEGIN_'+prep['nonce']+r'\r?\n(.*?)^E_RUNTIME_END_'+prep['nonce']+r'\s*$',stdout)
    require(match is not None,'missing result frame')
    result=json.loads(match.group(1))
    for key in ('run_id','nonce','bdf','script_sha256'):require(result[key]==prep[key],'transport identity mismatch')
    (run/'remote-result.json').write_text(match.group(1))
    output=run/'returned';output.mkdir(exist_ok=False)
    decode_into(result.pop('export',{}),output)
    result['returned_files']={p.relative_to(output).as_posix():sha(p.read_bytes()) for p in output.rglob('*') if p.is_file()}
    (run/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:result.get(k) for k in ('status','executions','error')}))
    return result['exit_code']


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('prepare','unpack'));parser.add_argument('run_id')
    parser.add_argument('--modules',type=Path);parser.add_argument('--executions',type=Path)
    parser.add_argument('--bdf',default='0000:b1:00.1')
    args=parser.parse_args()
    if args.action=='prepare':prepare(args)
    else:raise SystemExit(unpack(args))
