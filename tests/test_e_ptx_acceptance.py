"""Receiver-only tests; these do not claim hardware execution coverage."""
import importlib.util
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts/e_acceptance'))
import accept as e_accept


class EAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.out=self.root/'output';self.out.mkdir()
        self.case=next(c for c in e_accept.frozen_cases() if c['entry']=='copy_u32' and c['id']=='0058')
        for role in ('x','z'):
            shutil.copyfile(e_accept.FROZEN/'copy_u32/0058'/(role+'.bin'),self.out/('0058_'+role+'.bin'))
        (self.out/'0058_params.bin').write_bytes(struct.pack('<QQI4x',0x10020,0x20020,32))
        self.log=self.root/'stdout.log'
        self.log.write_text('CAPS threads=4 warps=8 cores=1\nPTX_COPY_ENTRY 6442450996\n'
                            'PTX_COPY_ARGS x=65568 z=131104 n=32\n'
                            'CAPTURED 0058 n=32 block=32 grid=1\nCAPTURE_COMPLETE 1\n')

    def check(self,code=0):
        return e_accept.check_raw(self.case,self.out,self.log,code)

    def test_positive_full_bytes_and_abi(self):
        self.assertEqual(self.check()['status'],'PASS')

    def test_data_input_and_both_guards_rejected(self):
        for role,offset in [('z',32),('z',0),('z',191),('x',40)]:
            p=self.out/('0058_'+role+'.bin');original=p.read_bytes();mutated=bytearray(original);mutated[offset]^=1;p.write_bytes(mutated)
            with self.assertRaisesRegex(ValueError,'full array mismatch'):self.check()
            p.write_bytes(original)

    def test_payload_pointer_n_and_padding_rejected(self):
        p=self.out/'0058_params.bin';original=p.read_bytes()
        for offset in (0,16,20):
            mutated=bytearray(original);mutated[offset]^=1;p.write_bytes(mutated)
            with self.assertRaisesRegex(ValueError,'payload'):self.check()
        p.write_bytes(original)

    def test_missing_output_and_failed_execution_rejected(self):
        with self.assertRaisesRegex(ValueError,'exit'):self.check(3)
        (self.out/'0058_z.bin').unlink()
        with self.assertRaisesRegex(ValueError,'missing'):self.check()

    def test_scalar_math_has_unsigned_wrap(self):
        self.assertEqual(e_accept.oracle.math_word('vadd_u32',0xffffffff,2,1),1)
        self.assertEqual(e_accept.oracle.math_word('affine_u32',0xffffffff,0xffffffff,0xffffffff),0)
        self.assertEqual(e_accept.oracle.math_word('affine_u32',0x80000000,2,0xffffffff),0x80000002)

    def test_launch_and_overlapping_allocations_rejected(self):
        altered=dict(self.case,block=33)
        with self.assertRaisesRegex(ValueError,'B32'):e_accept.oracle.validate_case(altered)
        with self.assertRaisesRegex(ValueError,'overlapping'):
            e_accept.oracle.validate_payload('copy_u32',self.case,(self.out/'0058_params.bin').read_bytes(),{'x':65536,'z':65536})


if __name__=='__main__':unittest.main()
