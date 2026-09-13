"""Named-mutex single instance guard. See plan.md §5."""

from __future__ import annotations

import ctypes
from ctypes import wintypes

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

ERROR_ALREADY_EXISTS = 183
kernel32.CreateMutexW.restype = wintypes.HANDLE
kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)

BRIDGE_MUTEX = "Global\\RebindMe-Bridge"
TRAY_MUTEX = "Global\\RebindMe-Tray"


class SingleInstance:
    """Holds a named mutex for the lifetime of the process."""

    def __init__(self, name: str):
        self.name = name
        self._handle: int | None = None

    def acquire(self) -> bool:
        handle = kernel32.CreateMutexW(None, False, self.name)
        if not handle:
            return False
        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            return False
        self._handle = handle
        return True

    def release(self) -> None:
        if self._handle:
            kernel32.CloseHandle(self._handle)
            self._handle = None


__all__ = ["BRIDGE_MUTEX", "TRAY_MUTEX", "SingleInstance"]
