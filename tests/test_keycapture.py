"""Tests for the key-capture wrapper (injected reader)."""

import threading
import unittest

from rebind_me.errors import RebindError
from rebind_me.keycapture import KeyCapture
from rebind_me.keys import VK_CODES


class FakeReader:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error

    def read(self):
        if self.error is not None:
            raise self.error
        return self.result


class BlockingReader:
    """Blocks in ``read`` until ``cancel`` is called."""

    def __init__(self, started):
        self.started = started
        self._done = threading.Event()

    def read(self):
        self.started.set()
        self._done.wait(2.0)
        return None

    def cancel(self):
        self._done.set()


class KeyCaptureTest(unittest.TestCase):
    def capture_with(self, reader):
        return KeyCapture(reader_factory=lambda: reader).capture()

    def test_returns_single_key(self) -> None:
        result = self.capture_with(FakeReader([VK_CODES["KeyK"]]))
        self.assertEqual(result, {"keys": ["KeyK"]})

    def test_escape_is_captured_like_any_key(self) -> None:
        result = self.capture_with(FakeReader([VK_CODES["Escape"]]))
        self.assertEqual(result, {"keys": ["Escape"]})

    def test_returns_chord_in_press_order(self) -> None:
        result = self.capture_with(FakeReader([VK_CODES["ControlLeft"], VK_CODES["Tab"]]))
        self.assertEqual(result, {"keys": ["ControlLeft", "Tab"]})

    def test_cancel_aborts_running_capture(self) -> None:
        started = threading.Event()
        reader = BlockingReader(started)
        capture = KeyCapture(reader_factory=lambda: reader)
        results: list[dict] = []
        worker = threading.Thread(target=lambda: results.append(capture.capture()))
        worker.start()
        self.assertTrue(started.wait(1.0))
        self.assertEqual(capture.cancel(), {"cancelled": True})
        worker.join(2.0)
        self.assertEqual(results, [{"cancelled": True}])

    def test_cancel_is_safe_when_idle(self) -> None:
        self.assertEqual(KeyCapture().cancel(), {"cancelled": True})

    def test_timeout(self) -> None:
        with self.assertRaises(RebindError) as ctx:
            self.capture_with(FakeReader(error=TimeoutError()))
        self.assertEqual(ctx.exception.code, "CAPTURE_TIMEOUT")
        self.assertEqual(ctx.exception.status, 408)

    def test_unknown_vk(self) -> None:
        with self.assertRaises(RebindError) as ctx:
            self.capture_with(FakeReader([0x9999]))
        self.assertEqual(ctx.exception.code, "INVALID_KEY_CODE")


if __name__ == "__main__":
    unittest.main()
