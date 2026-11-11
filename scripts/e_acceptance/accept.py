"""Independent E raw-byte, ABI and lane-level trace acceptance.

Only this directory's frozen mathematical oracle is imported. Producer PASS
labels, hash-only comparisons and producer trace analyzers are not criteria.
"""
import argparse
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
FROZEN = ROOT/'configs/acceptance/e-ptx15-v1'
FREEZE_SHA = 'f205a527c8bb6801ed7e2d416ea4a56236109e67c4b2323f851c4690d327e7d7'
ORACLE_SHA = 'da2df04b2f38e3adda0a9839aefec6ebdf549ddc3a2fe4f378fc369bcc016507'


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1048576), b''):
            h.update(chunk)
    return h.hexdigest()


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


require(sha(FROZEN/'oracle_v1.py') == ORACLE_SHA, 'oracle changed')
spec = importlib.util.spec_from_file_location('e_frozen_oracle', FROZEN/'oracle_v1.py')
oracle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oracle)


def frozen_cases():
    require(sha(FROZEN/'manifest.json') == FREEZE_SHA, 'frozen manifest changed')
    data = json.loads((FROZEN/'manifest.json').read_text())
    for case in data['cases']:
        inputs = {}
        for role, digest in case['inputs_sha256'].items():
            p = ROOT/'results/ptx-frontend-host-20261108-v3'/case['entry']/'inputs'/(case['id']+'_'+role+'.bin')
            require(sha(p) == digest, 'original input changed')
            inputs[role] = p.read_bytes()
        regenerated = oracle.expected_arrays(case['entry'],case,inputs)
        for role, digest in case['expected_sha256'].items():
            p = FROZEN/case['entry']/case['id']/(role+'.bin')
            require(sha(p) == digest and p.read_bytes() == regenerated[role], 'frozen answer changed')
    return data['cases']


def header_check(case, path):
    header = path.read_text()
    for key,value in {'n':case['n'],'grid':case['grid'],'block':32,
                      'buffer_bytes':case['words']*4,'guard_bytes':32,
                      'params_size':oracle.layout(case['entry'])['size']}.items():
        m = re.search(r'constexpr uint32_t '+key+r'\s*=\s*(\d+)\s*;',header)
        require(m and int(m[1]) == value, 'header '+key)
    require('"'+case['id']+'"' in header, 'header case id')
    for field in oracle.layout(case['entry'])['fields']:
        m=re.search(r'constexpr uint32_t '+field['name']+r'_offset\s*=\s*(\d+)\s*;',header)
        require(m and int(m[1]) == field['offset'], 'header ABI field '+field['name'])


def check_raw(case, output, log_path, exit_code):
    require(exit_code == 0, 'execution did not exit 0')
    roles = list(case['expected_sha256'])
    names = {case['id']+'_'+role+'.bin' for role in roles+['params']}
    require({p.name for p in output.iterdir() if p.is_file()} == names, 'missing or unexpected output')
    hashes = {}
    for role in roles:
        p = output/(case['id']+'_'+role+'.bin')
        expected = (FROZEN/case['entry']/case['id']/(role+'.bin')).read_bytes()
        actual = p.read_bytes()
        require(actual == expected, 'full array mismatch '+role+' (includes inputs and guards)')
        hashes[role] = sha(p)
    args, complete, captured, caps, entry = [],0,[],0,[]
    with log_path.open(encoding='utf-8',errors='strict') as stream:
        for line in stream:
            line=line.strip()
            if line.startswith('PTX_COPY_ARGS '):
                args.append({k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',line)})
            if line == 'CAPTURE_COMPLETE 1': complete += 1
            if line.startswith('CAPTURED '): captured.append(line)
            if line == 'CAPS threads=4 warps=8 cores=1': caps += 1
            if line.startswith('PTX_COPY_ENTRY '): entry.append(int(line.split()[1]))
    require(complete==1 and len(args)==1 and caps==1 and entry==[0x180000034], 'missing/duplicate completion, caps, entry or arguments')
    require(captured==['CAPTURED {id} n={n} block={block} grid={grid}'.format(**case)], 'launch metadata differs')
    fields = oracle.layout(case['entry'])['fields']
    require(set(args[0]) == {f['name'] for f in fields}, 'argument names')
    for f in fields:
        if f['type']=='u32':
            require(args[0][f['name']]==case[f['name']], 'argument scalar')
    bases = {role:args[0][role]-32 for role in roles}
    p = output/(case['id']+'_params.bin')
    oracle.validate_payload(case['entry'],case,p.read_bytes(),bases)
    return dict(status='PASS', array_sha256=hashes, payload_sha256=sha(p),
                pointers={role:args[0][role] for role in roles}, launch=dict(n=case['n'],block=32,grid=case['grid']))


def instruction_map(dump, entry):
    instructions = []
    for line in dump.read_text().splitlines():
        m = re.match(r'^([0-9a-f]+):\s+[0-9a-f]+\s+(\w+)\s+(.*)$',line)
        if m: instructions.append((int(m[1],16),m[2],m[3]))
    reads = [(pc,operands) for pc,op,operands in instructions if op in ('lw','lwu')]
    writes = [(pc,operands) for pc,op,operands in instructions if op=='sw']
    roles = ['x'] if entry=='copy_u32' else ['x','y']
    require(len(reads)==len(roles) and len(writes)==1, 'unexpected array disassembly')
    array = {pc:('LD',role) for (pc,_),role in zip(reads,roles)}
    array[writes[0][0]]=('ST','z')
    parameter = {}
    for pc,op,operand in instructions:
        if op=='lbu':
            m=re.search(r',\s*(0x[0-9a-f]+)\(a0\)',operand)
            require(m is not None,'unexpected byte-load base')
            parameter[pc]=int(m[1],16)
    used = 20 if entry=='copy_u32' else (28 if entry=='vadd_u32' else 32)
    require(sorted(parameter.values())==list(range(used)), 'parameter byte-read instruction coverage')
    return array,parameter


def check_trace(case, log_path, dump, pointers, backend):
    array_pcs, param_pcs = instruction_map(dump,case['entry'])
    dispatches=Counter(); accesses=Counter(); param_accesses=Counter()
    warp={}; cta={}; ranks={}; uuid={}
    first_request_count=0
    re_sim_dispatch=re.compile(r'dispatch CTA warp: cid=0, wid=(\d+), cta_id=(\d+), rank=(\d+)/8, tmask=1111, .*blockIdx=\((\d+),0\), mscratch=0x([0-9a-f]+)')
    re_rtl_cta=re.compile(r'kmu cta-fire: cta_id=(\d+), block_idx=\[(\d+),0,0\], .*param=0x([0-9a-f]+)')
    re_rtl_dispatch=re.compile(r'cta_dispatch dispatch: wid=(\d+), cta_id=(\d+), .*tmask=1111, .*init=[01]')
    re_sim_instruction=re.compile(r'pipeline decode: cid=0, wid=(\d+), cta_id=(\d+), .*PC=0x([0-9a-f]+).*\(#(\d+)\)')
    re_sim_req=re.compile(r'-lsu mem-req: op=(LD|ST), mask=([01]{4}), addr=\{([^}]+)\}.*\(#(\d+)\)')
    re_rtl_req=re.compile(r'-execute-lsu0 (Rd|Wr) Req: wid=(\d+), cta_id=(\d+), PC=0x([0-9a-f]+), tmask=([01]{4}), addr=\{([^}]+)\}')
    with log_path.open(encoding='utf-8') as stream:
        for line in stream:
            if backend=='simx':
                m=re_sim_dispatch.search(line)
                if m:
                    wid,ctaid,rank,block,param=[int(m[i],16 if i==5 else 10) for i in range(1,6)]
                    warp[wid]=(block,rank,param)
                    dispatches[(block,rank)]+=1
                m=re_sim_instruction.search(line)
                if m:
                    wid=int(m[1]); pc=int(m[3],16)
                    require(wid in warp,'instruction before dispatch')
                    uuid[int(m[4])]=(pc,warp[wid])
                m=re_sim_req.search(line)
                if not m: continue
                op,mask,addresses,uid=m.groups()
                require(int(uid) in uuid,'request missing instruction identity')
                pc,(block,rank,param)=uuid[int(uid)]
                values=[None if v.strip()=='-' else int(v,16) for v in addresses.split(',')]
            else:
                m=re_rtl_cta.search(line)
                if m:
                    ctaid,block,param=int(m[1]),int(m[2]),int(m[3],16)
                    cta[ctaid]=(block,param);ranks[ctaid]=0
                m=re_rtl_dispatch.search(line)
                if m:
                    wid,ctaid=int(m[1]),int(m[2])
                    require(ctaid in cta,'warp before CTA')
                    block,param=cta[ctaid];rank=ranks[ctaid];ranks[ctaid]+=1
                    warp[wid]=(block,rank,param);dispatches[(block,rank)]+=1
                m=re_rtl_req.search(line)
                if not m: continue
                kind,wid,ctaid,pc,mask,addresses=m.groups()
                pc=int(pc,16)
                # Do not silently discard a request before the first dispatch.
                # Cycle-one random diagnostics in these logs do not match this
                # precise execute-LSU request format.
                require(bool(warp),'LSU request before first dispatch')
                require(int(wid) in warp,'request before warp dispatch')
                block,rank,param=warp[int(wid)]
                op='LD' if kind=='Rd' else 'ST'
                values=list(reversed([int(v,16) for v in addresses.split(',')]))
            require(len(values)==4,'trace lane vector width')
            first_request_count+=1
            for lane,value in enumerate(values):
                # SimX BitVector streams low-to-high; RTL %b is high-to-low.
                active = mask[lane]=='1' if backend=='simx' else mask[3-lane]=='1'
                if not active: continue
                require(value is not None,'active lane missing address')
                i=block*32+rank*4+lane
                if pc in array_pcs:
                    expected_op,role=array_pcs[pc]
                    require(op==expected_op,'array instruction read/write differs')
                    require(i<case['n'],'false predicate issued array request')
                    require(value==pointers[role]+4*i,'array lane address mismatch')
                    accesses[(role,i)]+=1
                elif pc in param_pcs:
                    require(op=='LD' and value==param+param_pcs[pc], 'parameter byte address')
                    param_accesses[(i,param_pcs[pc])]+=1
                else:
                    for role,ptr in pointers.items():
                        require(not ptr-32<=value<ptr-32+case['words']*4,'unexpected array access PC')
    require(dispatches==Counter({(b,r):1 for b in range(case['grid']) for r in range(8)}),'CTA/rank dispatch coverage')
    require(accesses==Counter({(role,i):1 for role in pointers for i in range(case['n'])}),'array access multiplicity/coverage')
    # PTX parameter reads are pure. The compiler may sink unused pointer reads
    # beneath a false predicate, as the disassembly visibly does for x.
    # Every logical thread must nevertheless read all four bytes of N; active
    # threads must read every used field. Any observed read must be unique.
    n_offset = next(f['offset'] for f in oracle.layout(case['entry'])['fields'] if f['name']=='n')
    required = {(i,o) for i in range(case['grid']*32) for o in range(n_offset,n_offset+4)}
    required.update((i,o) for i in range(case['n']) for o in param_pcs.values())
    require(all(param_accesses[key]==1 for key in required),'parameter reads/actual launch coverage')
    require(all(0<=i<case['grid']*32 and o in param_pcs.values() and count==1
                for (i,o),count in param_accesses.items()),'duplicate/unexpected parameter read')
    return dict(status='PASS', array_reads=case['n']*(1 if case['entry']=='copy_u32' else 2),
        array_writes=case['n'], parameter_byte_lane_reads=sum(param_accesses.values()),
        logical_threads=32*case['grid'], dispatched_warps=sum(dispatches.values()),
        false_predicate_array_requests=0, raw_lsu_request_records=first_request_count,
        disassembly_sha256=sha(dump), log_sha256=sha(log_path))


def check_local(run):
    execution=json.loads((run/'execution.json').read_text())
    cases=frozen_cases()
    frozen_manifest=json.loads((FROZEN/'manifest.json').read_text())
    require(sha(ROOT/'configs/target_lock.json')==frozen_manifest['target_lock_sha256'],'root lock changed after oracle freeze')
    expected={(b,c['entry'],c['id']) for b in ('simx','rtlsim','noxrt') for c in cases}
    rows=execution['cases']
    require(len(rows)==45 and {(r['backend'],r['entry'],r['id']) for r in rows}==expected,'partial/duplicate/extra local execution')
    commands={c['label']:c for c in execution['commands']}
    require(len(commands)==len(execution['commands']), 'duplicate command labels')
    for path,digest in execution['identities']['source'].items():
        require(sha(ROOT/path)==digest,'source/lock identity changed')
    require(sha(ROOT/'configs/candidates/block32-v1/target_lock.json') ==
            '9bf1ecd89852e54dd402e669becbfd0910752ffd16ad9e7a9f9b20e77b6c4649','block32 candidate identity')
    require(sha(ROOT/'configs/candidates/u280-hbm32-v1/target_lock.json') ==
            'e55719ecaa83d1b0f637cf212819716c58667443918f822eaed9ee2eb2aa7486','U280 candidate identity')
    provenance={'simx':'ab-d6-trace-simx-20261108-v2','rtlsim':'ab-d6-trace-rtlsim-20261108-v1',
                'noxrt':'ab-d5-block32-20261108-v1-xrtsim'}
    for backend,archive_name in provenance.items():
        archive=ROOT/'results'/archive_name
        identity=json.loads((archive/'summary.json').read_text())
        for name,digest in execution['identities'][backend].items():
            stored=identity['build_artifacts']['sw/runtime/'+Path(name).name]
            require(digest==stored['sha256']==sha(archive/stored['review_copy']),'runtime archive identity')
    for entry in ('copy_u32','vadd_u32','affine_u32'):
        module=run/'modules'/entry
        case=next(c for c in cases if c['entry']==entry)
        require(sha(module/'frontend/source.ptx')==case['ptx_sha256']==sha(ROOT/'ptx/samples'/(entry+'.ptx')),'PTX source-to-image binding')
        for name,digest in execution['builds'][entry].items():
            if name in ('Makefile','kernel.cpp','kernel_body.hpp','kernel.elf','kernel.vxbin','kernel.dump'):
                require(sha(module/name)==digest,'rebuilt artifact changed')
        require(execution['builds'][entry]['kernel.vxbin']==execution['builds'][entry]['delivered_image'],'image reconstruction differs')
    for command in commands.values():
        require(command['exit_code']==0 and not command['timed_out'],'failed command '+command['label'])
        require(sha(run/command['stdout_stderr'])==command['log_sha256'],'command log changed')
    result=[]
    by_id={(c['entry'],c['id']):c for c in cases}
    for row in rows:
        case=by_id[(row['entry'],row['id'])];stage=run/row['directory']
        header_check(case,stage/'copy_case.hpp')
        for name,digest in row['hashes'].items():
            require(sha(stage/name)==digest,'source/binary identity changed')
        for role,digest in case['inputs_sha256'].items():
            require(sha(stage/'inputs'/(case['id']+'_'+role+'.bin'))==digest,'executed input changed')
        require(row['hashes']['kernel.vxbin']==execution['builds'][row['entry']]['delivered_image'],'delivered image differs')
        command=commands[row['run_label']]
        require(command['argv'][-3:]==['./host','inputs','output'],'unexpected executable/arguments')
        require('VORTEX_DRIVER='+('xrt' if row['backend']=='noxrt' else row['backend']) in command['argv'],'backend command mismatch')
        raw=check_raw(case,stage/'output',run/command['stdout_stderr'],command['exit_code'])
        if row['backend'] in ('simx','rtlsim'):
            trace=check_trace(case,run/command['stdout_stderr'],run/'modules'/row['entry']/'kernel.dump',raw['pointers'],row['backend'])
        else:
            trace={'status':'NOT_RUN','reason':'NOXRT release model does not provide D6 per-lane trace; output/ABI independently accepted'}
        result.append(dict(backend=row['backend'],entry=row['entry'],id=row['id'],raw=raw,trace=trace,
                           command=command,compile=commands[row['compile_label']]))
    return dict(status='PASS',scope='45 new runs: 15 each SimX, processor RTL, NOXRT AFU',
                image_reproduction=execution['builds'], cases=result,
                freeze_sha256=FREEZE_SHA, execution_sha256=sha(run/'execution.json'))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--local-run',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    try:
        result=check_local(args.local_run)
    except Exception as error:
        result={'status':'FAIL','error':repr(error)}
    (args.output/'result.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    print(result['status'],result.get('error',''))
    raise SystemExit(0 if result['status']=='PASS' else 1)
