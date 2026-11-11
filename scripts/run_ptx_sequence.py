"""Exercise 30 PTX launches in one device/queue with two buffer generations."""
import argparse
import itertools
import os
from pathlib import Path
import re
import shutil

from run_native_smoke import PROJECT, Recorder, sha256, utc_now
from run_ptx_copy import (BOARD_LOCK, CORPUS_HASHES, FRONTEND_RUN, SIM_LOCK, VORTEX,
                          BUILDS, read_json, require, run_stage, vxbin_entry, write_json)
from run_ptx_copy_trace import (IMAGE_RUN, LOAD_PC, STORE_PC, PARAM_PC,
                                analyze_trace, trace_libraries)
from run_ptx_arithmetic import instruction_sites
from ptx_sequence_contract import verify_capture
from ptx_sequence_trace import bind_rtl_dispatches

FROZEN = PROJECT / 'configs/acceptance/e-ptx15-v1'
FREEZE_SHA = 'f205a527c8bb6801ed7e2d416ea4a56236109e67c4b2323f851c4690d327e7d7'
IMAGES = {
    'copy_u32': (IMAGE_RUN / 'module', '78fdf5306a53d78e81420a85b26d913adc52333b9f5e580441b9c9abd0fb25c0'),
    'vadd_u32': (PROJECT / 'results/ptx-arithmetic-20261110-v1/vadd_u32',
                 'dd78f819747282db19645f9abd99f154b06346bd50193617d7ba143da2c12751'),
    'affine_u32': (PROJECT / 'results/ptx-arithmetic-20261110-v1/affine_u32',
                   'dd21f514e801a54101cd7b4b4a8cc48e07a7b7432e2fb32aa1e4bd7fa65f2a6d'),
}


def prepare(run):
    require(sha256(FROZEN / 'manifest.json') == FREEZE_SHA, 'E frozen manifest changed')
    frozen = read_json(FROZEN / 'manifest.json')
    bundle = run / 'bundle'
    for directory in ('inputs', 'source', 'expected'):
        (bundle / directory).mkdir(parents=True, exist_ok=False)
    groups = [[c for c in frozen['cases'] if c['entry'] == entry] for entry in IMAGES]
    ordered = [c for row in itertools.zip_longest(*groups) for c in row if c]
    # Rotate the second pass to change both module predecessors and input history.
    ordered += ordered[1:] + ordered[:1]
    capacity = max(c['words'] for c in ordered) * 4
    contract = dict(schema='ptx-same-device-sequence-v1', frozen_manifest_sha256=FREEZE_SHA,
                    target_lock_sha256=sha256(SIM_LOCK), board_lock_sha256=sha256(BOARD_LOCK),
                    buffer_bytes=capacity, abi=frozen['abi'], cases=[], expected={}, images={})
    corpora = {}
    for entry, (origin, digest) in IMAGES.items():
        require(sha256(origin / 'kernel.vxbin') == digest, 'delivered image changed: ' + entry)
        shutil.copy2(origin / 'kernel.vxbin', bundle / (entry + '.vxbin'))
        pc = vxbin_entry(bundle / (entry + '.vxbin'), entry)
        corpora[entry] = read_json(FRONTEND_RUN / entry / 'corpus.json')
        require(sha256(FRONTEND_RUN / entry / 'corpus.json') == CORPUS_HASHES[entry], 'source corpus changed')
        contract['images'][entry] = dict(sha256=digest, pc=pc)
    for index, original in enumerate(ordered):
        cid = '{:04d}'.format(index)
        entry, old_id = original['entry'], original['id']
        case = {key: original[key] for key in ('entry', 'n', 'block', 'grid', 'alpha')}
        case.update(id=cid, source_case=old_id, generation=1 + index // 15,
                    reject=index in (0, 1, 2, 15, 16, 17), pc=contract['images'][entry]['pc'],
                    words=capacity // 4, expected_loads=original['expected_array_reads'],
                    expected_stores=original['expected_array_writes'])
        contract['cases'].append(case)
        for key in ('x', 'y', 'z'):
            source_name = 'inputs/' + old_id + '_' + key + '.bin'
            source = FRONTEND_RUN / entry / source_name
            require(sha256(source) == original['inputs_sha256'][key] == corpora[entry]['files'][source_name],
                    'frozen input changed')
            raw = source.read_bytes()
            # Every launch has a different guard extension, including the repeated pass.
            padding = bytes(((index * 37 + j * 13 + ord(key)) & 255) for j in range(capacity - len(raw)))
            inp = raw + padding
            answer = FROZEN / entry / old_id / (key + '.bin')
            if key in original['expected_sha256']:
                require(sha256(answer) == original['expected_sha256'][key], 'E answer changed')
                expected = answer.read_bytes() + padding
            else:
                expected = inp  # Unused y in copy must remain byte-identical.
            name = cid + '_' + key + '.bin'
            (bundle / 'inputs' / name).write_bytes(inp)
            (bundle / 'expected' / name).write_bytes(expected)
            contract['expected'][name] = sha256(bundle / 'expected' / name)
            if case['reject']:
                reject_name = cid + '_reject_' + key + '.bin'
                (bundle / 'expected' / reject_name).write_bytes(inp)
                contract['expected'][reject_name] = sha256(bundle / 'expected' / reject_name)
    lines = ['#pragma once', '#include <array>', '#include <cstdint>', 'namespace sequence {',
             'constexpr uint32_t buffer_bytes = %du;' % capacity,
             'struct Case { const char* id; const char* entry; uint32_t n, block, grid, alpha, generation; bool reject; };',
             'constexpr std::array<Case, 30> cases{{']
    lines += ['  {{"{id}", "{entry}", {n}u, {block}u, {grid}u, {alpha}u, {generation}u, {reject}}},'.format(
              **dict(c, reject='true' if c['reject'] else 'false')) for c in contract['cases']]
    lines += ['}};', '}', '']
    (bundle / 'source/sequence.hpp').write_text('\n'.join(lines), encoding='ascii')
    shutil.copy2(PROJECT / 'native/ptx_sequence/main.cpp', bundle / 'source/main.cpp')
    shutil.copy2(PROJECT / 'scripts/ptx_sequence_contract.py', bundle / 'sequence_contract.py')
    contract['files'] = {p.relative_to(bundle).as_posix(): sha256(p) for p in sorted(bundle.rglob('*')) if p.is_file()}
    write_json(bundle / 'contract.json', contract)
    return contract


def check_traces(stdout, backend, contract, comparison):
    traces = []
    for c, observation in zip(contract['cases'], comparison['observations']):
        segment = stdout.split('SEQUENCE_BEGIN ' + c['id'] + '\n', 1)[1].split('SEQUENCE_END ' + c['id'] + '\n', 1)[0]
        bindings = []
        if backend == 'rtlsim':
            segment, bindings = bind_rtl_dispatches(segment, c['grid'])
        entry = c['entry']
        if entry == 'copy_u32':
            sites, param_pc = dict(x=(LOAD_PC, 'LD'), z=(STORE_PC, 'ST')), PARAM_PC
        else:
            sites, param_pc = instruction_sites((IMAGES[entry][0] / 'kernel.dump').read_text(), entry, 24)
        trace = analyze_trace(segment, backend, c, observation['addresses'], sites, param_pc)
        trace.update(id=c['id'], entry=entry, rtl_cta_bindings=bindings)
        traces.append(trace)
    require(all(t['status'] == 'PASS' for t in traces), 'sequence LSU mismatch: ' + backend)
    return dict(status='PASS', cases=traces, loads=sum(t['observed_loads'] for t in traces),
                stores=sum(t['observed_stores'] for t in traces))


def execute(run, recorder, recheck_run=None):
    old = PROJECT / 'results' / recheck_run if recheck_run else None
    if old:
        old_summary = read_json(old / 'summary.json')
        require(sha256(old / 'bundle/contract.json') == old_summary['contract_sha256'], 'parent contract changed')
        shutil.copytree(old / 'bundle', run / 'bundle')
        contract = read_json(run / 'bundle/contract.json')
        require(all(sha256(run / 'bundle' / name) == digest for name, digest in contract['files'].items()),
                'parent bundle changed')
        recorder.summary['rechecked_from'] = recheck_run
    else:
        contract = prepare(run)
    bundle = run / 'bundle'
    recorder.summary.update(contract_sha256=sha256(bundle / 'contract.json'), planned_launches=len(contract['cases']))
    for backend in ('simx', 'rtlsim', 'xrtsim'):
        if backend != 'xrtsim':
            lib, hashes = trace_libraries(backend)
        else:
            build_id = 'ab-d5-block32-20261108-v1-xrtsim'
            lib = BUILDS / build_id / 'sw/runtime'
            names = ('libvortex.so', 'libvortex-xrt.so', 'libxrtsim.so')
            hashes = {name: sha256(lib / name) for name in names}
            require(hashes == {name: sha256(PROJECT / 'results' / build_id / 'artifacts/sw/runtime' / name)
                               for name in names}, 'D5 AFU libraries changed')
        stage = run / backend
        (stage / 'actual').mkdir(parents=True)
        result = dict(status='FAIL', libraries=hashes)
        recorder.summary['backends'][backend] = result
        host = stage / 'sequence'
        prior = next((c for c in old_summary['commands'] if c['label'] == backend + '_run'), None) if old else None
        if prior:
            require(prior['returncode'] == 0 and not prior['timed_out'] and
                    old_summary['backends'][backend]['libraries'] == hashes and
                    sha256(old / prior['log']) == prior['log_sha256'], 'parent execution changed or failed')
            shutil.copy2(old / prior['log'], stage / 'execution.log')
            shutil.copytree(old / backend / 'actual', stage / 'actual', dirs_exist_ok=True)
            require(sha256(old / backend / 'sequence') == old_summary['backends'][backend]['host_sha256'], 'parent host changed')
            shutil.copy2(old / backend / 'sequence', host)
            copied = dict(prior, log=str((stage / 'execution.log').relative_to(run)), reused_from=recheck_run)
            recorder.summary['commands'].append(copied)
            stdout = (stage / 'execution.log').read_text()
            result.update(execution_reused_from=recheck_run, host_sha256=sha256(host))
            comparison = verify_capture(contract, stdout, stage / 'actual')
            write_json(stage / 'comparison.json', comparison)
            if backend != 'xrtsim':
                traces = check_traces(stdout, backend, contract, comparison)
                write_json(stage / 'trace.json', traces)
                result.update(loads=traces['loads'], stores=traces['stores'])
            result.update(status='PASS', launches=comparison['launches'], rejected_launches=comparison['rejected_launches'],
                          checked_files=comparison['checked_files'])
            recorder.save()
            print(backend, 'recheck PASS (raw execution from ' + recheck_run + ')', flush=True)
            continue
        run_stage(recorder, backend + '_compile', ['g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror',
                  '-I' + str(VORTEX / 'sw/runtime/include'), bundle / 'source/main.cpp', '-L' + str(lib),
                  '-lvortex', '-pthread', '-o', host], bundle)
        result['host_sha256'] = sha256(host)
        stdout = run_stage(recorder, backend + '_run', ['env', 'VORTEX_DRIVER=' + ('xrt' if backend == 'xrtsim' else backend),
                           'VORTEX_PROFILING=0', 'LD_LIBRARY_PATH=' + str(lib), host,
                           bundle / 'inputs', stage / 'actual'], bundle, timeout=600)
        comparison = verify_capture(contract, stdout, stage / 'actual')
        write_json(stage / 'comparison.json', comparison)
        if backend != 'xrtsim':
            traces = check_traces(stdout, backend, contract, comparison)
            write_json(stage / 'trace.json', traces)
            result.update(loads=traces['loads'], stores=traces['stores'])
        result.update(status='PASS', launches=comparison['launches'], rejected_launches=comparison['rejected_launches'],
                      checked_files=comparison['checked_files'])
        recorder.save()
        print(backend, result['status'], flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--recheck-run', help='Recheck successful raw executions; execute only missing backends')
    args = parser.parse_args()
    require(re.fullmatch(r'ptx-sequence-[A-Za-z0-9_.-]{1,64}', args.run_id), 'invalid sequence run id')
    require(not args.recheck_run or re.fullmatch(r'ptx-sequence-[A-Za-z0-9_.-]{1,64}', args.recheck_run), 'invalid parent run id')
    run = PROJECT / 'results' / args.run_id
    run.mkdir()
    summary = dict(schema='ptx-same-device-run-v1', run_id=args.run_id, status='FAIL', commands=[],
                   started_at=utc_now(), backends={b: dict(status='NOT_RUN') for b in ('simx', 'rtlsim', 'xrtsim', 'u280')},
                   independent_sequence_acceptance='NOT_RUN', timeout_recovery='NOT_RUN')
    recorder = Recorder(run, summary, dict(os.environ))
    try:
        shutil.copy2(__file__, run)
        execute(run, recorder, args.recheck_run)
        summary['status'] = 'PASS'
    except (OSError, ValueError, RuntimeError, KeyError, IndexError) as exc:
        summary['error'] = repr(exc)
    finally:
        summary['finished_at'] = utc_now()
        recorder.save()
    print(summary['status'], run, summary.get('error', ''))
    return 0 if summary['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
