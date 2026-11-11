"""Receive the new U280 run without using its producer's comparisons."""
import ast
import base64
import datetime
import hashlib
import json
from pathlib import Path
import re
import zlib

from accept import ROOT, frozen_cases, header_check, check_raw, require, sha

SCRIPT_SHA='9404ec6cb12964d88e12c440ad9b8c434c834d5353bf46fbfbb813cbc4d27b7e'
ARTIFACTS={
    'vortex_afu.xclbin':'bbac2ab73073b24ba857fb34eadf22bf1c11dc745527f064c4eec61b70d2c843',
    'libvortex.so':'d3538d2fc7c695a4a0102106aa45e9ef7a9e939fc44c3b15c547ff97d0dffe3e',
    'libvortex-xrt.so':'250769482e98c1cee84bd165a9e2af1c7b3f74a5b77dcf389ac1f4ea5aa7a8c1',
}
UUID='b60ca9fb-1506-3033-c156-e03ff687f492'
SHELL='fb2b2c5a19ed63593fea95f51fbc8eb9'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def decode_bundle(payload):
    # Read constant payload data only; never import or execute producer code.
    tree=ast.parse(payload.read_text())
    assignments={n.targets[0].id:n.value for n in tree.body if isinstance(n,ast.Assign)
                 and len(n.targets)==1 and isinstance(n.targets[0],ast.Name)}
    def encoded(name):
        strings=[n.value for n in ast.walk(assignments[name])
                 if isinstance(n,ast.Constant) and isinstance(n.value,str)]
        return base64.b64decode(max(strings,key=len),validate=True)
    script=encoded('script')
    require(digest(script)==SCRIPT_SHA,'embedded execution script changed')
    return json.loads(zlib.decompress(encoded('bundle')))


def idle_snapshot(snapshot):
    require(snapshot['ready']=='0x1','card not ready')
    require(SHELL in snapshot['interface_uuids'].lower().replace('-','').split(),'shell interface mismatch')
    require(int(snapshot['host_mem_size'])>=268435456,'HOST below 256 MiB')
    kds=snapshot['kdsstat']
    for key in ('outstanding execs','contexts'):
        require(re.search(r'^'+key+r':\s*0\s*$',kds,re.M),'KDS not idle: '+key)
    require(re.search(r'^client pid:\s*\Z',kds,re.M),'KDS client still present')


def check_gates(job):
    commands={c['label']:c for c in job['commands']}
    require(len(commands)==len(job['commands']),'duplicate board command')
    bdf=job['selected_bdf']; bus=bdf.split(':')[1]
    require(bdf=='0000:b1:00.1','unexpected acceptance card')
    for label,record in commands.items():
        if label.endswith('_holders'):
            require(record['exit_code']==1 and not record['stdout'].strip() and not record['stderr'].strip(),'visible holder check')
        else:
            require(record['exit_code']==0 and not record.get('timed_out',False),'board command failed '+label)
    for label in (bus+'_before_report',bus+'_immediately_before_open','after'):
        idle_snapshot(job['sysfs'][label])
    loaded=job['sysfs']['loaded']
    require(loaded['xclbinuuid'].lower()==UUID and int(loaded['host_mem_size'])>=268435456,'loaded image/HOST')
    enumeration=json.loads(job['reports']['device_list'])['system']['host']
    require(enumeration['devices'][job['xrt_index']]['bdf']==bdf,'XRT ordinal to BDF mapping')
    require(enumeration['devices'][job['xrt_index']]['is_ready']=='true','XRT enumeration readiness')
    require(enumeration['xrt']['version']=='2.13.479','XRT identity changed')
    for label in (bus+'_preflight','loaded'):
        devices=json.loads(job['reports'][label])['devices']
        require(len(devices)==1 and devices[0]['device_id']==bdf,'report BDF')
        device=devices[0]
        require(device['platforms'][0]['static_region']['vbnv']=='xilinx_u280_gen3x16_xdma_base_1','platform shell')
        require(device['pcie_info']['enabled_host_mem_size_bytes']=='256 MB','report enabled HOST')
        if label=='loaded':
            clocks=[c for c in device['platforms'][0]['clocks'] if c['id']=='DATA_CLK']
            require(len(clocks)==1 and int(clocks[0]['freq_mhz'])==200,'actual DATA_CLK')
            require(device['dynamic_regions'][0]['xclbin_uuid'].lower()==UUID,'report image UUID')
    require(len(job['clock_sysfs'])==1,'clock sysfs missing or ambiguous')
    path,frequencies=next(iter(job['clock_sysfs'].items()))
    require('/'+bdf+'/' in path and frequencies.split()==['200','500','450','0'],'driver clock readback')
    require({Path(p).name:h for p,h in job['artifact_sha256'].items()}==ARTIFACTS,'runtime/xclbin identities')
    return commands


def check_board(run, extracted, local_run):
    extracted.mkdir(parents=True,exist_ok=False)
    result=json.loads((run/'result.json').read_text(encoding='utf-8-sig'))
    preparation=json.loads((run/'preparation.json').read_text(encoding='utf-8-sig'))
    transport=json.loads((run/'transport.json').read_text(encoding='utf-8-sig'))
    bundle=decode_bundle(run/'payload.py')
    require(transport['ssh_exit_code']==0 and transport['exit_code']==0,'SSH/collection not complete')
    require(sha(run/'payload.py')==preparation['payload_sha256'],'payload identity')
    require(sha(run/'u280_board_smoke.py')==SCRIPT_SHA==result['script_sha256']==preparation['script_sha256'],'executed script identity')
    require(sha(run/'Invoke-U280BoardSmoke.ps1')==sha(ROOT/'scripts/Invoke-U280BoardSmoke.ps1'),'PowerShell entry changed')
    require(result['run_id']==bundle['run_id']==preparation['run_id']==transport['run_id']==run.name,'run identity')
    require(result['nonce']==bundle['nonce']==preparation['nonce'],'run nonce identity')
    lines=(run/'probe.stdout').read_text().splitlines()
    begin='U280_SMOKE_BEGIN_'+result['nonce'];end='U280_SMOKE_END_'+result['nonce']
    require(lines.count(begin)==1 and lines.count(end)==1,'raw transport result boundaries')
    raw_result=json.loads('\n'.join(lines[lines.index(begin)+1:lines.index(end)]))
    require(raw_result==result,'result differs from raw SSH return')
    cases=frozen_cases(); expected={c['entry']+'-'+c['id'] for c in cases}
    require(set(result['jobs'])==expected and len(bundle['jobs'])==15,'partial/extra board execution')
    prepared={j['ptx']['entry']+'-'+j['cases'][0]:j for j in bundle['jobs']}
    require(set(prepared)==expected,'input bundle cases differ')
    rows=[]
    for case in cases:
        entry,cid=case['entry'],case['id'];key=entry+'-'+cid
        job=result['jobs'][key];source=prepared[key]
        commands=check_gates(job)
        require(job['run_id']==run.name+'-'+key and job['nonce']==result['nonce'],'job identity')
        require(job['remote_directory'].endswith('/'+job['run_id']),'remote isolated directory')
        command=commands[entry]
        require(command['argv']==['./smoke','inputs','output'],'board executable/arguments')
        require(command['stderr'].splitlines()==['XRT index '+str(job['xrt_index'])+' BDF '+job['selected_bdf'],'U280_SMOKE_DEVICE_OPEN'],'board open gate output')
        compile_command=commands['host_compile']
        require(compile_command['argv'][0]=='/opt/rh/devtoolset-9/root/usr/bin/g++' and
                compile_command['argv'][-2:]==['-o','smoke'] and 'gate.cpp' in compile_command['argv'],'board compilation identity')
        contract=source['ptx']
        require(contract['sim_lock_sha256']==sha(ROOT/'configs/candidates/block32-v1/target_lock.json') and
                contract['u280_lock_sha256']==sha(ROOT/'configs/candidates/u280-hbm32-v1/target_lock.json'),'board lock binding')
        stage=extracted/key;stage.mkdir();(stage/'output').mkdir();(stage/'source').mkdir()
        for name,item in source['files'].items():
            raw=base64.b64decode(item['base64'],validate=True)
            require(digest(raw)==item['sha256'],'encoded board input identity')
            if name=='kernel.vxbin':
                require(raw==(local_run/'modules'/entry/'kernel.vxbin').read_bytes(),'board image is not independently rebuilt image')
            elif name.startswith('inputs/'):
                role=Path(name).stem.rsplit('_',1)[1]
                require(digest(raw)==case['inputs_sha256'][role],'board original input changed')
            elif name in ('source/main.cpp','source/copy_case.hpp'):
                reference=(local_run/'simx'/entry/cid/Path(name).name).read_bytes()
                if name=='source/copy_case.hpp' and entry=='copy_u32':
                    # The board packager adds unused generic metadata to the
                    # original copy header. Permit exactly these declarations;
                    # the compiled main.cpp is identical and never names them.
                    extra=('struct BufferSpec { const char* name; uint32_t offset; };\n'
                           'struct ScalarSpec { const char* name; uint32_t offset; uint32_t value; };\n'
                           'constexpr std::array<BufferSpec, 2> buffers{{\n'
                           '  {"x", x_offset},\n  {"z", z_offset},\n}};\n'
                           'constexpr std::array<ScalarSpec, 1> scalars{{\n'
                           '  {"n", n_offset, '+str(case['n'])+'u},\n}};\n')
                    normalized=raw.decode().replace('#include <array>\n','').replace('constexpr char entry[] = "copy_u32";\n','').replace(extra,'')
                    require(normalized.encode()==reference,'board copy header differs beyond unused metadata')
                else:
                    require(raw==reference,'board host source differs from local DUT')
            elif name=='resolved.cflags':
                flags=raw.decode().split()
                require(all(flag in compile_command['argv'] for flag in flags),'compiled flags differ from delivered flags')
                for flag in ('-DVX_CFG_XLEN=64','-DVX_CFG_NUM_WARPS=8','-DVX_CFG_NUM_THREADS=4','-DVX_CFG_PLATFORM_CLOCK_RATE=200'):
                    require(flag in flags,'missing fixed candidate flag '+flag)
            p=stage/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
        header_check(case,stage/'source/copy_case.hpp')
        require(set(job['outputs'])=={cid+'_'+r+'.bin' for r in case['expected_sha256']},'missing/extra board raw array')
        for name,item in job['outputs'].items():
            (stage/'output'/name).write_bytes(base64.b64decode(item['base64'],validate=True))
        (stage/'output'/(cid+'_params.bin')).write_bytes(base64.b64decode(job['ptx_launch']['payload_base64'],validate=True))
        (stage/'run.stdout').write_bytes(command['stdout'].encode('utf-8'))
        (stage/'run.stderr').write_bytes(command['stderr'].encode('utf-8'))
        raw=check_raw(case,stage/'output',stage/'run.stdout',command['exit_code'])
        rows.append(dict(entry=entry,id=cid,status='PASS',raw=raw,command=command,
                         compile=compile_command,card=job['selected_bdf'],xrt_index=job['xrt_index'],
                         data_clock_mhz=200,host_bytes=268435456,loaded_uuid=UUID,
                         identities=job['artifact_sha256'], gate_scope='KDS plus ordinary-account visible holders; no exclusive reservation'))
    return dict(status='PASS',scope='15 new U280 runs: raw arrays, ABI, execution and card gates',
                cases=rows,run_id=run.name,script_sha256=SCRIPT_SHA,
                result_sha256=sha(run/'result.json'),transport_sha256=sha(run/'transport.json'),
                payload_sha256=sha(run/'payload.py'),per_lane_trace='NOT_RUN on physical board; independently checked on SimX and processor RTL')


def check_post_artifacts(artifacts_run, board_run, board_extracted, destination):
    destination.mkdir(parents=True,exist_ok=False)
    post=json.loads((artifacts_run/'result.json').read_text())
    prep=json.loads((artifacts_run/'preparation.json').read_text())
    transport=json.loads((artifacts_run/'transport.json').read_text(encoding='utf-8-sig'))
    original=json.loads((board_run/'result.json').read_text())
    require(prep['board_result_sha256']==sha(board_run/'result.json'),'post-run evidence bound to another run')
    require(prep['board_run']==board_run.name and post['nonce']==prep['nonce'],'post-run identity')
    require(transport['ssh_exit_code']==0 and transport['exit_code']==0,'post-run SSH failed')
    require(sha(artifacts_run/'payload.py')==prep['payload_sha256'],'post-run collector payload identity')
    lines=(artifacts_run/'probe.stdout').read_text().splitlines()
    begin='E_ARTIFACTS_BEGIN_'+post['nonce'];end='E_ARTIFACTS_END_'+post['nonce']
    require(lines.count(begin)==1 and lines.count(end)==1,'post-run raw boundaries')
    require(json.loads('\n'.join(lines[lines.index(begin)+1:lines.index(end)]))==post,'post-run result differs from raw return')
    require(set(post['jobs'])==set(original['jobs'])==set(prep['jobs']),'post-run partial job set')
    tree=ast.parse((board_run/'u280_board_smoke.py').read_text())
    gate=next(ast.literal_eval(n.value).encode() for n in tree.body if isinstance(n,ast.Assign)
              and any(isinstance(t,ast.Name) and t.id=='GATE_SOURCE' for t in n.targets))
    rows=[]
    required={'gate.cpp','include/vortex2.h','kernel.vxbin','resolved.cflags','smoke','smoke.stderr',
              'smoke.stdout','source/copy_case.hpp','source/main.cpp'}
    for key,job in post['jobs'].items():
        original_job=original['jobs'][key]
        require(job['directory']==original_job['remote_directory']==prep['jobs'][key],'post-run directory mismatch')
        require(set(job['files'])==required,'post-run artifact set incomplete')
        hashes={}
        for name,meta in job['files'].items():
            raw=base64.b64decode(meta['base64'],validate=True)
            require(digest(raw)==meta['sha256'] and len(raw)==meta['bytes'],'post-run artifact bytes/hash mismatch')
            if name=='gate.cpp':require(raw==gate,'post-run gate source differs')
            elif name=='smoke':
                require(raw[:4]==b'\x7fELF','post-run host is not ELF')
                started=datetime.datetime.fromisoformat(original_job['started_at']).timestamp()
                finished=datetime.datetime.fromisoformat(original_job['finished_at']).timestamp()
                require(started-1<=meta['mtime_ns']/1e9<=finished+1,'host binary mtime outside run interval')
            elif name in ('smoke.stdout','smoke.stderr'):
                suffix=name.split('.')[1]
                require(raw==(board_extracted/key/('run.'+suffix)).read_bytes(),'post-run host log differs')
            else:
                require(raw==(board_extracted/key/name).read_bytes(),'post-run input/source differs')
            p=destination/key/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
            hashes[name]=meta['sha256']
        rows.append(dict(job=key,sha256=hashes,host_stat={k:v for k,v in job['files']['smoke'].items() if k!='base64'}))
    return dict(status='PASS',files=135,jobs=rows,result_sha256=sha(artifacts_run/'result.json'),
                scope='Post-run originals and hashes; source/image/log bytes match execution package/return. Host mtime lies in run interval. This is not an execution-time hash measurement.')
