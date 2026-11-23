"""Exercise the stop-before-launch rule and host split at the 4 GiB boundary."""

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, call, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import c_v03_high_board as high


class HighBoardTests(unittest.TestCase):
    def test_aliased_dma_ends_the_run_before_loading_a_kernel(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            binding = run / "binding.json"
            binding.write_bytes(b"{}")
            lock = run / "lock.json"
            lock.write_bytes(b"{}")
            context = Mock(state="READY")
            memory = bytearray(high.SIZE)

            def query(_device, key, output):
                output._obj.value = 2 * high.FOUR_GIB if key == 5 else 0

            def write(_handle, _offset, data):
                memory[:] = data

            def close():
                context.state = "CLOSED"

            context.lib.vx_device_query.side_effect = query
            context.write.side_effect = write
            context.read.side_effect = lambda *_: bytes(memory)
            context.close.side_effect = close
            plan = {"modules": {high.WIDE: {"image_sha256": "witness"}}}
            with patch.object(high, "high_preflight", return_value=plan), \
                    patch.object(high, "validate", return_value=({"image_sha256": "witness"}, b"")), \
                    patch.object(high, "Context", return_value=context), \
                    patch.object(high, "reserve", return_value=({"low": 1, "high": 2}, high.ALIAS)):
                with self.assertRaisesRegex(RuntimeError, "alias qualification mismatch"):
                    high.capture(run, run, high.BOARD_BACKEND, binding, lock, run)
            context.load.assert_not_called()
            context.launch.assert_not_called()
            context.close.assert_called_once()
            captured = high.read_json(run / high.BOARD_BACKEND / "capture.json")
            self.assertEqual((captured["alias"], captured["launch_attempts"], captured["device_state"]),
                             ("FAIL", 0, "CLOSED"))
            self.assertEqual((run / high.BOARD_BACKEND / "alias/1-low.bin").read_bytes(), high.pattern(1, "high"))

    def test_full_buffer_readback_joins_transfers_at_the_bank_boundary(self):
        context = Mock()
        base = high.FOUR_GIB - 64
        data = bytes(range(high.SIZE))
        high.write_buffer(context, "handle", base, data)
        self.assertEqual(context.write.call_args_list,
                         [call("handle", 0, data[:64]), call("handle", 64, data[64:])])
        context.read.side_effect = [data[:64], data[64:]]
        self.assertEqual(high.read_buffer(context, "handle", base), data)
        self.assertEqual(context.read.call_args_list, [call("handle", 0, 64), call("handle", 64, 192)])
        self.assertEqual(high.segments(high.FOUR_GIB), ((0, 256),))
