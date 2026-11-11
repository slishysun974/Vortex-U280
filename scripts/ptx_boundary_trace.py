"""Relate reused RTL CTA slots to logical blocks without changing raw evidence."""
import re

from ptx_sequence_trace import FIRE, ACCEPT
from run_ptx_copy import require

DONE = re.compile(r'^\s*(\d+): cluster0-socket0-core0-scheduler-cta_dispatch warp-done: wid=\d+, cta_id=(\d+), rem_warps=\d+, cta_done=1\s*$')
REQUEST = re.compile(r'^\s*(\d+): cluster0-socket0-core0-execute-lsu\d+ (?:Rd|Wr) Req: .*?cta_id=(\d+),')
SIM_DISPATCH = re.compile(r'^DEBUG \*\*\* dispatch CTA warp: cid=0, wid=(\d+), cta_id=(\d+), rank=(\d+)/(\d+),.*blockIdx=\((\d+),0\)')
SIM_DECODE = re.compile(r'^TRACE\s+\d+: cluster0-socket0-core0-pipeline decode: cid=0, wid=(\d+), cta_id=(\d+),.*ex=LSU')
SIM_DONE = re.compile(r'^TRACE\s+\d+: cluster0-socket0-core0 warp-state: wid=(\d+), tmask=0000\s*$')


def bind_simx(raw, case):
    """Use warp activation/deactivation and decoded UUIDs for reused SimX slots."""
    live, blocks, output, bindings = {}, {}, [], []
    for line in raw.splitlines(keepends=True):
        dispatch, decode, done = SIM_DISPATCH.match(line), SIM_DECODE.match(line), SIM_DONE.match(line)
        if dispatch:
            wid, slot, rank, size, block = map(int, dispatch.groups())
            require(wid not in live, 'SimX warp reused before retirement')
            require(all(s != slot or b == block for s, b in live.values()), 'SimX CTA slot reused while live')
            ranks = blocks.setdefault(block, set())
            require(size == (case['block'] + 3) // 4 and 0 <= rank < size and rank not in ranks,
                    'duplicate or invalid SimX logical warp rank')
            ranks.add(rank)
            live[wid] = slot, block
            bindings.append(dict(wid=wid, core_slot=slot, block=block, rank=rank))
            line = line[:dispatch.start(2)] + str(block) + line[dispatch.end(2):]
        elif decode:
            wid, slot = map(int, decode.groups())
            require(wid in live and live[wid][0] == slot, 'SimX LSU decode outside live warp')
            line = line[:decode.start(2)] + str(live[wid][1]) + line[decode.end(2):]
        elif done:
            wid = int(done[1])
            require(wid in live, 'SimX retirement without live warp')
            live.pop(wid)
    
        output.append(line)
    require(not live and sorted(blocks) == list(range(case['grid'])) and
            all(len(warps) == (case['block'] + 3) // 4 for warps in blocks.values()),
            'missing SimX block activation or retirement')
    return ''.join(output), bindings


def bind_slots(raw, grid):
    """Assign requests to the currently live block, requiring retirement before reuse."""
    fires, accepts = list(FIRE.finditer(raw)), list(ACCEPT.finditer(raw))
    require(len(fires) == len(accepts) == grid, 'missing or duplicate RTL handshake')
    indexed = {}
    for m in accepts:
        cycle, slot, pc, param = m.groups()
        key = (cycle, pc, param)
        require(key not in indexed, 'ambiguous RTL accept')
        indexed[key] = int(slot)
    bindings = []
    for m in fires:
        cycle, external, block, pc, param = m.groups()
        key = (cycle, pc, param)
        require(key in indexed, 'RTL handshake cycle or payload mismatch')
        bindings.append(dict(cycle=int(cycle), kmu_cta=int(external), block=int(block),
                             core_slot=indexed.pop(key)))
    require(not indexed and sorted(b['block'] for b in bindings) == list(range(grid)),
            'RTL block coverage mismatch')
    live, output, completed = {}, [], set()
    pending = iter(bindings)
    for line in raw.splitlines(keepends=True):
        fire = FIRE.match(line)
        request = REQUEST.match(line)
        done = DONE.match(line)
        if fire:
            binding = next(pending)
            slot = binding['core_slot']
            require(slot not in live, 'RTL slot reused before retirement')
            live[slot] = binding
            line = line[:fire.start(2)] + str(binding['block']) + line[fire.end(2):]
        elif request:
            cycle, slot = map(int, request.groups())
            require(slot in live and cycle >= live[slot]['cycle'], 'RTL LSU outside a live CTA')
            line = line[:request.start(2)] + str(live[slot]['block']) + line[request.end(2):]
        elif done:
            cycle, slot = map(int, done.groups())
            require(slot in live and cycle >= live[slot]['cycle'], 'RTL retirement without live CTA')
            binding = live.pop(slot)
            binding['done_cycle'] = cycle
            completed.add(binding['block'])
        output.append(line)
    require(not live and completed == set(range(grid)), 'missing RTL CTA retirement')
    return ''.join(output), bindings
