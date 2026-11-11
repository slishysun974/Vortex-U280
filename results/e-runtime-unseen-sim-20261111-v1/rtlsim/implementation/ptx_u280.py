"""Physical U280 binding and fresh open/close gates for the integrated C runtime.

Fixed D10/D12 artifacts only. No HOST configuration, reset recovery, or fallback.
Normal vx_device_open retains the upstream initialization behavior.
"""
import argparse
import ctypes as C
import datetime
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

from ptx_module import BOARD_LOCK_SHA, COMMIT, ModuleError, digest, read_json, target, write_json
from u280_board_smoke import BUSES, SHELL_UUID, XCLBIN_UUID, XCLBIN_SHA, RUNTIME_SHAS, capacity, idle, snapshot

SCHEMA = 'ptx-vx-u280-binding-v1'
QUERY_SOURCE = '''#include <xrt/xrt_device.h>
#include <iostream>
#include <cstdlib>
int main(int argc, char** argv) {
  if (argc != 2) return 2;
  try {
    auto device = xrt::device(static_cast<unsigned>(std::stoul(argv[1])));
    std::cout << device.get_info<xrt::info::device::bdf>() << std::endl;
  } catch (const std::exception& error) { std::cerr << error.what() << std::endl; return 3; }
}
'''


def require(ok, message):
    if not ok:
        raise ModuleError('E_TARGET_MISMATCH', message, 'open')


def create_binding(output, lock, hardware, library_dir, xclbin, query, bdf, index):
    """Record local artifacts; a binding never substitutes for fresh board gates."""
    raw, hw = Path(lock).read_bytes(), Path(hardware).read_bytes()
    target(raw, hw)
    require(digest(raw) == BOARD_LOCK_SHA, 'physical binding requires the pinned board lock')
    require(bdf in ['0000:'+b+':00.1' for b in BUSES] and type(index) is int and index >= 0,
            'unsupported BDF/index')
    libdir, bitstream, probe = (Path(p).resolve() for p in (library_dir, xclbin, query))
    for name, expected in RUNTIME_SHAS.items():
        require(digest((libdir/name).read_bytes()) == expected, 'D12 library differs: '+name)
    require(digest(bitstream.read_bytes()) == XCLBIN_SHA, 'D10 xclbin differs')
    require(probe.is_file(), 'missing compiled XRT BDF query')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    (output/'target_lock.json').write_bytes(raw)
    (output/'hardware.json').write_bytes(hw)
    binding = dict(schema_version=SCHEMA, backend='u280-xrt', driver='xrt', source_commit=COMMIT,
        target_lock_hash=digest(raw), hardware_sha256=digest(hw), library_dir=str(libdir),
        libraries=RUNTIME_SHAS, xclbin=str(bitstream), xclbin_sha256=XCLBIN_SHA,
        xclbin_uuid=XCLBIN_UUID, shell_uuid=SHELL_UUID, clock_mhz=200, minimum_host_bytes=256*1024*1024,
        bdf=bdf, index=index, query=str(probe), query_sha256=digest(probe.read_bytes()),
        query_source_sha256=digest(QUERY_SOURCE.encode()), recovery='unavailable', timing7='OPEN',
        scope='fixed physical artifacts; fresh device gates still required; not execution acceptance')
    write_json(output/'binding.json', binding)
    return binding


class BoardGate:
    def __init__(self, path, lock_bytes, run_id):
        self.path = Path(path).resolve()
        self.binding = read_json(self.path.read_bytes())
        require(isinstance(run_id,str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,95}',run_id),
                'physical context requires a unique safe run_id')
        self.output = self.path.parent/'sessions'/run_id
        self.output.mkdir(parents=True,exist_ok=False)
        self.record = dict(status='RUNNING',run_id=run_id,commands=[],reports={},sysfs={},
                           binding_sha256=digest(self.path.read_bytes()), board_execution='NOT_RUN',
                           holder_scope='ordinary-account visible holders; no exclusive reservation')
        try:
            self.static(lock_bytes)
        except Exception as error:
            self.failed(error)
            raise

    def save(self):
        write_json(self.output/'gate.json',self.record)

    def failed(self,error):
        self.record.update(status='FAIL',error=str(error))
        self.save()

    def static(self, lock_bytes):
        b = self.binding
        require(b.get('schema_version') == SCHEMA and b.get('backend') == 'u280-xrt'
                and b.get('driver') == 'xrt' and b.get('source_commit') == COMMIT,
                'invalid physical binding type/source')
        require(digest(lock_bytes) == BOARD_LOCK_SHA == b.get('target_lock_hash'), 'physical lock mismatch')
        hardware = (self.path.parent/'hardware.json').read_bytes()
        target(lock_bytes,hardware)
        require(digest(hardware) == b.get('hardware_sha256'), 'physical hardware hash mismatch')
        require(b.get('libraries') == RUNTIME_SHAS and b.get('xclbin_sha256') == XCLBIN_SHA
                and b.get('xclbin_uuid') == XCLBIN_UUID and b.get('shell_uuid') == SHELL_UUID
                and b.get('clock_mhz') == 200 and b.get('minimum_host_bytes') == 256*1024*1024
                and b.get('recovery') == 'unavailable' and b.get('timing7') == 'OPEN',
                'physical binding changed fixed platform limits')
        require(b.get('bdf') in ['0000:'+bus+':00.1' for bus in BUSES]
                and type(b.get('index')) is int and b['index'] >= 0, 'invalid physical card selection')
        libdir = Path(b['library_dir']).resolve()
        for name, expected in RUNTIME_SHAS.items():
            require(digest((libdir/name).read_bytes()) == expected, 'physical library changed: '+name)
        require(digest(Path(b['xclbin']).read_bytes()) == XCLBIN_SHA, 'physical bitstream changed')
        require(digest(Path(b['query']).read_bytes()) == b['query_sha256']
                and b.get('query_source_sha256') == digest(QUERY_SOURCE.encode()), 'BDF query changed')
        require(os.environ.get('VORTEX_DRIVER') == 'xrt' and not os.environ.get('XCL_EMULATION_MODE')
                and Path(os.environ.get('XCLBIN_PATH','')).resolve() == Path(b['xclbin']).resolve()
                and Path(os.environ.get('LD_LIBRARY_PATH','').split(':')[0]).resolve() == libdir
                and os.environ.get('XRT_DEVICE_INDEX') == str(b['index']), 'physical environment differs from binding')
        self.library_dir = libdir
        self.device = Path('/sys/bus/pci/devices')/b['bdf']
        self.record['artifact_hashes'] = dict(libraries=RUNTIME_SHAS,xclbin=XCLBIN_SHA,
                                             query=b['query_sha256'],lock=BOARD_LOCK_SHA)
        self.save()

    def command(self,label,argv):
        item = dict(label=label,argv=[str(x) for x in argv],exit_code=None,timeout_seconds=20)
        self.record['commands'].append(item)
        self.save()
        try:
            done = subprocess.run(item['argv'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=20)
            item.update(exit_code=done.returncode,stdout=done.stdout.decode(errors='replace'),
                        stderr=done.stderr.decode(errors='replace'))
        except subprocess.TimeoutExpired:
            item['timed_out'] = True
            raise
        finally:
            self.save()
        return item

    def report(self,label,selected=True):
        output = self.output/(label+'.json')
        argv = ['xbutil','examine','--format','JSON','--output',str(output)]
        if selected:
            argv += ['--device',self.binding['bdf'],'--report','platform','pcie-info','dynamic-regions']
        item = self.command(label,argv)
        require(item['exit_code'] == 0, 'xbutil report failed: '+label)
        raw = output.read_bytes()
        self.record['reports'][label] = dict(file=output.name,sha256=digest(raw))
        data = read_json(raw)
        if not selected:
            return data['system']['host']['devices']
        require(len(data['devices']) == 1 and data['devices'][0]['device_id'] == self.binding['bdf'],
                'xbutil selected a different BDF')
        return data['devices'][0]

    def idle(self,label):
        state = snapshot(self.device)
        self.record['sysfs'][label] = state
        self.save()
        require((self.device/'driver').resolve().name == 'xocl' and state['ready'] == '0x1'
                and SHELL_UUID in state['interface_uuids'].lower().replace('-','').split()
                and idle(state['kdsstat']), 'card not ready/idle with fixed shell')
        require(int(state['host_mem_size']) >= 256*1024*1024, 'HOST allocation below 256 MiB')
        nodes = [Path('/dev/dri')/p.name for p in (self.device/'drm').glob('renderD*')]
        require(len(nodes) == 1 and nodes[0].is_char_device(), 'invalid render mapping')
        fuser = shutil.which('fuser') or next((p for p in ('/usr/sbin/fuser','/sbin/fuser') if Path(p).is_file()),None)
        require(fuser is not None, 'fuser is required')
        holders = self.command(label+'_holders',[fuser,'-v',str(nodes[0])])
        require(holders['exit_code'] == 1 and not holders['stdout'].strip() and not holders['stderr'].strip(),
                'visible holder present or holder query failed')

    def before_open(self):
        self.idle('before')
        listing = self.report('device_list',False)
        index = self.binding['index']
        require(index < len(listing) and listing[index]['bdf'] == self.binding['bdf']
                and listing[index]['is_ready'] == 'true', 'fresh XRT enumeration/index mismatch')
        entry = self.report('preflight')
        require(capacity(entry['pcie_info']['shared_host_mem_size_bytes']) >= 256*1024*1024, 'XRT HOST capacity too small')
        query = self.command('xrt_bdf',[self.binding['query'],str(index)])
        require(query['exit_code'] == 0 and query['stdout'].strip() == self.binding['bdf'], 'XRT C++ BDF mismatch')
        self.idle('immediately_before_open')

    def opened(self):
        state = snapshot(self.device)
        self.record['sysfs']['loaded'] = state
        require(state['xclbinuuid'].lower() == XCLBIN_UUID, 'loaded UUID mismatch')
        entry = self.report('loaded')
        clocks = [c for c in entry['platforms'][0]['clocks'] if c['id'] == 'DATA_CLK']
        require(len(clocks) == 1 and int(clocks[0]['freq_mhz']) == 200, 'actual DATA_CLK is not 200 MHz')
        self.record.update(open_gate='PASS',clock_readback=clocks[0],clock_sysfs={str(p):p.read_text().strip()
            for p in self.device.glob('icap.*/clock_freqs')})
        self.save()

    def closed(self):
        try:
            self.idle('after_close')
            self.record.update(status='PASS',close_gate='PASS',
                               scope='physical open/close gates; kernel correctness is in caller evidence')
            self.save()
        except Exception as error:
            self.failed(error)
            raise


def open_context(ctx, binding_path):
    from ptx_runtime import api, P, Q, QueueInfo
    gate = None
    try:
        gate = BoardGate(binding_path,ctx.lock_bytes,ctx.run_id)
        ctx.board_gate = gate
        gate.before_open()
        ctx.lib = api(C.CDLL(str(gate.library_dir/'libvortex.so')))
        ctx.check(ctx.lib.vx_device_open(0,C.byref(ctx.device)),'open')
        gate.opened()
        ctx.caps = {}
        for name,key in (('threads',1),('warps',2),('cores',3),('isa_flags',7),('clusters',10)):
            value = Q()
            ctx.check(ctx.lib.vx_device_query(ctx.device,key,C.byref(value)),'query_caps')
            ctx.caps[name] = value.value
        require(all(ctx.caps[k] == v for k,v in dict(threads=4,warps=8,cores=1,clusters=1).items())
                and 1 << (((ctx.caps['isa_flags'] >> 30) & 3) + 4) == 64,'physical geometry/XLEN mismatch')
        maps = Path('/proc/self/maps').read_text()
        require(all(str(gate.library_dir/n) in maps for n in RUNTIME_SHAS)
                and 'libxrtsim.so' not in maps, 'wrong physical libraries actually loaded')
        info = QueueInfo(C.sizeof(QueueInfo),None,1,0)
        ctx.check(ctx.lib.vx_queue_create(ctx.device,C.byref(info),C.byref(ctx.queue)),'open')
    except Exception as error:
        if gate:
            gate.failed(error)
        if ctx.device:
            ctx.lib.vx_device_release(ctx.device)
            ctx.device = P()
        if isinstance(error,ModuleError):
            ctx.fail(error.code,str(error),'open')
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('output','lock','hardware','library-dir','xclbin','query'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--bdf',required=True)
    parser.add_argument('--index',type=int,required=True)
    args = parser.parse_args()
    create_binding(args.output,args.lock,args.hardware,args.library_dir,args.xclbin,args.query,args.bdf,args.index)
