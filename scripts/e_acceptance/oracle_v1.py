"""Non-author E oracle; authored from PTX sources and original inputs only.

This module deliberately imports no project implementation. It is a finite
mathematical oracle for the 15 named B32 cases, not a PTX interpreter.
"""
import argparse
import hashlib
import json
import pathlib
import struct
import sys

CASES = {
    'copy_u32': ('0010', '0058', '0070', '0082', '0094', '0106'),
    'vadd_u32': ('0010', '0058', '0070', '0106'),
    'affine_u32': ('0034', '0176', '0210', '0250', '0322'),
}
GUARD_WORDS = 8
MODULUS = 1 << 32


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode('utf-8')


def math_word(entry, x, y, alpha):
    if entry == 'copy_u32':
        return x
    if entry == 'vadd_u32':
        return (x + y) % MODULUS
    if entry == 'affine_u32':
        return (alpha * x + y) % MODULUS
    raise ValueError('unaccepted entry')


def validate_case(case):
    if case['block'] != 32 or not (1 <= case['grid'] <= (1 << 31) - 1):
        raise ValueError('B32 launch constraint')
    if not (0 <= case['n'] < MODULUS and 0 <= case['alpha'] < MODULUS):
        raise ValueError('u32 scalar constraint')
    if case['grid'] * case['block'] > MODULUS:
        raise ValueError('linear thread index overflow')
    if case['grid'] != max(1, (case['n'] + 31) // 32):
        raise ValueError('fixed corpus grid constraint')
    if case['words'] != max(case['n'], 1) + 2 * GUARD_WORDS:
        raise ValueError('allocation with prefix and suffix guards')


def layout(entry):
    roles = ['x', 'z'] if entry == 'copy_u32' else ['x', 'y', 'z']
    fields = [{'name': role, 'type': 'u64', 'offset': 8*i, 'size': 8}
              for i, role in enumerate(roles)]
    fields.append({'name': 'n', 'type': 'u32', 'offset': len(roles)*8, 'size': 4})
    if entry == 'affine_u32':
        fields.append({'name': 'alpha', 'type': 'u32', 'offset': 28, 'size': 4})
    return {'fields': fields, 'size': 24 if entry == 'copy_u32' else 32,
            'align': 8, 'endian': 'little', 'padding': 'zero',
            'pointer_byte_offset': 32, 'arrays_disjoint': True,
            'grid': '(G,1,1)', 'block': '(32,1,1)', 'shared_bytes': 0}


def validate_payload(entry, case, payload, allocation_bases):
    """Check full bytes from independently supplied allocation addresses.

    Address evidence must come from the executed host/runtime, never from a
    self-reported payload hash. Allocations include guards; pointers are +32.
    """
    validate_case(case)
    spec = layout(entry)
    if len(payload) != spec['size']:
        raise ValueError('payload size')
    expected = bytearray(spec['size'])
    ranges = []
    for field in spec['fields']:
        name, offset = field['name'], field['offset']
        if field['type'] == 'u64':
            base = allocation_bases[name]
            end = base + case['words'] * 4
            if base <= 0 or base % 4 or end > (1 << 64):
                raise ValueError('allocation address range/alignment')
            ranges.append((base, end))
            struct.pack_into('<Q', expected, offset, base + 32)
        else:
            struct.pack_into('<I', expected, offset, case[name])
    for i, (start, end) in enumerate(ranges):
        if any(start < end2 and start2 < end for start2, end2 in ranges[i+1:]):
            raise ValueError('overlapping allocations')
    if payload != bytes(expected):
        raise ValueError('payload pointer/scalar/padding mismatch')
    return True


def expected_arrays(entry, case, inputs):
    validate_case(case)
    for role, data in inputs.items():
        if len(data) != 4 * case['words']:
            raise ValueError('input allocation length: ' + role)
    out = bytearray(inputs['z'])
    # Equivalent to block_id*32 + tid, with each i represented once.
    for i in range(case['n']):
        byte_offset = 4 * (GUARD_WORDS + i)
        x = struct.unpack_from('<I', inputs['x'], byte_offset)[0]
        y = struct.unpack_from('<I', inputs['y'], byte_offset)[0]
        struct.pack_into('<I', out, byte_offset, math_word(entry, x, y, case['alpha']))
    answer = {'x': inputs['x'], 'z': bytes(out)}
    if entry != 'copy_u32':
        answer['y'] = inputs['y']
    return answer


def freeze(root, destination):
    destination.mkdir(parents=True, exist_ok=False)
    own_bytes = pathlib.Path(__file__).read_bytes()
    (destination / 'oracle_v1.py').write_bytes(own_bytes)
    manifest = {
        'schema': 'e-ptx-frozen-oracle-v1', 'author': 'non-author AI agent E',
        'independence': 'Before any DUT output, expected output, comparison, production oracle or packer was read. Only contracts, PTX, corpus case metadata and original inputs were read.',
        'scope': 'Exactly 15 original B32 cases, full allocation bytes and relocated argument ABI. No unseen corpus or full P0 claim.',
        'oracle_sha256': sha(own_bytes),
        'target_lock_sha256': sha((root / 'configs/target_lock.json').read_bytes()),
        'semantics': {'copy_u32': 'z[i]=x[i]', 'vadd_u32': 'z[i]=(x[i]+y[i]) mod 2^32',
                      'affine_u32': 'z[i]=(alpha*x[i]+y[i]) mod 2^32',
                      'active': '0 <= i < N; i=block_id*B+tid; inactive lanes issue no array accesses',
                      'guard_words_each_end': 8, 'inputs_unchanged': True,
                      'n_zero': 'One B32 block must actually launch; arrays unchanged'},
        'abi': {entry: layout(entry) for entry in CASES}, 'cases': [],
    }
    for entry, ids in CASES.items():
        corpus_dir = root / 'results/ptx-frontend-host-20261108-v3' / entry
        corpus = json.loads((corpus_dir / 'corpus.json').read_text(encoding='utf-8'))
        metadata = {c['id']: c for c in corpus['cases']}
        ptx_hash = sha((root / 'ptx/samples' / (entry + '.ptx')).read_bytes())
        for case_id in ids:
            # Ignore implementation-derived expected_loads/stores completely.
            case = {key: metadata[case_id][key] for key in ('id', 'n', 'block', 'grid', 'alpha', 'repeat', 'words')}
            validate_case(case)
            inputs = {role: (corpus_dir / 'inputs' / (case_id + '_' + role + '.bin')).read_bytes()
                      for role in ('x', 'y', 'z')}
            source_payload = (corpus_dir / 'inputs' / (case_id + '_params.bin')).read_bytes()
            spec = layout(entry)
            used = set()
            if len(source_payload) != spec['size']:
                raise ValueError('source payload size')
            for field in spec['fields']:
                used.update(range(field['offset'], field['offset'] + field['size']))
                if field['type'] == 'u32' and struct.unpack_from('<I', source_payload, field['offset'])[0] != case[field['name']]:
                    raise ValueError('source payload scalar differs from metadata')
            if any(b for i,b in enumerate(source_payload) if i not in used):
                raise ValueError('source payload nonzero padding')
            output_dir = destination / entry / case_id
            output_dir.mkdir(parents=True)
            hashes = {}
            for role, data in expected_arrays(entry, case, inputs).items():
                (output_dir / (role + '.bin')).write_bytes(data)
                hashes[role] = sha(data)
            manifest['cases'].append(dict(case, entry=entry, ptx_sha256=ptx_hash,
                inputs_sha256={role: sha(data) for role,data in inputs.items()},
                source_params_sha256=sha(source_payload), expected_sha256=hashes,
                expected_array_reads=case['n']*(1 if entry == 'copy_u32' else 2),
                expected_array_writes=case['n']))
    manifest_data = canonical(manifest)
    (destination / 'manifest.json').write_bytes(manifest_data)
    (destination / 'manifest.sha256').write_text(sha(manifest_data)+'  manifest.json\n', encoding='ascii')
    print(json.dumps({'status':'FROZEN','cases':len(manifest['cases']),
                      'oracle_sha256':sha(own_bytes), 'manifest_sha256':sha(manifest_data),
                      'directory':str(destination)}, sort_keys=True))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=pathlib.Path, default=pathlib.Path('.'))
    parser.add_argument('--freeze', required=True, type=pathlib.Path)
    args = parser.parse_args()
    freeze(args.root, args.freeze)
