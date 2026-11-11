"""Snapshot current project scripts, run host tests, and verify protected inputs."""
import argparse
import json
import os
from pathlib import Path
import re
import sys
from run_native_smoke import PROJECT, Recorder, sha256, utc_now


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id',required=True);args=parser.parse_args()
    if not re.fullmatch(r'c-runtime-closeout-[A-Za-z0-9_.-]+',args.run_id):raise ValueError('invalid run id')
    run=PROJECT/'results'/args.run_id;run.mkdir(exist_ok=False)
    summary=dict(status='RUNNING',commands=[],run_id=args.run_id,started_at=utc_now(),
                 scope='Python runner tests and protected source integrity only; not RTL or board execution')
    env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',VORTEX_SOURCE='/opt/vortex-ab/sources/vortex-7fe19369587c-v1')
    recorder=Recorder(run,summary,env)
    try:
        protected=json.loads((PROJECT/'results/c-runtime-import-20261111-v1/result.json').read_bytes())['protected']
        protected.update({'configs/acceptance/e-ptx15-v1/manifest.json':'f205a527c8bb6801ed7e2d416ea4a56236109e67c4b2323f851c4690d327e7d7',
            'configs/acceptance/e-ptx15-v1/oracle_v1.py':'da2df04b2f38e3adda0a9839aefec6ebdf549ddc3a2fe4f378fc369bcc016507',
            'configs/acceptance/e-runtime-unseen-20261111-v1/manifest.json':'ee47fa9d641a1c94f35666610d4910924c233fb83f13b1e859c26ce3de95a654'})
        summary['protected']=protected
        paths=list((PROJECT/'scripts').glob('*.py'))+list((PROJECT/'scripts/e_acceptance').glob('*.py'))+list((PROJECT/'tests').glob('*.py'))
        summary['implementation']={}
        for path in paths:
            rel=path.relative_to(PROJECT);dest=run/'implementation'/rel
            dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(path.read_bytes())
            summary['implementation'][rel.as_posix()]=sha256(path)
        for p,h in protected.items():
            if sha256(PROJECT/p)!=h:raise ValueError('protected bytes changed: '+p)
        record,output=recorder.command('unittest',[sys.executable,'-B','-m','unittest','discover','-s','tests','-v'],PROJECT,300)
        if record['returncode']!=0 or record['timed_out']:raise ValueError('selftests failed')
        for p,h in dict(protected,**summary['implementation']).items():
            if sha256(PROJECT/p)!=h:raise ValueError('source changed during checks: '+p)
        summary.update(status='PASS',exit_code=0)
    except Exception as error:
        summary.update(status='FAIL',exit_code=1,error=repr(error))
    summary['finished_at']=utc_now();recorder.save()
    print(json.dumps({k:summary.get(k) for k in ('status','exit_code','error')}))
    return summary['exit_code']


if __name__=='__main__':sys.exit(main())
