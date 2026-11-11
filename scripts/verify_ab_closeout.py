"""Audit A/B delivery identities and evidence in a new directory; no board access."""
import argparse
import base64
import json
import os
from pathlib import Path
import re
import shutil

from run_native_smoke import PROJECT, Recorder, sha256, utc_now
from run_ptx_copy import (FRONTEND_RUN, SIM_LOCK, VORTEX, capture_comparison, case_header,
                          read_json, require, run_stage, write_json)
from run_ptx_boundaries import select_cases, IMAGES
from run_ptx_copy_trace import LOAD_PC, STORE_PC, PARAM_PC, analyze_trace
from run_ptx_arithmetic import instruction_sites
from ptx_boundary_trace import bind_slots, bind_simx
from review_ptx_sequence import review


def check_boundaries(source):
    summary = read_json(source / 'summary.json')
    require(summary['status'] == 'PASS' and summary['exit_code'] == 0 and
            summary['target_lock_sha256'] == sha256(SIM_LOCK), 'boundary run did not pass')
    commands = {}
    for command in summary['commands']:
        require(command['label'] not in commands, 'duplicate execution label')
        require(command['returncode'] == 0 and not command['timed_out'] and
                sha256(source / command['log']) == command['log_sha256'], 'command or raw log changed')
        commands[command['label']] = command
    snapshots = read_json(source / 'implementation.json')
    require(all(sha256(source / 'implementation' / name) == h for name, h in snapshots.items()), 'implementation snapshot changed')
    totals = {b: dict(launches=0, files=0, loads=0, stores=0) for b in ('simx', 'rtlsim', 'xrtsim')}
    planned_labels = {'source_commit'}
    for entry, (_, image_sha) in IMAGES.items():
        module = source / entry
        manifest = read_json(module / 'manifest.json')
        require(sha256(module / 'kernel.vxbin') == image_sha and all(
            sha256(module / name) == h for name, h in manifest['files'].items()), 'module artifact changed')
        corpus = read_json(FRONTEND_RUN / entry / 'corpus.json')
        require(sha256(FRONTEND_RUN / entry / 'corpus.json') == manifest['corpus_sha256'], 'corpus identity changed')
        cases = select_cases(entry, corpus)
        require(cases == manifest['cases'] == summary['kernels'][entry]['cases'], 'case coverage changed')
        ir = read_json(module / 'frontend/ir.json')
        sites, param_pc = ((dict(x=(LOAD_PC, 'LD'), z=(STORE_PC, 'ST')), PARAM_PC) if entry == 'copy_u32' else
                          instruction_sites((module / 'kernel.dump').read_text(), entry, 24))
        planned_labels.update((entry + '_frontend', entry + '_device_build'))
        for backend in totals:
            require([r['id'] for r in summary['kernels'][entry]['backends'][backend]] == [c['id'] for c in cases],
                    'missing, duplicated, or reordered backend result')
        for case in cases:
            cid = case['id']
            directory = module / cid
            require((directory / 'copy_case.hpp').read_text() == case_header(case, ir), 'host geometry/header changed')
            require(sha256(directory / 'main.cpp') == snapshots['native/ptx_copy/main.cpp'], 'host source changed')
            for group in ('inputs', 'expected'):
                for path in (directory / group).iterdir():
                    require(sha256(path) == corpus['files'][group + '/' + path.name], 'input/reference changed')
            planned_labels.add(entry + '_' + cid + '_compile')
            for backend in totals:
                label = entry + '_' + cid + '_' + backend + '_run'
                planned_labels.add(label)
                stdout = (source / commands[label]['log']).read_text()
                require(stdout.splitlines().count('CAPTURE_COMPLETE 1') == 1 and
                        stdout.splitlines().count('CAPTURED {id} n={n} block={block} grid={grid}'.format(**case)) == 1,
                        'capture geometry/completion mismatch')
                stage = directory / backend
                comp = capture_comparison(directory, stage / 'actual', stdout, case, ir, manifest['runtime_entry_pc'])
                require(comp['status'] == 'PASS' and comp == read_json(stage / 'comparison.json'), 'capture recheck failed')
                record = next(r for r in summary['kernels'][entry]['backends'][backend] if r['id'] == cid)
                require(record['status'] == 'PASS' and sha256(directory / 'host') == record['host_sha256'], 'host binary changed')
                totals[backend]['launches'] += 1
                totals[backend]['files'] += len(comp['files'])
                if backend != 'xrtsim':
                    view, bindings = bind_slots(stdout, case['grid']) if backend == 'rtlsim' else bind_simx(stdout, case)
                    trace = analyze_trace(view, backend, case, comp['device_addresses'], sites, param_pc)
                    trace['cta_bindings'] = bindings
                    # JSON encodes integer dictionary keys as strings.
                    require(trace['status'] == 'PASS' and json.loads(json.dumps(trace)) == read_json(stage / 'trace.json'),
                            'trace recheck failed')
                    totals[backend]['loads'] += trace['observed_loads']
                    totals[backend]['stores'] += trace['observed_stores']
            for name in (directory / 'simx/actual').iterdir():
                if not name.name.endswith('_params.bin'):
                    require(all(name.read_bytes() == (directory / b / 'actual' / name.name).read_bytes()
                                for b in ('rtlsim', 'xrtsim')), 'three-way array mismatch')
    require(set(commands) == planned_labels, 'unexpected/missing execution commands')
    require(all(t['launches'] == 67 for t in totals.values()), 'incomplete boundary suite')
    return dict(status='PASS', scope='recheck existing executions; not additional DUT runs',
                commands=len(commands), totals=totals, source_run=source.name)


def audit(run, recorder, boundary_run, unit_run=None):
    summary = recorder.summary
    old_checks = read_json(PROJECT / 'results/ab-ptx-sequence-check-20261110-v1/result.json')
    require(sha256(PROJECT / 'configs/target_lock.json') == old_checks['root_lock_sha256'] and
            sha256(PROJECT / 'configs/target_caps.json') == old_checks['root_caps_sha256'], 'root lock/caps changed')
    lock = read_json(PROJECT / 'configs/target_lock.json')
    inventory = PROJECT / lock['evidence'] / 'source_manifest.json'
    require(sha256(inventory) == lock['source_manifest_sha256'], 'source manifest changed')
    entries = read_json(inventory)
    for root in (PROJECT / 'upstream/vortex', VORTEX):
        require(all(sha256(root / item['path']) == item['sha256'] for item in entries), 'fixed source checkout changed')
    summary['source_identity'] = dict(status='PASS', files_per_checkout=len(entries), checkouts=2)
    print('source identity PASS', flush=True)
    if unit_run:
        prior = PROJECT / 'results' / unit_run
        tests = read_json(prior / 'summary.json')
        require(tests['status'] == 'PASS' and tests['exit_code'] == 0 and all(
            sha256(PROJECT / p) == h for p, h in tests['implementation'].items()), 'test run failed or code changed')
        require(len(tests['commands']) == 1, 'unexpected test command set')
        command = tests['commands'][0]
        require(command['label'] == 'runner_unittest' and command['returncode'] == 0 and not command['timed_out'] and
                sha256(prior / command['log']) == command['log_sha256'], 'test command/log changed')
        shutil.copy2(prior / command['log'], run / 'logs/runner_unittest.log')
        recorder.summary['commands'].append(dict(command, log='logs/runner_unittest.log', reused_from=unit_run))
        output = (run / 'logs/runner_unittest.log').read_text()
    else:
        output = run_stage(recorder, 'runner_unittest', ['python3', '-B', '-m', 'unittest', 'discover', '-s', 'tests', '-v'], PROJECT, timeout=240)
    match = re.search(r'Ran (\d+) tests?', output)
    skipped = re.search(r'OK \(skipped=(\d+)\)', output)
    require(match and re.search(r'(?m)^OK(?: \(skipped=\d+\))?$', output), 'missing unittest completion')
    count = int(match[1]); skips = int(skipped[1]) if skipped else 0
    summary['runner_unittest'] = dict(status='PASS', total=count, passed=count-skips, skipped=skips, exit_code=0)
    print('runner tests PASS', count, 'total', flush=True)
    summary['boundary_review'] = check_boundaries(PROJECT / 'results' / boundary_run)
    print('boundary capture/trace review PASS', flush=True)
    sequence_out = run / 'sequence-review'
    sequence_out.mkdir()
    sequence = review(PROJECT / 'results/u280-board-ptx-sequence-20261110-v1', sequence_out)
    write_json(sequence_out / 'result.json', sequence)
    summary['sequence_review'] = dict(status=sequence['status'], four_way_arrays=sequence['four_way_array_files'],
                                    executions='HISTORICAL; no new board run')
    archive = PROJECT / 'results/u280-archive-20261109-v5'
    archived = read_json(archive / 'probe.json')
    require(all(sha256(archive / 'returned/reports' / f['path']) == f['sha256']
                for f in archived['report_inventory']), 'archived report changed')
    build = read_json(archive / 'returned/build/result.json')
    xclbin = archive / 'returned/artifacts/vortex_afu.xclbin'
    require(build['status'] == 'PASS' and build['exit_code'] == 0 and sha256(xclbin) == build['artifact']['sha256'],
            'xclbin/build identity mismatch')
    runtime_path = PROJECT / 'results/u280-runtime-20261109-v4/returned/runtime'
    runtime = read_json(runtime_path / 'result.json')
    require(runtime['status'] == 'PASS' and runtime['exit_code'] == 0 and all(
        sha256(runtime_path / a['path']) == a['sha256'] for a in runtime['artifacts']), 'server runtime changed')
    report = archive / 'returned/reports/link/imp/impl_1_full_util_routed.rpt'
    text = report.read_text()
    resources = {}
    for key in ('CLB LUTs', 'CLB Registers', 'Block RAM Tile', 'DSPs', 'URAM'):
        row = re.search(r'^\|\s*' + re.escape(key) + r'\s*\|\s*([\d.]+)\s*\|', text, re.M)
        require(row, 'missing resource row: ' + key)
        resources[key] = float(row[1]) if '.' in row[1] else int(row[1])
    summary['fpga_archive'] = dict(status='PASS', reports=len(archived['report_inventory']),
                                 xclbin_sha256=sha256(xclbin), resources_routed_including_shell=resources,
                                 timing_7='OPEN', performance='NOT_MEASURED')
    accepted = read_json(PROJECT / 'results/e-ptx-acceptance-20261110-v2/result.json')
    frozen = PROJECT / 'configs/acceptance/e-ptx15-v1'
    freeze = read_json(frozen / 'manifest.json')
    require(sha256(frozen / 'manifest.json') == accepted['frozen_manifest_sha256'] and
            sha256(frozen / 'oracle_v1.py') == accepted['oracle_sha256'], 'E frozen identity changed')
    for c in freeze['cases']:
        require(all(sha256(frozen / c['entry'] / c['id'] / (name + '.bin')) == h
                    for name, h in c['expected_sha256'].items()), 'E answer changed')
    summary['e_frozen_answers'] = dict(status='PASS', cases=len(freeze['cases']), new_acceptance='NOT_RUN')
    # Deliverable index is separate from all historical locks and acceptance records.
    paths = [PROJECT / p for p in ('configs/target_lock.json', 'configs/target_caps.json',
        'configs/candidates/block32-v1/target_lock.json', 'configs/candidates/u280-hbm32-v1/target_lock.json',
        'configs/ptx_frontend/v1/profile.json', 'configs/ptx_frontend/v1/abi.json',
        'results/u280-runtime-gcc9-prepare-20261109-v2/binding.json',
        'results/u280-board-regression-20261110-v1/comparison.json',
        'results/e-ptx-acceptance-20261110-v2/result.json',
        'results/u280-board-ptx-sequence-20261110-v1/result.json',
        'results/u280-timing7-review-20261110-v1/result.json',
        'docs/AB_CLOSEOUT.md', 'docs/AB_RECOVERY_LIMITS.md',
        'scripts/run_ptx_boundaries.py', 'scripts/ptx_boundary_trace.py', 'scripts/verify_ab_closeout.py',
        'scripts/run_native_smoke.py', 'scripts/u280_board_smoke.py', 'scripts/Invoke-U280BoardSmoke.ps1',
        'scripts/review_u280_ptx_results.py', 'scripts/replay_ptx_boundary_bundle.py',
        'tests/test_ptx_boundaries.py', 'tests/test_native_smoke.py', 'tests/test_u280_ptx_device.py')]
    paths += [xclbin, report, runtime_path / 'result.json', PROJECT / 'results' / boundary_run / 'summary.json']
    paths += [runtime_path / a['path'] for a in runtime['artifacts']]
    paths += [PROJECT / 'results' / boundary_run / e / 'kernel.vxbin' for e in IMAGES]
    delivery = dict(schema='ab-platform-delivery-v1', frozen=False, scope='A/B reproducible platform evidence and limitations',
                    acceptance='LIMITED; no full P0 or new E acceptance',
                    files=[dict(path=p.relative_to(PROJECT).as_posix(), bytes=p.stat().st_size, sha256=sha256(p)) for p in paths],
                    remaining=dict(timing_7='OPEN', boundary_u280='NOT_RUN', independent_sequence='NOT_RUN',
                                   timeout_recovery='NOT_RUN', generic_runtime='NOT_RUN', performance='NOT_MEASURED'))
    write_json(run / 'delivery.json', delivery)
    summary['delivery_sha256'] = sha256(run / 'delivery.json')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--boundary-run', required=True)
    parser.add_argument('--unit-run', help='Reuse a successful full test run only when all script/test hashes are unchanged')
    args = parser.parse_args()
    for value in (args.run_id, args.boundary_run, *([args.unit_run] if args.unit_run else [])):
        require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{1,95}', value), 'unsafe run id')
    run = PROJECT / 'results' / args.run_id
    run.mkdir()
    summary = dict(schema='ab-closeout-audit-v1', started_at=utc_now(), status='FAIL', commands=[],
                   board_execution='NOT_RUN', scope='runner tests, source identity, historical evidence recheck and delivery index')
    recorder = Recorder(run, summary, dict(os.environ))
    try:
        shutil.copy2(__file__, run)
        audit(run, recorder, args.boundary_run, args.unit_run)
        summary['status'] = 'PASS'
    except (OSError, RuntimeError, ValueError, KeyError, IndexError, StopIteration) as error:
        summary['error'] = repr(error)
    finally:
        summary['finished_at'] = utc_now()
        summary['exit_code'] = 0 if summary['status'] == 'PASS' else 1
        recorder.save()
    print(summary['status'], run, summary.get('error', ''), flush=True)
    return summary['exit_code']


if __name__ == '__main__':
    raise SystemExit(main())
