"""Recheck U280 sequence bytes, gates and three-model captures in a new directory."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import shutil

from ptx_sequence_contract import verify_capture, require
from u280_board_smoke import XCLBIN_SHA, RUNTIME_SHAS, XCLBIN_UUID, idle

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_bytes())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def review(board_run, out):
    prep = read(board_run / 'preparation.json')
    result = read(board_run / 'result.json')
    transport = read(board_run / 'transport.json')
    require(result['status'] == transport['status'] == 'PASS' and transport['ssh_exit_code'] == 0 and
            transport['exit_code'] == 0, 'board/SSH failed')
    require(result['run_id'] == prep['run_id'] == transport['run_id'] == board_run.name and
            result['nonce'] == prep['nonce'] and result['mode'] == prep['mode'] == 'ptx-sequence' and
            result['script_sha256'] == prep['script_sha256'] == digest(board_run / 'u280_board_smoke.py'),
            'board script/result identity mismatch')
    require(digest(board_run / 'payload.py') == prep['payload_sha256'], 'board payload changed')
    contract = prep['sequence']
    source = ROOT / 'results' / prep['source_run']
    require(read(source / 'bundle/contract.json') == contract, 'sequence contract differs')
    summary = read(source / 'summary.json')
    require(summary['status'] == 'PASS' and digest(source / 'bundle/contract.json') == summary['contract_sha256'],
            'source sequence not passed or changed')
    require(all(result[key] == 'PASS' for key in ('host_compile', 'card_preflight', 'device_open', 'readback', 'board_execution')),
            'missing board gate')
    require(result['sysfs']['loaded']['xclbinuuid'] == XCLBIN_UUID and idle(result['sysfs']['after']['kdsstat'])
            and int(result['clock_readback']['freq_mhz']) == 200 and result['clock_readback']['id'] == 'DATA_CLK'
            and result['host_capacity'][result['selected_bdf']]['bytes'] >= 256 * 1024 * 1024,
            'board loaded clock/HOST/idle gate mismatch')
    require(re.fullmatch('[0-9a-f]{64}', result['host_sha256']), 'missing pre-run host identity')
    for name, expected in dict(RUNTIME_SHAS, **{'vortex_afu.xclbin': XCLBIN_SHA}).items():
        require([value for path, value in result['artifact_sha256'].items() if Path(path).name == name] == [expected],
                'board artifact mismatch: ' + name)
    commands = [c for c in result['commands'] if c['label'] in ('host_compile', 'native_ptx-sequence')]
    require(len(commands) == 2 and all(c['exit_code'] == 0 and not c.get('timed_out') for c in commands),
            'compile/execution failed')
    execute = next(c for c in commands if c['label'] == 'native_ptx-sequence')
    actual = out / 'u280'
    actual.mkdir()
    for name, item in result['outputs'].items():
        require(re.fullmatch(r'\d{4}_(?:(?:reject_)?[xyz]|params)\.bin', name), 'unsafe output member')
        raw = base64.b64decode(item['base64'], validate=True)
        require(hashlib.sha256(raw).hexdigest() == item['sha256'] and item['status'] == 'PASS', 'output hash/status mismatch')
        (actual / name).write_bytes(raw)
    checks = {'u280': verify_capture(contract, execute['stdout'], actual)}
    for backend in ('simx', 'rtlsim', 'xrtsim'):
        command = next(c for c in summary['commands'] if c['label'] == backend + '_run')
        logfile = source / command['log']
        require(summary['backends'][backend]['status'] == 'PASS' and command['returncode'] == 0
                and not command['timed_out'] and digest(logfile) == command['log_sha256'], 'simulation evidence mismatch')
        checks[backend] = verify_capture(contract, logfile.read_text(), source / backend / 'actual')
    for name in contract['expected']:
        require(all((actual / name).read_bytes() == (source / backend / 'actual' / name).read_bytes()
                    for backend in ('simx', 'rtlsim', 'xrtsim')), 'four-way bytes mismatch: ' + name)
    return dict(status='PASS', scope='same-device PTX sequence; reused E array answers plus author padding checks',
                board_run=board_run.name, source_run=source.name, checks=checks,
                four_way_array_files=len(contract['expected']), parameter_files_per_backend=len(contract['cases']),
                contract_sha256=digest(source / 'bundle/contract.json'), board_result_sha256=digest(board_run / 'result.json'),
                timeout_recovery='NOT_RUN', independent_sequence_acceptance='NOT_RUN')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--board-run', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    for value in (args.board_run, args.output):
        require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{1,95}', value), 'invalid run id')
    out = ROOT / 'results' / args.output
    out.mkdir()
    shutil.copy2(__file__, out)
    result = dict(status='FAIL')
    try:
        result = review(ROOT / 'results' / args.board_run, out)
    except (OSError, ValueError, RuntimeError, KeyError, StopIteration) as exc:
        result['error'] = repr(exc)
    result['exit_code'] = 0 if result['status'] == 'PASS' else 1
    (out / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(result['status'], out, result.get('error', ''))
    return result['exit_code']


if __name__ == '__main__':
    raise SystemExit(main())
