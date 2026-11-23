"""Host controls for the C V03 corpus and the readback comparison."""
import ctypes
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import check_c_v03_receipt as receipt
import freeze_c_v03_cases as vectors


class ReceiverTests(unittest.TestCase):
    def test_partial_warp_wide_product_and_unwritten_store(self):
        buffers = dict(x=list(range(32)), z=list(range(1000, 1200)))
        vectors.form_outputs(buffers, dict(x=3, z=5), 3, (1 << 30) + 2)
        def column(number):
            return buffers["z"][5 + 4 * number:9 + 4 * number]
        self.assertEqual(column(16), [5, 6, 9, 1072])  # shifted, shifted, alternate, absent
        self.assertEqual(column(40), [3, 4, 1167, 1168])
        self.assertEqual(column(41), [1169, 1170, 5, 1172])

    def test_cta_local_skip_and_global_tail(self):
        buffers = dict(x=[0xffffffff] * 32, z=[13] * 32, audit=[7] * 32)
        vectors.wide_outputs(buffers, dict(x=0, z=1, audit=3), 5, 2, [9, 1, (1 << 30) + 2])
        active = {0, 2, 3, 4, 5, 7, 8}
        self.assertEqual({i for i, word in enumerate(buffers["z"]) if word == 0}, {4 + i for i in active})
        self.assertEqual(buffers["audit"][3:13], [1 if i in active else 0xa5a55a5c for i in range(10)])

    def test_offline_review_checks_each_array_and_payload_padding(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            frozen = root / "corpus"
            expected = frozen / "case"
            model = root / "simx"
            actual = model / "case"
            expected.mkdir(parents=True)
            actual.mkdir(parents=True)
            binding = model / "binding.json"
            binding.write_bytes(b"{}")
            caps = dict(backend="simx", device_state="READY", threads=4, warps=8, cores=1, generation=1)
            entry = receipt.FORMS
            event = dict(status="COMPLETE", event_id=1, generation=1, backend="simx")
            row = dict(id="case", entry=entry, grid=[1, 1, 1], block=[1, 1, 1], launched="RUNNING",
                       after="READY", event=event)
            bases = dict(x=32, z=64, audit=96)
            record = dict(initial=caps, final_state="CLOSED", binding_sha256=receipt.sha256(binding),
                          native_bases=bases, cases=[row], loads=[entry])
            (model / "capture.json").write_text(json.dumps(record))
            case = dict(id="case", entry=entry, grid=1, block=1, offsets=dict.fromkeys(bases, 0), scalars=[7])
            manifest = dict(words=1, cases=[case])
            for role, value in bases.items():
                data = struct.pack("<I", value)
                (expected / (role + ".expected.bin")).write_bytes(data)
                (actual / (role + ".actual.bin")).write_bytes(data)
            (actual / "params.bin").write_bytes(struct.pack("<QQI4x", 32, 64, 7))
            with patch.object(receipt, "BINDINGS", root):
                self.assertEqual(receipt.review_backend(root, frozen, "simx", manifest)["launches"], 1)
                for path in actual.iterdir():
                    original = path.read_bytes()
                    path.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
                    with self.subTest(file=path.name), self.assertRaises(RuntimeError):
                        receipt.review_backend(root, frozen, "simx", manifest)
                    path.write_bytes(original)

    def test_capture_stops_after_first_bad_readback(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            frozen = root / "corpus"
            case = frozen / "first"
            case.mkdir(parents=True)
            binding = root / "binding.json"
            binding.write_bytes(b"{}")
            for role in receipt.ROLES:
                (case / (role + ".input.bin")).write_bytes(bytes(4))
                (case / (role + ".expected.bin")).write_bytes(struct.pack("<I", int(role == "z")))
            spec = dict(id="first", entry=receipt.FORMS, block=1, grid=1, offsets=dict.fromkeys(receipt.ROLES, 0),
                        scalars=[1])
            manifest = dict(words=1, cases=[spec, dict(spec, id="second")])
            runtime = Mock(state="READY")
            runtime.alloc.side_effect = receipt.ROLES
            runtime.buffers = {role: (None, 4) for role in receipt.ROLES}
            runtime.lib.vx_buffer_address.return_value = 0
            runtime.launch.return_value = Mock(payload=ctypes.create_string_buffer(bytes(24)),
                                               plan=Mock(payload=bytes(24), grid=[1, 1, 1], block=[1, 1, 1]))
            runtime.query_caps.return_value = dict(device_state="READY")
            runtime.wait.return_value = dict(status="COMPLETE")
            runtime.read.return_value = bytes(4)

            def close():
                runtime.state = "CLOSED"

            runtime.close.side_effect = close
            lock = root / "target_lock.json"
            with patch.object(receipt, "Context", return_value=runtime) as create:
                with self.assertRaisesRegex(RuntimeError, "first/z readback differs"):
                    receipt.capture(root, frozen, "u280-xrt", manifest, binding=binding, target_lock=lock)
            create.assert_called_once_with(binding, lock, backend="u280-xrt", run_id=root.name)
            runtime.launch.assert_called_once()
            runtime.close.assert_called_once()
            capture = receipt.read_json(root / "u280-xrt/capture.json")
            self.assertEqual(capture["current_case"], "first")
            self.assertEqual(capture["launch_attempts"], 1)
            self.assertEqual(capture["final_state"], "CLOSED")
            self.assertEqual(capture["error"], "first/z readback differs")
            self.assertFalse((root / "u280-xrt/second").exists())
