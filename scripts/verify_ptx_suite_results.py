"""Recheck archived PTX suite captures without executing or importing the runtime.

Checks evidence consistency and recomputes arithmetic; this is not independent E
acceptance and does not replace a device rerun. Supports raw cases or ZIP/TGZ chunks.
"""
import argparse
import hashlib
import itertools
import json
from pathlib import Path
import struct
import tarfile
import zipfile


def verify(directory):
    root=Path(directory)
    result=json.loads((root/'result.json').read_text(encoding='utf-8'))
    backend=result['backend']
    assert result['schema_version'] in ('ptx-suite-simx-v1','ptx-suite-simulation-v2')
    assert backend in ('simx','rtlsim','xrtsim')
    assert result['schema_version']!='ptx-suite-simx-v1' or backend=='simx'
    assert result['status']=='PASS' and result['exit_code']==0
    assert result['caps']['backend']==backend
    assert result['u280']=='NOT_RUN' and result['independent_acceptance']=='NOT_RUN'
    kernel=result['kernel']
    assert kernel in ('copy','vadd','affine')
    blocks=result['blocks']
    assert blocks in ([1,4,7,16],[1,4,7,16,17,31,32])
    assert result['caps']['threads']*result['caps']['warps']==blocks[-1]
    lengths=[0,1,7,15,16,17,31,32,33,65,257,1024]
    alphas=[0,1,0xffffffff] if kernel=='affine' else [1]
    wanted=set(itertools.product(lengths,blocks,alphas,[0,1]))
    actual=set()
    archives=[]
    members={}
    try:
        for path in sorted(root.glob('cases-*.zip')):
            archive=zipfile.ZipFile(path)
            archives.append(archive)
            for name in archive.namelist():
                assert name not in members,'duplicate archive entry'
                members[name]=(archive,'zip')
        for path in sorted(root.glob('cases-*.tgz')):
            archive=tarfile.open(path,'r:gz')
            archives.append(archive)
            for member in archive.getmembers():
                assert member.isfile(),'only regular capture files are expected'
                assert member.name not in members,'duplicate archive entry'
                members[member.name]=(archive,'tar')
        def read(case,name):
            assert Path(name).name==name,'invalid capture filename'
            key='cases/'+case+'/'+name
            if not members:return (root/key).read_bytes()
            archive,kind=members[key]
            return archive.read(key) if kind=='zip' else archive.extractfile(key).read()
        for index,case in enumerate(result['cases']):
            assert case['id']=='%04d'%index and case['status']=='PASS'
            n,block,alpha,dataset=(case[k] for k in ('n','block','alpha','dataset'))
            signature=(n,block,alpha,dataset)
            assert signature in wanted and signature not in actual
            actual.add(signature)
            assert case['grid']==max(1,(n+block-1)//block)
            assert case['offset_bytes']==(32 if dataset==0 else 16)
            assert case['completion']['status']=='COMPLETE' and case['completion']['backend']==backend
            files={name:read(case['id'],name) for name in case['files']}
            for name,data in files.items():
                assert len(data)==1056*4 and hashlib.sha256(data).hexdigest()==case['files'][name],name
            required={'x.bin','z.bin','expected.bin','observed_x.bin','observed_z.bin'}
            if kernel!='copy':required|={'y.bin','observed_y.bin'}
            assert set(files)==required
            assert files['observed_x.bin']==files['x.bin']
            if kernel!='copy':assert files['observed_y.bin']==files['y.bin']
            x=struct.unpack('<1056I',files['x.bin'])
            y=struct.unpack('<1056I',files['y.bin']) if kernel!='copy' else None
            reference=list(struct.unpack('<1056I',files['z.bin']))
            first=case['offset_bytes']//4
            for i in range(first,first+n):
                reference[i]=(x[i] if kernel=='copy' else x[i]+y[i] if kernel=='vadd' else x[i]*alpha+y[i])%4294967296
            recomputed=struct.pack('<1056I',*reference)
            assert files['expected.bin']==recomputed and files['observed_z.bin']==recomputed
            times=case['host_timing_ns']
            assert set(times)=={'h2d','launch','wait','d2h','compare'}
            assert all(type(v) is int and v>=0 for v in times.values())
        assert actual==wanted and result['passed']==len(wanted)
        recovery=result['recovery']
        assert recovery['status']=='PASS' and recovery['timeout']['native_status']==7
        assert recovery['timeout']['device_state']=='NEEDS_RECOVERY'
        assert recovery['drained']['generation']==1 and recovery['drained']['isolated'] is True
        answer={'copy':'ffffffff','vadd':'01000000','affine':'03000000'}[kernel]
        assert recovery['observed_hex']==answer==recovery['expected_hex']
        rejected={r['check']:r['error']['code'] for r in result['rejections']}
        assert rejected['block-'+str(blocks[-1]+1)]=='E_LAUNCH_LIMIT'
        for label,code in [('second-module','E_BUSY'),('missing-parameter','E_PARAM_LAYOUT'),
                           ('unaligned-pointer','E_ADDRESS_RANGE'),('stale-module','E_MODULE_CORRUPT'),
                           ('stale-buffer','E_INVALID_BUFFER'),('stale-event','E_EVENT')]:assert rejected[label]==code
        assert result['timeout_caps']['first_error']==dict(native_status=7,phase='wait')
        return dict(status='PASS',run_id=result['run_id'],kernel=kernel,backend=backend,cases=len(wanted),
                    block32_cases=sum(c['block']==32 for c in result['cases']),rejections=len(rejected),
                    scope='capture hashes, recomputed arithmetic, guards, coverage and recovery metadata; not independent device execution')
    finally:
        for archive in archives:archive.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run',type=Path)
    args=parser.parse_args()
    print(json.dumps(verify(args.run),ensure_ascii=False))
