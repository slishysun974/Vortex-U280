"""Shared capture checks for the fixed same-device PTX sequence (Python 3.6)."""
import hashlib
import re


def require(ok, reason):
    if not ok:
        raise RuntimeError(reason)


def verify_capture(contract, stdout, output):
    lines = stdout.splitlines()
    cases = contract['cases']
    ids = [c['id'] for c in cases]
    require(lines.count('SEQUENCE_DEVICE_OPEN 1') == lines.count('SEQUENCE_DEVICE_CLOSE 1') == 1,
            'expected exactly one device open and close')
    require(re.findall(r'(?m)^SEQUENCE_BEGIN (\d+)$', stdout) == ids and
            re.findall(r'(?m)^SEQUENCE_END (\d+)$', stdout) == ids and
            re.findall(r'(?m)^CAPTURED (\d+) ', stdout) == ids and
            lines.count('CAPTURE_COMPLETE ' + str(len(ids))) == 1, 'partial or reordered sequence')
    buffers = re.findall(r'(?m)^SEQUENCE_BUFFERS generation=(\d+) x=(\d+) y=(\d+) z=(\d+)$', stdout)
    generations = sorted(set(c['generation'] for c in cases))
    require([int(row[0]) for row in buffers] == generations, 'buffer generation mismatch')
    addresses = {}
    for gen, *values in buffers:
        pointers = list(map(int, values))
        ordered = sorted(pointers)
        require(all(32 <= p <= 2**64 - contract['buffer_bytes'] + 32 and p % 4 == 0 for p in pointers)
                and all(b - a >= contract['buffer_bytes'] for a, b in zip(ordered, ordered[1:])),
                'overlapping or invalid sequence buffers')
        addresses[int(gen)] = dict(zip(('x', 'y', 'z'), pointers))
    expected_files = dict(contract['expected'])
    observations = []
    module_order, reject_order = [], []
    previous = None
    for c in cases:
        cid, entry = c['id'], c['entry']
        if entry != previous:
            module_order.append((cid, entry))
        previous = entry
        require(lines.count('SEQUENCE_LAUNCH {id} entry={entry} pc={pc} n={n} block={block} grid={grid} generation={generation}'.format(**c)) == 1,
                'launch descriptor mismatch: ' + cid)
        require(lines.count('CAPTURED {id} n={n} block={block} grid={grid}'.format(**c)) == 1,
                'capture geometry mismatch: ' + cid)
        abi = contract['abi'][entry]
        payload = bytearray(abi['size'])
        for field in abi['fields']:
            value = addresses[c['generation']][field['name']] if field['size'] == 8 else c[field['name']]
            payload[field['offset']:field['offset'] + field['size']] = value.to_bytes(field['size'], 'little')
        name = cid + '_params.bin'
        raw = (output / name).read_bytes()
        require(raw == payload, 'parameter bytes mismatch: ' + cid)
        expected_files[name] = hashlib.sha256(payload).hexdigest()
        if c['reject']:
            reject_order.extend((cid, str(b), '3', '1') for b in (33, 64))
        observations.append(dict(id=cid, entry=entry, generation=c['generation'],
                                 addresses=addresses[c['generation']], params_sha256=expected_files[name]))
    require(re.findall(r'(?m)^SEQUENCE_MODULE (\d+) entry=(\w+)$', stdout) == module_order,
            'module reload order mismatch')
    require(re.findall(r'(?m)^SEQUENCE_REJECT (\d+) block=(\d+) rc=(\d+) event_null=(\d+)$', stdout) == reject_order,
            'invalid launch rejection mismatch')
    require(set(p.name for p in output.iterdir()) == set(expected_files), 'capture file set mismatch')
    for name, digest in expected_files.items():
        require(hashlib.sha256((output / name).read_bytes()).hexdigest() == digest,
                'captured bytes differ: ' + name)
    return dict(status='PASS', launches=len(cases), rejected_launches=len(reject_order),
                buffer_generations=len(generations), device_opens=1, module_loads=len(module_order),
                checked_files=len(expected_files), observations=observations,
                scope='fixed sequence; synchronous invalid launch rejection, not timeout recovery')
