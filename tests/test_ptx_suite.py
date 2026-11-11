"""Author harness checks against explicit arithmetic examples, not device evidence."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from run_ptx_suite import expected_words, launch_args, timing_summary


class SuiteTests(unittest.TestCase):
    def test_explicit_unsigned_examples_and_guards(self):
        x=[99,0xffffffff,0x80000000,88]
        y=[77,2,3,66]
        z=[11,12,13,14]
        self.assertEqual(expected_words('copy',x,y,z,1,2,1),[11,0xffffffff,0x80000000,14])
        self.assertEqual(expected_words('vadd',x,y,z,1,2,1),[11,1,0x80000003,14])
        self.assertEqual(expected_words('affine',x,y,z,1,2,0xffffffff),[11,3,0x80000003,14])
        self.assertEqual(expected_words('affine',x,y,z,1,2,0),[11,2,3,14])
        self.assertEqual(z,[11,12,13,14])

    def test_zero_length_does_not_read_input(self):
        self.assertEqual(expected_words('affine',[],[],[1,2,3],1,0,7),[1,2,3])

    def test_parameter_order_and_access_ranges(self):
        args=launch_args('affine',['x','y','z'],8,17,0xffffffff)
        self.assertEqual([a.buffer for a in args[:3]],['x','y','z'])
        self.assertEqual([(a.offset,a.access_bytes,a.access) for a in args[:3]],[(32,68,'r'),(32,68,'r'),(32,68,'w')])
        self.assertEqual(args[3:],[17,0xffffffff])
        self.assertEqual(len(launch_args('copy',['x','z'],4,0,1)),3)

    def test_timing_keeps_all_samples_and_units(self):
        result=timing_summary([{'host_timing_ns':{'wait':v}} for v in (90,10,20)])
        self.assertEqual(result,{'wait':dict(count=3,min_ns=10,median_ns=20,max_ns=90)})
