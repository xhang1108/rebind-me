"""Low-level keyboard capture for the UI. See plan.md §7.

A single key is captured with ``WH_KEYBOARD_LL``, blocked from reaching other
applications, and returned as a ``KeyboardEvent.code`` name. Esc cancels and a
15 s timeout returns ``CAPTURE_TIMEOUT``. The reader is injectable so the
surrounding logic can be tested without installing a hook.
"""

from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes
from typing import Callable

from .errors import RebindError
from .keys import HOOK_CODES_BY_VK

CAPTURE_TIMEOUT_SECONDS = 15.0

WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_QUIT = 0x0012
VK_ESCAPE = 0x1B

ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt_x", wintypes.LONG),
        ("pt_y", wintypes.LONG),
    ]


_HOOKPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
)


_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

_user32.SetWindowsHookExW.restype = wintypes.HHOOK
_user32.SetWindowsHookExW.argtypes = (
    ctypes.c_int,
    _HOOKPROC,
    wintypes.HINSTANCE,
    wintypes.DWORD,
)
_user32.UnhookWindowsHookEx.argtypes = (wintypes.HHOOK,)
_user32.CallNextHookEx.restype = ctypes.c_ssize_t
_user32.CallNextHookEx.argtypes = (wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
_user32.GetMessageW.argtypes = (ctypes.POINTER(MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT)
_user32.GetMessageW.restype = ctypes.c_int
_user32.TranslateMessage.argtypes = (ctypes.POINTER(MSG),)
_user32.DispatchMessageW.argtypes = (ctypes.POINTER(MSG),)
_user32.PostQuitMessage.argtypes = (ctypes.c_int,)
_user32.PostThreadMessageW.argtypes = (wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
_kernel32.GetCurrentThreadId.restype = wintypes.DWORD


class WindowsKeyReader:
    """Installs a low-level hook on a worker thread and returns one VK code.

    ``read`` returns ``None`` when Esc cancels, or raises ``TimeoutError``.
    """

    def __init__(self, timeout: float = CAPTURE_TIMEOUT_SECONDS):
        self.timeout = timeout
        self._result: int | None = None
        self._done = threading.Event()
        self._thread_id = 0
        self._thread: threading.Thread | None = None
        self._proc = _HOOKPROC(self._callback)

    def read(self) -> int | None:
        self._thread = threading.Thread(target=self._run, name="key-capture", daemon=True)
        self._thread.start()
        if not self._done.wait(self.timeout):
            if self._thread_id:
                _user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
            self._thread.join(1.0)
            raise TimeoutError("key capture timed out")
        return self._result

    def _callback(self, ncode: int, wparam: int, lparam: int) -> int:
        if ncode == 0 and wparam in (WM_KEYDOWN, WM_SYSKEYDOWN):
            info = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            self._result = None if info.vkCode == VK_ESCAPE else int(info.vkCode)
            self._done.set()
            _user32.PostQuitMessage(0)
        return 1  # block the key while capturing

    def _run(self) -> None:
        self._thread_id = _kernel32.GetCurrentThreadId()
        hook = _user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._proc, None, 0)
        if not hook:
            self._done.set()
            return
        message = MSG()
        try:
            while _user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                _user32.TranslateMessage(ctypes.byref(message))
                _user32.DispatchMessageW(ctypes.byref(message))
        finally:
            _user32.UnhookWindowsHookEx(hook)


class KeyCapture:
    def __init__(
        self,
        timeout: float = CAPTURE_TIMEOUT_SECONDS,
        reader_factory: Callable[[], object] | None = None,
    ):
        self.timeout = timeout
        self._reader_factory = reader_factory or (lambda: WindowsKeyReader(timeout))

    def capture(self) -> dict:
        reader = self._reader_factory()
        try:
            vk = reader.read()  # type: ignore[attr-defined]
        except TimeoutError as error:
            raise RebindError("CAPTURE_TIMEOUT", "key capture timed out", 408) from error
        if vk is None:
            return {"cancelled": True}
        code = HOOK_CODES_BY_VK.get(int(vk))
        if code is None:
            raise RebindError("INVALID_KEY_CODE", f"unsupported key: 0x{int(vk):02X}")
        return {"keyCode": code}


__all__ = ["CAPTURE_TIMEOUT_SECONDS", "KeyCapture", "WindowsKeyReader"]
