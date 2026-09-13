"""Tests for the key-capture wrapper (injected reader)."""

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


class KeyCaptureTest(unittest.TestCase):
    def capture_with(self, reader):
        return KeyCapture(reader_factory=lambda: reader).capture()

    def test_returns_single_key(self) -> None:
        result = self.capture_with(FakeReader([VK_CODES["KeyK"]]))
        self.assertEqual(result, {"keys": ["KeyK"]})

    def test_returns_chord_in_press_order(self) -> None:
        result = self.capture_with(FakeReader([VK_CODES["ControlLeft"], VK_CODES["Tab"]]))
        self.assertEqual(result, {"keys": ["ControlLeft", "Tab"]})

    def test_escape_cancels(self) -> None:
        result = self.capture_with(FakeReader(None))
        self.assertEqual(result, {"cancelled": True})

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
