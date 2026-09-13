"""Tests for SendInput flag selection and event construction."""

import unittest

from rebind_me import keys
from rebind_me.winapi import input as win_input


class FlagTest(unittest.TestCase):
    def test_keyboard_flags(self) -> None:
        self.assertEqual(win_input.keyboard_flags("KeyK", up=False), 0)
        self.assertEqual(win_input.keyboard_flags("KeyK", up=True), win_input.KEYEVENTF_KEYUP)
        self.assertEqual(
            win_input.keyboard_flags("ArrowLeft", up=False), win_input.KEYEVENTF_EXTENDEDKEY
        )
        self.assertEqual(
            win_input.keyboard_flags("Delete", up=True),
            win_input.KEYEVENTF_EXTENDEDKEY | win_input.KEYEVENTF_KEYUP,
        )

    def test_mouse_button_flags(self) -> None:
        self.assertEqual(
            win_input.mouse_button_flags("MouseLeft", up=False),
            (win_input.MOUSEEVENTF_LEFTDOWN, 0),
        )
        self.assertEqual(
            win_input.mouse_button_flags("MouseLeft", up=True),
            (win_input.MOUSEEVENTF_LEFTUP, 0),
        )
        self.assertEqual(
            win_input.mouse_button_flags("MouseForward", up=False),
            (win_input.MOUSEEVENTF_XDOWN, win_input.XBUTTON2),
        )

    def test_scroll_flags(self) -> None:
        self.assertEqual(
            win_input.scroll_flags("ScrollUp"),
            (win_input.MOUSEEVENTF_WHEEL, win_input.WHEEL_DELTA),
        )
        self.assertEqual(
            win_input.scroll_flags("ScrollDown"),
            (win_input.MOUSEEVENTF_WHEEL, -win_input.WHEEL_DELTA),
        )
        self.assertEqual(
            win_input.scroll_flags("ScrollRight"),
            (win_input.MOUSEEVENTF_HWHEEL, win_input.WHEEL_DELTA),
        )


class OutputConstructionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.output = win_input.SendInputOutput()
        self.captured: list = []
        self.output._send = lambda inputs: self.captured.extend(inputs)  # type: ignore[method-assign]

    def test_keyboard_event(self) -> None:
        self.output.key_down("KeyK")
        event = self.captured[0]
        self.assertEqual(event.type, win_input.INPUT_KEYBOARD)
        self.assertEqual(event.ki.wVk, keys.VK_CODES["KeyK"])
        self.assertEqual(event.ki.dwFlags, 0)

    def test_mouse_button_event(self) -> None:
        self.output.key_down("MouseRight")
        event = self.captured[0]
        self.assertEqual(event.type, win_input.INPUT_MOUSE)
        self.assertEqual(event.mi.dwFlags, win_input.MOUSEEVENTF_RIGHTDOWN)

    def test_scroll_event_unsigned_data(self) -> None:
        self.output.scroll("ScrollDown")
        event = self.captured[0]
        self.assertEqual(event.mi.mouseData, (-win_input.WHEEL_DELTA) & 0xFFFFFFFF)

    def test_mouse_move_event(self) -> None:
        self.output.mouse_move(5, -3)
        event = self.captured[0]
        self.assertEqual((event.mi.dx, event.mi.dy), (5, -3))
        self.assertEqual(event.mi.dwFlags, win_input.MOUSEEVENTF_MOVE)

    def test_key_down_routes_mouse_and_scroll(self) -> None:
        self.output.key_down("MouseLeft")
        self.output.key_down("ScrollUp")
        self.assertEqual(self.captured[0].type, win_input.INPUT_MOUSE)
        self.assertEqual(self.captured[1].type, win_input.INPUT_MOUSE)


if __name__ == "__main__":
    unittest.main()
