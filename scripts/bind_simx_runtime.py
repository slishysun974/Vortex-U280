"""Bind a verified SimX, processor RTL or AFU model build to the runtime loader."""
import argparse
import os
from pathlib import Path
import re
import subprocess

from ptx_module import COMMIT, digest, read_json, target, write_json
from runtime_backends import BACKENDS, validate_native


def bind(summary_path, lock_path, hardware_path, output):
    summary_bytes = Path(summary_path).read_bytes()
    summary = read_json(summary_bytes)
    lock_bytes, hardware_bytes = Path(lock_path).read_bytes(), Path(hardware_path).read_bytes()
    _, defines, _ = target(lock_bytes, hardware_bytes)
    backend = summary.get('backend')
    validate_native(summary, backend, digest(lock_bytes))
    driver, backend_library, simulator_library = BACKENDS[backend]
    libraries, dependencies = {}, {}
    build_root = Path(summary['build_path']).resolve()
    libdir = Path(summary['build_path']).resolve()/'sw/runtime'
    ldd = []
    if backend == 'xrtsim':
        for stamp, flag in (('xrt_config.stamp', '-DXRTSIM'), ('xrtsim_config.stamp', '-DNOXRT')):
            data = (libdir/stamp).read_bytes()
            if (flag not in data.decode().split()
                    or digest(data) != summary['build_artifacts']['sw/runtime/'+stamp]['sha256']):
                raise ValueError('AFU simulation build stamp differs: '+stamp)
    for name in ('libvortex.so',backend_library,simulator_library):
        actual = digest((libdir/name).read_bytes())
        if actual != summary['build_artifacts']['sw/runtime/'+name]['sha256']:
            raise ValueError('library changed after native validation: '+name)
        libraries[name] = actual
        environment = dict(os.environ, LD_LIBRARY_PATH=str(libdir), VORTEX_DRIVER=driver)
        run = subprocess.run(['ldd',str(libdir/name)],capture_output=True,text=True,env=environment)
        if run.returncode or 'not found' in run.stdout:
            raise ValueError('unresolved library dependency: '+name)
        for dependency in re.findall(r'=> (/\S+) \(',run.stdout):
            path = Path(dependency).resolve()
            if path.is_relative_to(build_root):
                dependencies[str(path)] = digest(path.read_bytes())
        ldd.append(name+'\n'+run.stdout)
    output = Path(output)
    output.mkdir(parents=True,exist_ok=False)
    (output/'hardware.json').write_bytes(hardware_bytes)
    (output/'target_lock.json').write_bytes(lock_bytes)
    (output/'native-summary.json').write_bytes(summary_bytes)
    (output/'ldd.log').write_text('\n'.join(ldd))
    result = dict(schema_version='ptx-vx-runtime-binding-v3',backend=backend,driver=driver,source_commit=COMMIT,
                  target_lock_hash=digest(lock_bytes),hardware_defines=defines,library_dir=str(libdir),
                  libraries=libraries,dependencies=dependencies,native_summary_sha256=digest(summary_bytes),
                  scope='native build identity; PTX validation is separate')
    write_json(output/'binding.json',result)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--summary',type=Path,required=True)
    parser.add_argument('--target-lock',type=Path,required=True)
    parser.add_argument('--hardware',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    bind(args.summary,args.target_lock,args.hardware,args.output)
    print('Verified simulation runtime binding created:',args.output/'binding.json')


if __name__=='__main__':
    main()
