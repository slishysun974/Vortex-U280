"""Receiver fault controls only; synthetic fixtures are not device evidence."""
import copy
from pathlib import Path
import struct
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/e_acceptance"))
from runtime_unseen_common import corpus, sha
from runtime_unseen_check import check_case


class UnseenReceiverControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frozen = ROOT / "configs/acceptance/e-runtime-unseen-20261111-v1"
        cls.manifest = corpus(cls.frozen)

    def fixture(self, index=6):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        case = self.manifest["cases"][index]
        folder = root / case["id"]
        folder.mkdir()
        bases = dict(x=0x100000000, y=0x200000000, z=0x300000000)
        pointers = {role: bases[role] + 4 * case["offsets_words"][role] for role in bases}
        if case["semantics"] == "copy":
            params = struct.pack("<QQI4x", pointers["x"], pointers["z"], case["n"])
        elif case["semantics"] == "vadd":
            params = struct.pack("<QQQI4x", pointers["x"], pointers["y"], pointers["z"], case["n"])
        else:
            params = struct.pack("<QQQII", pointers["x"], pointers["y"], pointers["z"], case["n"], case["alpha"])
        for role in bases:
            source = role + (".expected.bin" if role == "z" else ".input.bin")
            (folder / (role + ".actual.bin")).write_bytes((self.frozen / "vectors" / case["id"] / source).read_bytes())
        for name in ("params.plan.bin", "params.before_mutation.bin", "params.after_mutation.bin"):
            (folder / name).write_bytes(params)
        state = dict(device_state="READY", generation=0, first_error=None, device_fault=None)
        actual = dict(id=case["id"], module=case["module"], allocation_generation=case["allocation_generation"],
                      status="CAPTURED", phases=dict(load="PASS", H2D="PASS", launch="PASS", wait="PASS", D2H="PASS"),
                      grid=[case["grid"], 1, 1], block=[case["block"], 1, 1], before=state, after=state,
                      launched=dict(state, device_state="RUNNING"), wait=dict(status="COMPLETE", event_id=1, generation=0),
                      event_id=1, event_completed=True, bases=bases,
                      files={p.name: sha(p.read_bytes()) for p in folder.iterdir()})
        return root, case, actual

    def test_positive_full_and_zero(self):
        for index in (0, 6, 16):
            check_case(*self.fixture(index))

    def test_corrupted_arrays_and_sentinels_rejected(self):
        for role, position in (("x", 0), ("y", 5), ("z", 0), ("z", 2399), ("z", 156)):
            with self.subTest(role=role, position=position):
                root, case, actual = self.fixture()
                path = root / case["id"] / (role + ".actual.bin")
                data = bytearray(path.read_bytes())
                data[position] ^= 1
                path.write_bytes(data)
                with self.assertRaises(ValueError):
                    check_case(root, case, actual)

    def test_argument_bytes_and_snapshot_rejected(self):
        for name in ("params.plan.bin", "params.before_mutation.bin", "params.after_mutation.bin"):
            root, case, actual = self.fixture(0)
            path = root / case["id"] / name
            data = bytearray(path.read_bytes())
            data[-1] = 1  # copy ABI padding must remain zero
            path.write_bytes(data)
            with self.assertRaises(ValueError):
                check_case(root, case, actual)

    def test_incorrect_state_geometry_identity_rejected(self):
        mutations = [lambda a: a.update(event_completed=False), lambda a: a.update(block=[32, 1, 1]),
                     lambda a: a.update(module="copy"), lambda a: a["after"].update(device_state="RUNNING"),
                     lambda a: a["after"].update(generation=1), lambda a: a["after"].update(device_fault={"native_status": 8}),
                     lambda a: a["bases"].update(x=a["bases"]["x"] + 4), lambda a: a["wait"].update(event_id=2)]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                root, case, actual = self.fixture()
                actual = copy.deepcopy(actual)
                mutate(actual)
                with self.assertRaises(ValueError):
                    check_case(root, case, actual)


if __name__ == "__main__":
    unittest.main()
