"""Rebuild three fixed PTX images and execute the A/B boundary delivery suite."""
import argparse
import os
import re
import shutil
import tempfile

from run_native_smoke import PROJECT, Recorder, sha256, utc_now
from run_ptx_copy import (BUILDS, CORPUS_HASHES, FRONTEND_RUN, SIM_LOCK, VORTEX,
    capture_comparison, read_json, require, run_stage, stage_case, vxbin_entry, write_json)
from run_ptx_copy_trace import LOAD_PC, STORE_PC, PARAM_PC, analyze_trace, trace_libraries
from run_ptx_arithmetic import instruction_sites
from run_ptx_sequence import IMAGES
from ptx_boundary_trace import bind_slots, bind_simx

SIZES = (0, 1, 7, 31, 32, 33, 63, 64, 65, 257, 1024)
BLOCKS = (1, 4, 7, 16, 31, 32)


def select_cases(entry, corpus):
    """67 cases: all required N at B32, smaller blocks at N0/65, affine controls."""
    alpha = 0xffffffff if entry == 'affine_u32' else 1
    geometries = {(n, 32, alpha) for n in SIZES}
    geometries |= {(n, b, alpha) for b in BLOCKS[:-1] for n in (0, 65)}
    if entry == 'affine_u32':
        geometries |= {(n, 32, a) for n in (65, 1024) for a in (0, 1)}
    cases = [c for c in corpus['cases'] if c['repeat'] == 0 and (c['n'], c['block'], c['alpha']) in geometries]
    require(len(cases) == len(geometries) and
            {(c['n'], c['block'], c['alpha']) for c in cases} == geometries, 'boundary coverage mismatch')
    return cases


def execute(run, recorder):
    summary = recorder.summary
    require(run_stage(recorder, 'source_commit', ['git', '-C', VORTEX, 'rev-parse', 'HEAD'], run).strip() ==
            read_json(SIM_LOCK)['vortex']['commit'], 'source commit mismatch')
    libraries = {b: trace_libraries(b) for b in ('simx', 'rtlsim')}
    afu = BUILDS / 'ab-d5-block32-20261108-v1-xrtsim/sw/runtime'
    afu_names = ('libvortex.so', 'libvortex-xrt.so', 'libxrtsim.so')
    afu_hashes = {n: sha256(afu / n) for n in afu_names}
    require(afu_hashes == {n: sha256(PROJECT / 'results/ab-d5-block32-20261108-v1-xrtsim/artifacts/sw/runtime' / n)
                          for n in afu_names}, 'AFU library identity changed')
    libraries['xrtsim'] = afu, afu_hashes
    summary['libraries'] = {b: h for b, (_, h) in libraries.items()}
    build = BUILDS / 'ab-d5-block32-20261108-v1-simx'
    require(sha256(build / 'sw/kernel/libvortex2.a') ==
            read_json(IMAGES['copy_u32'][0] / 'manifest.json')['kernel_lib_sha256'], 'device library changed')
    require(sha256(build / 'tests/regression/common.mk') ==
            sha256(PROJECT / 'upstream/vortex/tests/regression/common.mk'), 'device build rules changed')
    defines = ' '.join('-D{}={}'.format(k, v) for k, v in read_json(SIM_LOCK.with_name('native_smoke.json'))['defines'].items())
    for entry, (origin, image_sha) in IMAGES.items():
        module = run / entry
        module.mkdir()
        frontend = read_json(origin / 'frontend/manifest.json')
        received = read_json(PROJECT / 'results/e-ptx-reproduce-20261110-v1/execution.json')['builds'][entry]
        require(sha256(origin / 'kernel.vxbin') == image_sha, 'delivered image changed')
        for name in ('kernel.cpp', 'Makefile'):
            require(sha256(origin / name) == received[name], 'delivered wrapper/build input changed')
            shutil.copy2(origin / name, module / name)
        run_stage(recorder, entry + '_frontend', ['python3', '-B', PROJECT / 'scripts/ptx_frontend.py',
                  PROJECT / 'ptx/samples' / (entry + '.ptx'), '--target-lock', SIM_LOCK,
                  '--output', module / 'frontend'], module)
        for name in ('kernel_body.hpp', 'ir.json', 'source.ptx'):
            require(sha256(module / 'frontend' / name) == frontend['files'][name], 'frontend identity mismatch')
        shutil.copy2(module / 'frontend/kernel_body.hpp', module)
        run_stage(recorder, entry + '_device_build', ['make', 'ROOT_DIR=' + str(build), 'CONFIGS=' + defines,
                  'PTX_ENTRY=' + entry, 'kernel.vxbin', 'kernel.dump'], module, timeout=180)
        require(sha256(module / 'kernel.vxbin') == image_sha, 'rebuilt image mismatch')
        ir = read_json(module / 'frontend/ir.json')
        pc = vxbin_entry(module / 'kernel.vxbin', entry)
        if entry == 'copy_u32':
            sites, param_pc = dict(x=(LOAD_PC, 'LD'), z=(STORE_PC, 'ST')), PARAM_PC
        else:
            sites, param_pc = instruction_sites((module / 'kernel.dump').read_text(), entry, 24)
        corpus_path = FRONTEND_RUN / entry / 'corpus.json'
        require(sha256(corpus_path) == CORPUS_HASHES[entry], 'corpus changed')
        cases = select_cases(entry, read_json(corpus_path))
        manifest = dict(entry=entry, image_sha256=image_sha, runtime_entry_pc=pc,
                        target_lock_sha256=sha256(SIM_LOCK), corpus_sha256=CORPUS_HASHES[entry],
                        files={p.relative_to(module).as_posix(): sha256(p) for p in sorted(module.rglob('*')) if p.is_file()},
                        cases=cases)
        write_json(module / 'manifest.json', manifest)
        summary['kernels'][entry] = dict(image_sha256=image_sha, cases=cases, backends={b: [] for b in libraries})
        for case in cases:
            cid = case['id']
            directory = module / cid
            directory.mkdir()
            staged, _ = stage_case(directory, ir, cid)
            require(staged == case, 'case changed during staging')
            shutil.copy2(PROJECT / 'native/ptx_copy/main.cpp', directory)
            host = directory / 'host'
            run_stage(recorder, entry + '_' + cid + '_compile', ['g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror',
                      '-I' + str(VORTEX / 'sw/runtime/include'), directory / 'main.cpp', '-L' + str(libraries['simx'][0]),
                      '-lvortex', '-o', host], directory)
            for backend, (lib, _) in libraries.items():
                stage = directory / backend
                actual = stage / 'actual'
                actual.mkdir(parents=True)
                label = entry + '_' + cid + '_' + backend
                stdout = run_stage(recorder, label + '_run', ['env', '-u', 'XCLBIN_PATH', '-u', 'XCL_EMULATION_MODE',
                    'VORTEX_DRIVER=' + ('xrt' if backend == 'xrtsim' else backend), 'LD_LIBRARY_PATH=' + str(lib),
                    'VORTEX_PROFILING=0', 'XRT_DEVICE_INDEX=0', host, directory / 'inputs', actual], module, timeout=180)
                require(stdout.splitlines().count('CAPTURE_COMPLETE 1') == 1 and
                        stdout.splitlines().count('CAPTURED {id} n={n} block={block} grid={grid}'.format(**case)) == 1,
                        'incomplete or wrong capture geometry')
                comparison = capture_comparison(directory, actual, stdout, case, ir, pc)
                write_json(stage / 'comparison.json', comparison)
                require(comparison['status'] == 'PASS', 'array or parameter mismatch: ' + label)
                result = dict(id=cid, status='PASS', host_sha256=sha256(host), checked_files=len(comparison['files']))
                if backend != 'xrtsim':
                    view, bindings = bind_slots(stdout, case['grid']) if backend == 'rtlsim' else bind_simx(stdout, case)
                    trace = analyze_trace(view, backend, case, comparison['device_addresses'], sites, param_pc)
                    trace['cta_bindings'] = bindings
                    write_json(stage / 'trace.json', trace)
                    require(trace['status'] == 'PASS', 'LSU trace mismatch: ' + label)
                    result.update(loads=trace['observed_loads'], stores=trace['observed_stores'])
                summary['kernels'][entry]['backends'][backend].append(result)
                recorder.save()
            print(entry, cid, 'N=' + str(case['n']), 'B=' + str(case['block']), '3 backends PASS', flush=True)
    summary['totals'] = {b: dict(launches=sum(len(k['backends'][b]) for k in summary['kernels'].values()),
        checked_files=sum(r['checked_files'] for k in summary['kernels'].values() for r in k['backends'][b])) for b in libraries}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    require(re.fullmatch(r'ptx-boundaries-[A-Za-z0-9_.-]{1,64}', args.run_id), 'invalid run id')
    run = PROJECT / 'results' / args.run_id
    run.mkdir()
    summary = dict(schema='ab-ptx-boundaries-v1', run_id=args.run_id, started_at=utc_now(), status='FAIL',
                   commands=[], kernels={}, target_lock_sha256=sha256(SIM_LOCK),
                   u280='NOT_RUN', independent_acceptance='NOT_RUN',
                   reference='Preserved author corpus; no new independent E acceptance', performance='NOT_MEASURED')
    # DEBUG3 emits many tiny writes. Spool raw bytes on Linux before one archive
    # copy, so Windows-mounted filesystem latency does not become a DUT timeout.
    scratch = tempfile.TemporaryDirectory(prefix='vortex-ab-boundaries-')
    summary['log_spooling'] = dict(directory=scratch.name, purpose='raw DEBUG3 log I/O only; no semantic filtering')
    recorder = Recorder(run, summary, dict(os.environ), scratch_logs=scratch.name)
    try:
        snapshot = run / 'implementation'
        shutil.copytree(PROJECT / 'scripts', snapshot / 'scripts', ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copytree(PROJECT / 'native/ptx_copy', snapshot / 'native/ptx_copy')
        write_json(run / 'implementation.json', {p.relative_to(snapshot).as_posix(): sha256(p)
                   for p in sorted(snapshot.rglob('*')) if p.is_file()})
        execute(run, recorder)
        summary['status'] = 'PASS'
    except (OSError, RuntimeError, ValueError, KeyError, IndexError) as error:
        summary['error'] = repr(error)
    finally:
        summary['finished_at'] = utc_now()
        summary['exit_code'] = 0 if summary['status'] == 'PASS' else 1
        recorder.save()
        scratch.cleanup()
    print(summary['status'], run, summary.get('error', ''), flush=True)
    return summary['exit_code']


if __name__ == '__main__':
    raise SystemExit(main())
