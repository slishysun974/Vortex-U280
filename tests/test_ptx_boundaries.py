"""Boundary evidence checks; synthetic records are not DUT execution."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from ptx_boundary_trace import bind_slots, bind_simx
from run_ptx_boundaries import select_cases, SIZES, BLOCKS


def fire(cycle, block, slot=0):
    return (f'{cycle}: kmu cta-fire: cta_id={block}, block_idx=[{block},0,0], PC=0x180000000, param=0x11000, aligned_lmem_size=0\n'
            f'{cycle}: cluster0-socket0-core0-scheduler-cta_dispatch kmu-accept: cta_id={slot}, PC=0x180000000, param=0x11000, stride=0\n')


def request(cycle, slot=0):
    return f'{cycle}: cluster0-socket0-core0-execute-lsu0 Rd Req: wid=0, cta_id={slot}, PC=0x180000140, tmask=0001, addr={{0x1020}}\n'


def done(cycle, slot=0):
    return f'{cycle}: cluster0-socket0-core0-scheduler-cta_dispatch warp-done: wid=0, cta_id={slot}, rem_warps=0, cta_done=1\n'


class BoundaryTraceTests(unittest.TestCase):
    def test_simx_reused_warp_and_slot_keep_logical_blocks(self):
        def block(index):
            return (f'DEBUG *** dispatch CTA warp: cid=0, wid=0, cta_id=0, rank=0/1, blockIdx=({index},0)\n'
                    'TRACE 10: cluster0-socket0-core0-pipeline decode: cid=0, wid=0, cta_id=0, PC=0x140, ex=LSU (#1)\n'
                    'TRACE 20: cluster0-socket0-core0 warp-state: wid=0, tmask=0000\n')
        raw = block(0) + block(1)
        view, bindings = bind_simx(raw, dict(block=1, grid=2))
        self.assertEqual([b['block'] for b in bindings], [0, 1])
        self.assertIn('cta_id=1, PC=0x140', view)
        with self.assertRaisesRegex(RuntimeError, 'before retirement'):
            bind_simx(raw.replace('TRACE 20: cluster0-socket0-core0 warp-state: wid=0, tmask=0000\n', '', 1), dict(block=1, grid=2))

    def test_simx_physical_warp_can_run_two_ranks_of_one_block(self):
        activation = ('DEBUG *** dispatch CTA warp: cid=0, wid=0, cta_id=0, rank={rank}/2, blockIdx=(0,0)\n'
                      'TRACE 20: cluster0-socket0-core0 warp-state: wid=0, tmask=0000\n')
        raw = activation.format(rank=0) + activation.format(rank=1)
        _, bindings = bind_simx(raw, dict(block=8, grid=1))
        self.assertEqual([b['rank'] for b in bindings], [0, 1])
        with self.assertRaisesRegex(RuntimeError, 'logical warp rank'):
            bind_simx(raw.replace('rank=1/2', 'rank=0/2'), dict(block=8, grid=1))

    def test_reused_slot_is_bound_to_new_logical_block(self):
        raw = fire(10, 0) + request(12) + done(15) + fire(20, 1) + request(22) + done(25)
        view, bindings = bind_slots(raw, 2)
        self.assertIn('22: cluster0-socket0-core0-execute-lsu0 Rd Req: wid=0, cta_id=1,', view)
        self.assertIn('12: cluster0-socket0-core0-execute-lsu0 Rd Req: wid=0, cta_id=0,', view)
        self.assertEqual([b['done_cycle'] for b in bindings], [15, 25])
        self.assertNotIn('cta_id=1, PC=0x180000140', raw)

    def test_rejects_live_slot_reuse_and_missing_retirement(self):
        for raw, message in ((fire(10, 0) + fire(20, 1), 'before retirement'),
                             (fire(10, 0) + request(12), 'missing RTL CTA retirement')):
            with self.subTest(message=message), self.assertRaisesRegex(RuntimeError, message):
                bind_slots(raw, 2 if '20:' in raw else 1)

    def test_rejects_request_after_retirement(self):
        with self.assertRaisesRegex(RuntimeError, 'outside a live CTA'):
            bind_slots(fire(10, 0) + done(15) + request(16), 1)

    def test_rejects_missing_accept_wrong_payload_duplicate_blocks(self):
        valid = fire(10, 0) + done(15)
        for raw, grid in ((valid.replace('10: cluster0', '11: cluster0'), 1),
                          (valid.replace('param=0x11000, stride', 'param=0x12000, stride'), 1),
                          (valid + fire(20, 0) + done(25), 2)):
            with self.subTest(raw=raw), self.assertRaises(RuntimeError):
                bind_slots(raw, grid)


class BoundaryCoverageTests(unittest.TestCase):
    def corpus(self, entry):
        alphas = (0, 1, 0xffffffff) if entry == 'affine_u32' else (1,)
        return dict(cases=[dict(id=str(i), n=n, block=b, alpha=a, repeat=r)
            for i, (n, b, a, r) in enumerate((n, b, a, r) for n in SIZES for b in BLOCKS for a in alphas for r in (0, 1))])

    def test_all_required_sizes_and_small_blocks_are_planned(self):
        for entry, count in (('copy_u32', 21), ('vadd_u32', 21), ('affine_u32', 25)):
            cases = select_cases(entry, self.corpus(entry))
            self.assertEqual(len(cases), count)
            self.assertEqual({c['n'] for c in cases if c['block'] == 32}, set(SIZES))
            self.assertEqual({c['block'] for c in cases}, set(BLOCKS))

    def test_missing_or_duplicate_case_cannot_reduce_coverage(self):
        corpus = self.corpus('copy_u32')
        corpus['cases'] = [c for c in corpus['cases'] if not (c['n'] == 1024 and c['block'] == 32)]
        with self.assertRaisesRegex(RuntimeError, 'coverage mismatch'):
            select_cases('copy_u32', corpus)
        corpus = self.corpus('copy_u32')
        corpus['cases'].append(dict(corpus['cases'][0]))
        with self.assertRaisesRegex(RuntimeError, 'coverage mismatch'):
            select_cases('copy_u32', corpus)


if __name__ == '__main__':
    unittest.main()
