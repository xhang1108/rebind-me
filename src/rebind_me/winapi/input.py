"""SendInput keyboard / mouse / scroll injection. See plan.md §7.

Implements the output interface the mapping engine expects
(``key_down`` / ``key_up`` / ``scroll``) plus ``mouse_move`` for the touchpad.
Flag selection is split into pure helpers so it can be unit tested.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from ..errors import RebindError
from ..keys import EXTENDED_CODES, VK_CODES, is_keyboard_code, is_mouse_code, is_scroll_code

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_XDOWN = 0x0080
MOUSEEVENTF_XUP = 0x0100
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000

WHEEL_DELTA = 120
XBUTTON1 = 0x0001
XBUTTON2 = 0x0002

_MOUSE_DOWN_UP = {
    "MouseLeft": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP, 0),
    "MouseRight": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP, 0),
    "MouseMiddle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP, 0),
    "MouseBack": (MOUSEEVENTF_XDOWN, MOUSEEVENTF_XUP, XBUTTON1),
    "MouseForward": (MOUSEEVENTF_XDOWN, MOUSEEVENTF_XUP, XBUTTON2),
}

_SCROLL_WHEEL = {
    "ScrollUp": (MOUSEEVENTF_WHEEL, WHEEL_DELTA),
    "ScrollDown": (MOUSEEVENTF_WHEEL, -WHEEL_DELTA),
    "ScrollRight": (MOUSEEVENTF_HWHEEL, WHEEL_DELTA),
    "ScrollLeft": (MOUSEEVENTF_HWHEEL, -WHEEL_DELTA),
}

ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


def keyboard_flags(code: str, up: bool) -> int:
    """Return the KEYBDINPUT flags for a keyboard ``code``."""
    flags = 0
    if code in EXTENDED_CODES:
        flags |= KEYEVENTF_EXTENDEDKEY
    if up:
        flags |= KEYEVENTF_KEYUP
    return flags


def mouse_button_flags(code: str, up: bool) -> tuple[int, int]:
    """Return ``(flags, mouseData)`` for a mouse button press/release."""
    down, up_flag, data = _MOUSE_DOWN_UP[code]
    return (up_flag if up else down), data


def scroll_flags(code: str) -> tuple[int, int]:
    """Return ``(flags, mouseData)`` for one scroll tick."""
    return _SCROLL_WHEEL[code]


class SendInputOutput:
    """Concrete engine output backed by ``user32.SendInput``."""

    def __init__(self) -> None:
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._user32.SendInput.restype = wintypes.UINT
        self._user32.SendInput.argtypes = (
            wintypes.UINT,
            ctypes.POINTER(INPUT),
            ctypes.c_int,
        )

    def _send(self, inputs: list[INPUT]) -> None:
        if not inputs:
            return
        array = (INPUT * len(inputs))(*inputs)
        sent = self._user32.SendInput(len(inputs), array, ctypes.sizeof(INPUT))
        if sent != len(inputs):
            raise RebindError("INJECTION_FAILED", "SendInput was blocked")

    def _keyboard(self, code: str, up: bool) -> None:
        if not is_keyboard_code(code):
            raise RebindError("INVALID_KEY_CODE", f"unknown keyboard code: {code!r}")
        event = INPUT()
        event.type = INPUT_KEYBOARD
        event.ki = KEYBDINPUT(
            wVk=VK_CODES[code],
            wScan=0,
            dwFlags=keyboard_flags(code, up),
            time=0,
            dwExtraInfo=0,
        )
        self._send([event])

    def key_down(self, code: str) -> None:
        if is_mouse_code(code):
            self._mouse_button(code, up=False)
        elif is_scroll_code(code):
            self.scroll(code)
        else:
            self._keyboard(code, up=False)

    def key_up(self, code: str) -> None:
        if is_mouse_code(code):
            self._mouse_button(code, up=True)
        elif is_scroll_code(code):
            self.scroll(code)
        else:
            self._keyboard(code, up=True)

    def _mouse_button(self, code: str, up: bool) -> None:
        flags, data = mouse_button_flags(code, up)
        event = INPUT()
        event.type = INPUT_MOUSE
        event.mi = MOUSEINPUT(
            dx=0, dy=0, mouseData=data, dwFlags=flags, time=0, dwExtraInfo=0
        )
        self._send([event])

    def scroll(self, code: str) -> None:
        flags, data = scroll_flags(code)
        event = INPUT()
        event.type = INPUT_MOUSE
        event.mi = MOUSEINPUT(
            dx=0, dy=0, mouseData=ctypes.c_uint32(data).value, dwFlags=flags, time=0, dwExtraInfo=0
        )
        self._send([event])

    def mouse_move(self, dx: int, dy: int) -> None:
        event = INPUT()
        event.type = INPUT_MOUSE
        event.mi = MOUSEINPUT(
            dx=int(dx),
            dy=int(dy),
            mouseData=0,
            dwFlags=MOUSEEVENTF_MOVE,
            time=0,
            dwExtraInfo=0,
        )
        self._send([event])


__all__ = [
    "SendInputOutput",
    "keyboard_flags",
    "mouse_button_flags",
    "scroll_flags",
]
