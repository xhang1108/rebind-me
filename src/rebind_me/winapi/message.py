"""Shared Win32 message-loop types.

``MSG`` and ``POINT`` are used by the low-level key hook
(:mod:`rebind_me.keycapture`) and the tray icon (:mod:`rebind_me.winapi.notifyicon`).
They are defined once here so the two ctypes layouts cannot drift apart.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", POINT),
        ("lPrivate", wintypes.DWORD),
    ]


__all__ = ["MSG", "POINT"]
