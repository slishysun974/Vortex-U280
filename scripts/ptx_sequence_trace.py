"""Bind the one-core RTL KMU and core CTA IDs using observed handshake cycles."""
import re
from ptx_sequence_contract import require

FIRE = re.compile(r'^\s*(\d+): kmu cta-fire: cta_id=(\d+), block_idx=\[(\d+),0,0\], PC=(0x[0-9a-f]+), param=(0x[0-9a-f]+),', re.M)
ACCEPT = re.compile(r'^\s*(\d+): cluster0-socket0-core0-scheduler-cta_dispatch kmu-accept: cta_id=(\d+), PC=(0x[0-9a-f]+), param=(0x[0-9a-f]+),', re.M)


def bind_rtl_dispatches(raw, grid):
    fires, accepts = list(FIRE.finditer(raw)), list(ACCEPT.finditer(raw))
    require(len(fires) == len(accepts) == grid, 'missing or duplicate RTL dispatch handshake')
    indexed = {}
    for match in accepts:
        cycle, internal, pc, param = match.groups()
        key = (cycle, pc, param)
        require(key not in indexed, 'ambiguous core accept at cycle ' + cycle)
        indexed[key] = int(internal)
    bindings = []
    for match in fires:
        cycle, external, block, pc, param = match.groups()
        key = (cycle, pc, param)
        require(key in indexed, 'KMU/core handshake cycle or payload mismatch')
        bindings.append(dict(cycle=int(cycle), kmu_cta=int(external), core_cta=indexed.pop(key), block=int(block)))
    require(not indexed and len({b['core_cta'] for b in bindings}) == grid,
            'reused core CTA ID within a launch')
    replacements = iter(bindings)

    def replace(match):
        binding = next(replacements)
        local_start = match.start(2) - match.start()
        local_end = match.end(2) - match.start()
        # Only the analysis view changes; raw evidence is never rewritten.
        return match[0][:local_start] + str(binding['core_cta']) + match[0][local_end:]

    return FIRE.sub(replace, raw), bindings
