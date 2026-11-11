"""Validate all prepared boundary inputs and replay five gated hosts locally."""
import argparse
import ast
import base64
import json
import os
import re
import shutil
import zlib

from run_native_smoke import PROJECT, Recorder, sha256, utc_now
from run_ptx_copy import backend_libraries, read_json, require, run_stage, write_json
from u280_board_smoke import compare_outputs, verify_ptx_launch


def execute(out, prepared, recorder):
    prep = read_json(prepared / 'preparation.json')
    payload = (prepared / 'payload.py').read_bytes()
    worker = (prepared / 'u280_board_smoke.py').read_bytes()
    require(sha256(prepared / 'payload.py') == prep['payload_sha256'] and
            sha256(prepared / 'u280_board_smoke.py') == prep['script_sha256'], 'prepared identity changed')
    ast.parse(worker, feature_version=(3, 6))
    ast.parse(payload, feature_version=(3, 6))
    encoded = re.search(rb"(?m)^bundle = json.loads\(zlib.decompress\(base64.b64decode\('([A-Za-z0-9+/=]+)'\)\)\)$", payload)
    require(encoded and base64.b64encode(worker) in payload, 'embedded worker/bundle changed')
    bundle = json.loads(zlib.decompress(base64.b64decode(encoded[1], validate=True)))
    require(bundle['boundary_plan'] == prep['boundary_plan'] and bundle['source_run'] == prep['source_run'] and
            bundle['nonce'] == prep['nonce'] and len(bundle['jobs']) == len(prep['jobs']) == 67, 'payload plan changed')
    files = 0
    selected = []
    for job, record in zip(bundle['jobs'], prep['jobs']):
        require({k: v for k, v in job.items() if k != 'files'} == {k: v for k, v in record.items() if k != 'inputs'},
                'payload job contract differs')
        require(set(job['files']) == set(record['inputs']), 'payload members differ')
        for name, member in job['files'].items():
            raw = base64.b64decode(member['base64'], validate=True)
            import hashlib
            require(hashlib.sha256(raw).hexdigest() == member['sha256'] == record['inputs'][name], 'payload bytes changed')
            files += 1
        c = job['ptx']['case']
        entry = job['ptx']['entry']
        if (c['n'] == 1024 and c['block'] == 32 and c['alpha'] == (0xffffffff if entry == 'affine_u32' else 1)) or (
                c['n'] == 65 and ((entry == 'copy_u32' and c['block'] == 1) or (entry == 'affine_u32' and c['block'] == 31))):
            selected.append(job)
    require(len(selected) == 5, 'replay coverage mismatch')
    namespace = {'__name__': 'offline_board_worker'}
    exec(compile(worker, 'u280_board_smoke.py', 'exec'), namespace)
    libraries = {b: backend_libraries(b) for b in ('simx', 'rtlsim')}
    recorder.summary.update(packaged_files=files, packaged_cases=67,
                            libraries={b: h for b, (_, h) in libraries.items()})
    for job in selected:
        label = job['ptx']['entry'] + '_' + job['cases'][0]
        work = out / label
        work.mkdir()
        for name, item in job['files'].items():
            require(not name.startswith('/') and '..' not in name.split('/'), 'unsafe bundle member')
            path = work / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(base64.b64decode(item['base64'], validate=True))
        (work / 'gate.cpp').write_text(namespace['GATE_SOURCE'])
        stub = work / 'stub/xrt/xrt_device.h'
        stub.parent.mkdir(parents=True)
        stub.write_text('''#pragma once
#include <string>
namespace xrt { namespace info { namespace device { struct bdf {}; } }
class device { public: explicit device(unsigned) {} template<class T>
std::string get_info() const { return "0000:b1:00.1"; } }; }
''')
        host = work / 'host'
        run_stage(recorder, label + '_compile', ['g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror',
                  '-Iinclude', '-Istub', *(work / 'resolved.cflags').read_text().split(), 'gate.cpp',
                  '-L' + str(libraries['simx'][0]), '-lvortex', '-pthread', '-o', host], work)
        for backend, (lib, _) in libraries.items():
            stage = work / backend
            (stage / 'output').mkdir(parents=True)
            shutil.copy2(work / 'kernel.vxbin', stage)
            env = ['env', 'VORTEX_DRIVER=' + backend, 'LD_LIBRARY_PATH=' + str(lib), 'VORTEX_PROFILING=0', 'XRT_DEVICE_INDEX=3']
            argv = [host, work / 'inputs', stage / 'output']
            if backend == 'simx':
                command, raw = recorder.command(label + '_wrong_bdf', env + ['U280_EXPECTED_BDF=0000:b4:00.1'] + argv, stage)
                require(command['returncode'] == 2 and not command['timed_out'] and 'U280_SMOKE_DEVICE_OPEN' not in raw and
                        not list((stage / 'output').iterdir()), 'wrong BDF not rejected before open')
            raw = run_stage(recorder, label + '_' + backend, ['bash', '-c', 'printf R | exec "$@"', 'gate-input',
                *env, 'U280_EXPECTED_BDF=0000:b1:00.1', *argv], stage, timeout=120)
            require(raw.splitlines().count('CAPTURE_COMPLETE 1') == 1 and 'U280_SMOKE_DEVICE_OPEN' in raw, 'missing completion/gate')
            comparison = dict(outputs={}, case_results={})
            compare_outputs(stage, job, comparison, raw)
            verify_ptx_launch(stage, job, comparison, raw)
            require(comparison['passed_cases'] == 1 and not comparison['unexpected_outputs'], 'prepared output mismatch')
            write_json(stage / 'comparison.json', comparison)
        recorder.summary['replays'].append(dict(entry=job['ptx']['entry'], case=job['ptx']['case'],
                                               simx='PASS', rtlsim='PASS', wrong_bdf='REJECTED_BEFORE_OPEN'))
        recorder.save()
        print(label, 'two-backend replay PASS', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared-run', required=True)
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    for value in (args.prepared_run, args.run_id):
        require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{1,95}', value), 'unsafe run id')
    out = PROJECT / 'results' / args.run_id
    out.mkdir()
    summary = dict(status='FAIL', commands=[], replays=[], started_at=utc_now(), board_execution='NOT_RUN',
                   scope='exact prepared host replay; XRT BDF query is a stub, not real XRT/board validation')
    recorder = Recorder(out, summary, dict(os.environ))
    try:
        shutil.copy2(__file__, out)
        execute(out, PROJECT / 'results' / args.prepared_run, recorder)
        summary['status'] = 'PASS'
    except (OSError, RuntimeError, ValueError, KeyError) as error:
        summary['error'] = repr(error)
    finally:
        summary.update(finished_at=utc_now(), exit_code=0 if summary['status'] == 'PASS' else 1)
        recorder.save()
    print(summary['status'], summary.get('error', ''), flush=True)
    return summary['exit_code']


if __name__ == '__main__':
    raise SystemExit(main())
