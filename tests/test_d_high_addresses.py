"""Controls for the model capture checker, using byte fixtures only."""
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from run_d_high_addresses import GUARD, ROLES, SIZE, check, vectors, write_json


class HighAddressCaptureTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        case, inputs, expected = vectors("high_to_low")
        self.root = Path(temp.name) / case["id"]
        self.stage = self.root / "xrtsim"
        self.stage.mkdir(parents=True)
        write_json(self.root / "case.json", case)
        pointers = {r: case["bases"][r] + 4 * GUARD for r in ROLES}
        caps = dict(threads=4, warps=8, cores=1, global_bytes=2**33, vm=0)
        write_json(self.stage / "reservations.json", dict(caps=caps, bases=case["bases"],
                                                         pointers=pointers, bytes_per_buffer=SIZE))
        for role in ROLES:
            (self.root / (role + ".input.bin")).write_bytes(inputs[role])
            (self.root / (role + ".expected.bin")).write_bytes(expected[role])
            (self.stage / (role + ".before.bin")).write_bytes(inputs[role])
            (self.stage / (role + ".after.bin")).write_bytes(expected[role])
        self.payload = struct.pack("<QQQIII4x", *(pointers[r] for r in ROLES), case["n"],
                                   case["skip_lane"], case["bias"])
        (self.stage / "params.bin").write_bytes(self.payload)

    def compare(self):
        return check(self.root, "xrtsim", "HIGH_ADDRESS_COMPLETE xrtsim high_to_low\n")[0]

    def test_equal_low_words_can_be_distinguished(self):
        x, z = struct.unpack_from("<QQ", self.payload)
        self.assertEqual(x - z, 1 << 32)
        self.assertEqual(self.compare()["status"], "PASS")

    def test_dropped_high_bit_in_payload_is_detected(self):
        data = bytearray(self.payload)
        data[4] = 0
        (self.stage / "params.bin").write_bytes(data)
        with self.assertRaisesRegex(RuntimeError, "ABI"):
            self.compare()

    def test_prelaunch_alias_is_detected_even_with_correct_final_output(self):
        (self.stage / "z.before.bin").write_bytes((self.stage / "x.before.bin").read_bytes())
        with self.assertRaisesRegex(RuntimeError, "pre-launch data"):
            self.compare()

    def test_single_clobbered_guard_byte_is_detected(self):
        path = self.stage / "z.after.bin"
        data = bytearray(path.read_bytes())
        data[-1] ^= 1
        path.write_bytes(data)
        with self.assertRaisesRegex(RuntimeError, "post-launch data"):
            self.compare()
