"""Compare identical PTX modules/captures across SimX, processor RTL and AFU.

Rechecks each capture first. Same-author differential evidence, not E acceptance.
"""
import argparse
import hashlib
import json
from pathlib import Path
from verify_ptx_suite_results import verify


def compare(directories):
    if len(directories)!=3:raise ValueError('exactly three backend runs required')
    results={}
    checks=[]
    for directory in directories:
        path=Path(directory)/'result.json'
        check=verify(directory)
        result=json.loads(path.read_text(encoding='utf-8'))
        if result['backend'] in results:raise ValueError('duplicate backend')
        results[result['backend']]=result
        checks.append(dict(check,result_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    if set(results)!={'simx','rtlsim','xrtsim'}:raise ValueError('missing backend')
    base=results['simx']
    for backend,result in results.items():
        for key in ('kernel','target_lock_hash','module_manifest_sha256','blocks','passed'):
            if result[key]!=base[key]:raise ValueError('different target/module/coverage: '+key)
        for left,right in zip(base['cases'],result['cases']):
            for key in ('id','n','block','grid','dataset','alpha','offset_bytes','files'):
                if left[key]!=right[key]:raise ValueError('capture differs: '+backend+'/'+left['id']+'/'+key)
    return dict(status='PASS',kernel=base['kernel'],identical_cases=base['passed'],backends=checks,
        scope='same module and target; identical raw inputs, expected outputs, observed inputs/outputs and guards; host timings excluded; not independent E or physical board acceptance')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('runs',type=Path,nargs=3)
    args=parser.parse_args()
    print(json.dumps(compare(args.runs),indent=2))
