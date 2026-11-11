"""Transport/receipt checks only; no SSH or hardware execution."""
import ast
from pathlib import Path
import sys
import tempfile
import unittest
import hashlib
import json
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import c_runtime_board as board


class BoardTransportTests(unittest.TestCase):
    def test_remote_bootstrap_parses_on_python36(self):
        ast.parse((ROOT/'scripts/c_runtime_board.py').read_text(),feature_version=(3,6))

    def test_packaged_runtime_parses_on_python36(self):
        for name in (*board.PY_FILES,'check_c_runtime_compat.py'):
            with self.subTest(name=name):
                ast.parse((ROOT/'scripts'/name).read_text(),feature_version=(3,6))

    def test_backport_matches_pinned_distribution(self):
        vendor=ROOT/'third_party/dataclasses-0.8'
        wheel=(vendor/'dataclasses-0.8-py3-none-any.whl').read_bytes()
        self.assertEqual(hashlib.sha256(wheel).hexdigest(),
            '0201d89fa866f68c8ebd9d08ee6ff50c0b255f8ec63a71c16fda7af82bb887bf')
        with zipfile.ZipFile(vendor/'dataclasses-0.8-py3-none-any.whl') as archive:
            self.assertEqual((vendor/'dataclasses.py').read_bytes(),archive.read('dataclasses.py'))
            self.assertEqual((vendor/'LICENSE.txt').read_bytes(),archive.read('dataclasses-0.8.dist-info/LICENSE.txt'))
        for name,digest in json.loads((vendor/'provenance.json').read_bytes())['files'].items():
            self.assertEqual(hashlib.sha256((vendor/name).read_bytes()).hexdigest(),digest)

    def test_capture_paths_cannot_escape_receiver(self):
        for name in ('../escape','/absolute','a/../escape','a//b','./a','C:/a','a\\b','a/b/..'):
            with self.subTest(name=name),self.assertRaises(ValueError):board.safe_member(name)

    def test_raw_bytes_roundtrip_and_tamper_rejection(self):
        encoded=board.encode({'execution/copy/case-00/observed_z.bin':bytes(range(256))})
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            board.decode_into(encoded,root/'good')
            self.assertEqual((root/'good/execution/copy/case-00/observed_z.bin').read_bytes(),bytes(range(256)))
            item=next(iter(encoded.values()));item['sha256']='0'*64
            with self.assertRaises(ValueError):board.decode_into(encoded,root/'bad')
            self.assertFalse((root/'bad/execution/copy/case-00/observed_z.bin').exists())

    def test_receiver_does_not_overwrite_existing_files(self):
        encoded=board.encode({'existing.bin':b'new'})
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);(root/'existing.bin').write_bytes(b'original')
            with self.assertRaises(FileExistsError):board.decode_into(encoded,root)
            self.assertEqual((root/'existing.bin').read_bytes(),b'original')
