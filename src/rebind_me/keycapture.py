"""Low-level keyboard capture for the UI.

A single key is captured with ``WH_KEYBOARD_LL``, blocked from reaching other
applications, and returned as a ``KeyboardEvent.code`` name. Any key can be
mapped, including Esc; cancellation goes through :meth:`KeyCapture.cancel` and
a 15 s timeout returns ``CAPTURE_TIMEOUT``. The reader is injectable so the
surrounding logic can be tested without installing a hook.
"""

from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes
from typing import Callable

from .errors import RebindError
from .keys import HOOK_CODES_BY_VK
from .winapi.message import MSG

CAPTURE_TIMEOUT_SECONDS = 15.0

WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_QUIT = 0x0012

ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
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


_UNSET = object()


class WindowsKeyReader:
    """Captures one chord (all keys held together) with a low-level hook.

    Records every keydown until all keys are released, so Ctrl+Tab comes back
    as ``["ControlLeft", "Tab"]``. Every key (including Esc) is a valid capture;
    ``read`` returns ``None`` only when :meth:`cancel` is called from another
    thread, or raises ``TimeoutError``. Every key is blocked while capturing.
    """

    def __init__(self, timeout: float = CAPTURE_TIMEOUT_SECONDS):
        self.timeout = timeout
        self._result: object = _UNSET
        self._done = threading.Event()
        self._lock = threading.Lock()
        self._thread_id = 0
        self._thread: threading.Thread | None = None
        self._proc = _HOOKPROC(self._callback)
        self._all_pressed: list[int] = []
        self._currently_down: set[int] = set()

    def read(self) -> list[int] | None:
        self._thread = threading.Thread(target=self._run, name="key-capture", daemon=True)
        self._thread.start()
        if not self._done.wait(self.timeout):
            self.cancel()
            self._thread.join(1.0)
            raise TimeoutError("key capture timed out")
        if self._result is _UNSET:
            return None
        return self._result  # type: ignore[return-value]

    def cancel(self) -> None:
        """Abort the capture from any thread; ``read`` returns ``None``."""
        self._finish(None)

    def _finish(self, result: list[int] | None) -> None:
        with self._lock:
            if self._result is _UNSET:
                self._result = result
        self._done.set()
        if self._thread_id:
            _user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        else:
            _user32.PostQuitMessage(0)

    def _callback(self, ncode: int, wparam: int, lparam: int) -> int:
        if ncode == 0 and wparam in (WM_KEYDOWN, WM_SYSKEYDOWN):
            vk = int(ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents.vkCode)
            if vk not in self._currently_down:
                self._currently_down.add(vk)
                self._all_pressed.append(vk)
        elif ncode == 0 and wparam in (WM_KEYUP, WM_SYSKEYUP):
            vk = int(ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents.vkCode)
            self._currently_down.discard(vk)
            if self._all_pressed and not self._currently_down:
                self._finish(list(self._all_pressed))
        return 1  # block the key while capturing

    def _run(self) -> None:
        self._thread_id = _kernel32.GetCurrentThreadId()
        hook = _user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._proc, None, 0)
        if not hook:
            self._result = None
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
        self._lock = threading.Lock()
        self._current: object | None = None
        self._cancelled = threading.Event()

    def capture(self) -> dict:
        self._cancelled.clear()
        reader = self._reader_factory()
        with self._lock:
            self._current = reader
        # A cancel may have arrived before the reader was registered.
        if self._cancelled.is_set():
            cancel = getattr(reader, "cancel", None)
            if cancel is not None:
                cancel()
        try:
            vks = reader.read()  # type: ignore[attr-defined]
        except TimeoutError as error:
            raise RebindError("CAPTURE_TIMEOUT", "key capture timed out", 408) from error
        finally:
            with self._lock:
                self._current = None
        if vks is None:
            return {"cancelled": True}
        codes: list[str] = []
        for vk in vks:
            code = HOOK_CODES_BY_VK.get(int(vk))
            if code is None:
                raise RebindError("INVALID_KEY_CODE", f"unsupported key: 0x{int(vk):02X}")
            if code not in codes:
                codes.append(code)
        return {"keys": codes}

    def cancel(self) -> dict:
        """Abort the capture in progress, if any. Safe to call when idle."""
        self._cancelled.set()
        with self._lock:
            reader = self._current
        cancel = getattr(reader, "cancel", None) if reader is not None else None
        if cancel is not None:
            cancel()
        return {"cancelled": True}


__all__ = ["CAPTURE_TIMEOUT_SECONDS", "KeyCapture", "WindowsKeyReader"]
