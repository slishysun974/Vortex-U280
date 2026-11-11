"""Actual mutations of new-run evidence to challenge the E receiver."""
import argparse
import base64
import copy
import hashlib
import json
from pathlib import Path
import re
import shutil

import accept
import board


def write_json(path,data):
    path.write_text(json.dumps(data,indent=2,sort_keys=True)+'\n',encoding='utf-8')


def flip(path,index):
    data=bytearray(path.read_bytes());data[index]^=1;path.write_bytes(data)


def inject(local_run,board_run,out):
    out.mkdir(parents=True,exist_ok=False)
    cases=accept.frozen_cases();case=next(c for c in cases if c['entry']=='copy_u32' and c['id']=='0058')
    execution=json.loads((local_run/'execution.json').read_text())
    commands={c['label']:c for c in execution['commands']}
    rows=[]
    def attempt(name,fn,should_reject=True):
        try:
            fn(); rejected=False;reason=None
        except (ValueError,KeyError,FileNotFoundError) as error:
            rejected=True;reason=str(error)
        passed=rejected==should_reject
        rows.append(dict(name=name,status='PASS' if passed else 'FAIL',
                         expected_rejection=should_reject,rejected=rejected,reason=reason))
        print(name,rows[-1]['status'],reason or '',flush=True)
    source=local_run/'simx/copy_u32/0058/output'
    source_log=local_run/commands['simx_copy_u32_0058_run']['stdout_stderr']
    for name,mutation in [
        ('positive_raw',None),('output_data',('0058_z.bin',32)),
        ('prefix_sentinel',('0058_z.bin',0)),('suffix_sentinel',('0058_z.bin',191)),
        ('input_preservation',('0058_x.bin',36)),('parameter_n',('0058_params.bin',16)),
        ('parameter_pointer',('0058_params.bin',0)),('parameter_padding',('0058_params.bin',20)),
        ('missing_output','missing'),('extra_output','extra'),('truncated_output','short'),
        ('nonzero_execution_exit','exit'),('missing_completion','completion'),('wrong_launch','launch')]:
        stage=out/name;stage.mkdir();shutil.copytree(source,stage/'output')
        text='\n'.join(s for s in source_log.read_text().splitlines() if s.startswith(('PTX_COPY_','CAPS ','CAPTURE')))+'\n'
        if isinstance(mutation,tuple):flip(stage/'output'/mutation[0],mutation[1])
        if mutation=='missing':(stage/'output/0058_z.bin').unlink()
        if mutation=='extra':(stage/'output/extra.bin').write_bytes(b'x')
        if mutation=='short':(stage/'output/0058_z.bin').write_bytes(b'x')
        if mutation=='completion':text=text.replace('CAPTURE_COMPLETE 1\n','')
        if mutation=='launch':text=text.replace('block=32','block=16')
        (stage/'stdout.log').write_text(text,encoding='utf-8')
        code=7 if mutation=='exit' else 0
        attempt(name,lambda:accept.check_raw(case,stage/'output',stage/'stdout.log',code),mutation is not None)
    for name in ('partial_execution','duplicate_execution'):
        stage=out/name;stage.mkdir();data=copy.deepcopy(execution)
        if name=='partial_execution':data['cases'].pop()
        else:data['cases'][-1]=data['cases'][0]
        write_json(stage/'execution.json',data)
        attempt(name,lambda:accept.check_local(stage))
    tail=next(c for c in cases if c['entry']=='copy_u32' and c['id']=='0070')
    command=commands['rtlsim_copy_u32_0070_run'];log_path=local_run/command['stdout_stderr']
    raw=accept.check_raw(tail,local_run/'rtlsim/copy_u32/0070/output',log_path,0)
    trace_lines=log_path.read_text().splitlines(True)
    array_line=next(s for s in trace_lines if '-execute-lsu0 Rd Req:' in s and 'PC=0x180000140' in s)
    for name in ('positive_trace','request_before_dispatch','false_predicate_request','duplicate_array_request','missing_array_request','missing_dispatch'):
        stage=out/name;stage.mkdir();lines=list(trace_lines)
        if name=='request_before_dispatch':lines.insert(0,array_line)
        if name=='false_predicate_request':lines=[s.replace('PC=0x180000140, tmask=0001','PC=0x180000140, tmask=0011') for s in lines]
        if name=='duplicate_array_request':lines.insert(lines.index(array_line),array_line)
        if name=='missing_array_request':lines.remove(array_line)
        if name=='missing_dispatch':lines=[s for s in lines if 'cta_dispatch dispatch:' not in s]
        (stage/'trace.log').write_text(''.join(lines),encoding='utf-8')
        attempt(name,lambda:accept.check_trace(tail,stage/'trace.log',local_run/'modules/copy_u32/kernel.dump',raw['pointers'],'rtlsim'),name!='positive_trace')
    board_result=json.loads((board_run/'result.json').read_text())
    for name in ('board_wrong_clock','board_busy_after'):
        job=copy.deepcopy(board_result['jobs']['copy_u32-0058'])
        if name=='board_wrong_clock':
            report=json.loads(job['reports']['loaded']);report['devices'][0]['platforms'][0]['clocks'][0]['freq_mhz']='199'
            job['reports']['loaded']=json.dumps(report)
        else:job['sysfs']['after']['kdsstat']=job['sysfs']['after']['kdsstat'].replace('contexts:\t\t0','contexts:\t\t1')
        stage=out/name;stage.mkdir();write_json(stage/'job.json',job)
        attempt(name,lambda:board.check_gates(job))
    # Update producer output SHA, expected SHA, result.json and raw SSH JSON
    # together. The independent frozen byte oracle must still reject the data.
    stage=out/'board_self_consistent_hash_forgery';shutil.copytree(board_run,stage)
    data=copy.deepcopy(board_result);item=data['jobs']['copy_u32-0058']['outputs']['0058_z.bin']
    changed=bytearray(base64.b64decode(item['base64']));changed[32]^=1
    item['base64']=base64.b64encode(changed).decode();item['sha256']=hashlib.sha256(changed).hexdigest();item['expected_sha256']=item['sha256']
    # Preserve run directory identity by nesting the exact original run name.
    nested=stage/board_run.name;nested.mkdir()
    for p in list(stage.iterdir()):
        if p.is_file():shutil.copyfile(p,nested/p.name)
    write_json(nested/'result.json',data)
    (nested/'probe.stdout').write_text('U280_SMOKE_BEGIN_'+data['nonce']+'\n'+json.dumps(data,indent=2)+'\nU280_SMOKE_END_'+data['nonce']+'\n',encoding='utf-8')
    attempt('board_self_consistent_hash_forgery',lambda:board.check_board(nested,stage/'extracted',local_run))
    result=dict(status='PASS' if all(r['status']=='PASS' for r in rows) else 'FAIL',
                scope='Receiver fault injection, not device error recovery or DUT invalid-input API testing',
                positive_controls=sum(not r['expected_rejection'] for r in rows),
                negative_cases=sum(r['expected_rejection'] for r in rows),cases=rows)
    write_json(out/'result.json',result)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--local-run',type=Path,required=True)
    parser.add_argument('--board-run',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    result=inject(args.local_run,args.board_run,args.output)
    raise SystemExit(result['status']!='PASS')
