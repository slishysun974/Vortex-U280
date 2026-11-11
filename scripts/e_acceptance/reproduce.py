"""Execute delivered implementations in an empty E-owned directory.

This records execution and provenance only; accept.py decides correctness.
No production oracle, argument packer, trace parser or comparer is imported.
Run under the existing Vortex WSL environment.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
FROZEN = ROOT / 'configs/acceptance/e-ptx15-v1'
FREEZE_SHA = 'f205a527c8bb6801ed7e2d416ea4a56236109e67c4b2323f851c4690d327e7d7'
BUILDS = {
    'simx': 'ab-d6-trace-simx-20261108-v2',
    'rtlsim': 'ab-d6-trace-rtlsim-20261108-v1',
    'noxrt': 'ab-d5-block32-20261108-v1-xrtsim',
}


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True)+'\n', encoding='utf-8')


def old_case(entry, case_id):
    if entry == 'copy_u32':
        return ROOT/'results/ptx-copy-trace-20261110-v1'/case_id
    return ROOT/'results/ptx-arithmetic-20261110-v1'/entry/case_id


def old_module(entry):
    if entry == 'copy_u32':
        return ROOT/'results/ptx-copy-20261110-v2/module'
    return ROOT/'results/ptx-arithmetic-20261110-v1'/entry


class Recorder:
    def __init__(self, directory):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=False)
        (directory/'logs').mkdir()
        self.data = dict(schema='e-ptx-reproduction-v1', status='RUNNING',
                         freeze_sha256=FREEZE_SHA, commands=[], builds={}, cases=[], identities={})
        self.save()

    def save(self):
        write_json(self.directory/'execution.json', self.data)

    def run(self, label, command, cwd, timeout=180):
        log = self.directory/'logs'/(str(len(self.data['commands'])+1).zfill(3)+'_'+label+'.log')
        rec = dict(label=label, argv=[str(a) for a in command], cwd=str(cwd),
                   started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                   stdout_stderr=str(log.relative_to(self.directory)), timeout_seconds=timeout)
        start = time.monotonic()
        with log.open('wb') as stream:
            try:
                cp = subprocess.run(rec['argv'], cwd=cwd, stdout=stream, stderr=subprocess.STDOUT,
                                    timeout=timeout, check=False)
                rec['exit_code'] = cp.returncode
                rec['timed_out'] = False
            except subprocess.TimeoutExpired:
                rec['exit_code'] = None
                rec['timed_out'] = True
        rec['elapsed_seconds'] = round(time.monotonic()-start, 3)
        rec['log_sha256'] = digest(log)
        self.data['commands'].append(rec)
        self.save()
        print(label, 'exit=',rec['exit_code'], flush=True)
        if rec['exit_code'] != 0:
            raise RuntimeError(label+' failed; raw log '+str(log))
        return rec


def execute(rec):
    if digest(FROZEN/'manifest.json') != FREEZE_SHA:
        raise ValueError('frozen manifest changed')
    manifest = json.loads((FROZEN/'manifest.json').read_text())
    libs = {}
    for backend, provenance in BUILDS.items():
        archive = ROOT/'results'/provenance
        source = json.loads((archive/'summary.json').read_text())
        build = Path(source['build_path'])
        lib = build/'sw/runtime'
        libs[backend] = lib
        names = ['libvortex.so']
        names += {'simx':['libvortex-simx.so','libsimx.so'],
                  'rtlsim':['libvortex-rtlsim.so','librtlsim.so'],
                  'noxrt':['libvortex-xrt.so','libxrtsim.so']}[backend]
        identities = {}
        for name in names:
            record = source['build_artifacts']['sw/runtime/'+name]
            actual = digest(lib/name)
            if actual != record['sha256'] or actual != digest(archive/record['review_copy']):
                raise ValueError('runtime identity mismatch '+str(lib/name))
            identities[str(lib/name)] = actual
        rec.data['identities'][backend] = identities
    rec.data['identities']['source'] = {
        str(p.relative_to(ROOT)): digest(p) for p in [ROOT/'configs/target_lock.json',
        ROOT/'configs/candidates/block32-v1/target_lock.json', ROOT/'scripts/ptx_frontend.py']}
    rec.run('python_version', ['python3','--version'], rec.directory)
    rec.run('gpp_version', ['g++','--version'], rec.directory)
    for entry in ('copy_u32','vadd_u32','affine_u32'):
        module = rec.directory/'modules'/entry
        module.mkdir(parents=True)
        old = old_module(entry)
        rec.run(entry+'_frontend', ['python3','-B', ROOT/'scripts/ptx_frontend.py',
                ROOT/'ptx/samples'/(entry+'.ptx'), '--target-lock',
                ROOT/'configs/candidates/block32-v1/target_lock.json','--output',module/'frontend'], module)
        for name in ('kernel.cpp','Makefile'):
            shutil.copyfile(old/name, module/name)
        shutil.copyfile(module/'frontend/kernel_body.hpp', module/'kernel_body.hpp')
        argv = ['make','ROOT_DIR=/opt/vortex-ab/builds/ab-d5-block32-20261108-v1-simx',
                'CONFIGS=-DVX_CFG_NUM_CLUSTERS=1 -DVX_CFG_NUM_CORES=1 -DVX_CFG_NUM_THREADS=4 -DVX_CFG_NUM_WARPS=8']
        if entry != 'copy_u32':
            argv.append('PTX_ENTRY='+entry)
        rec.run(entry+'_device_build', argv+['kernel.vxbin','kernel.dump'], module)
        identities = {name: digest(module/name) for name in ('kernel.cpp','Makefile','kernel_body.hpp','kernel.vxbin','kernel.elf','kernel.dump')}
        identities['delivered_image'] = digest(old/'kernel.vxbin')
        identities['image_reproduced'] = identities['kernel.vxbin'] == identities['delivered_image']
        rec.data['builds'][entry] = identities
        rec.save()
        if not identities['image_reproduced']:
            raise ValueError('new image differs from delivered '+entry)
    for backend, lib in libs.items():
        for case in manifest['cases']:
            entry, cid = case['entry'], case['id']
            stage = rec.directory/backend/entry/cid
            stage.mkdir(parents=True)
            (stage/'inputs').mkdir()
            (stage/'output').mkdir()
            for name in ('main.cpp','copy_case.hpp'):
                shutil.copyfile(old_case(entry,cid)/name, stage/name)
            shutil.copyfile(rec.directory/'modules'/entry/'kernel.vxbin',stage/'kernel.vxbin')
            for role, expected_hash in case['inputs_sha256'].items():
                p = ROOT/'results/ptx-frontend-host-20261108-v3'/entry/'inputs'/(cid+'_'+role+'.bin')
                if digest(p) != expected_hash:
                    raise ValueError('input identity changed')
                shutil.copyfile(p,stage/'inputs'/p.name)
            label = backend+'_'+entry+'_'+cid
            compile_rec = rec.run(label+'_compile', ['g++','-std=c++17','-Wall','-Wextra','-Werror','-O2',
                '-I/opt/vortex-ab/sources/vortex-7fe19369587c-v1/sw/runtime/include',
                'main.cpp','-L'+str(lib),'-lvortex','-o','host'],stage)
            driver = 'xrt' if backend == 'noxrt' else backend
            run_rec = rec.run(label+'_run', ['env','-u','XCLBIN_PATH','-u','XCL_EMULATION_MODE',
                'VORTEX_DRIVER='+driver,'LD_LIBRARY_PATH='+str(lib),'VORTEX_PROFILING=0',
                'XRT_DEVICE_INDEX=0','./host','inputs','output'],stage)
            rec.data['cases'].append(dict(backend=backend, entry=entry, id=cid,
                directory=str(stage.relative_to(rec.directory)), compile_label=compile_rec['label'],
                run_label=run_rec['label'], executed=True,
                hashes={name:digest(stage/name) for name in ('main.cpp','copy_case.hpp','host','kernel.vxbin')}))
            rec.save()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    if not args.run_id.startswith('e-ptx-') or '/' in args.run_id or '\\' in args.run_id:
        raise ValueError('E-only fresh run-id required')
    recorder = Recorder(ROOT/'results'/args.run_id)
    shutil.copyfile(__file__, recorder.directory/'reproduce.py')
    try:
        execute(recorder)
        recorder.data['status'] = 'EXECUTED_NOT_YET_ACCEPTED'
    except Exception as error:
        recorder.data['status'] = 'FAIL'
        recorder.data['error'] = repr(error)
        raise
    finally:
        recorder.save()
