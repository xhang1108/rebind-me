"""Shell_NotifyIcon tray plumbing.

A hidden top-level window owns the notification icon so it still receives the
``TaskbarCreated`` broadcast after Explorer restarts. The icon is added, a
popup menu is tracked on right-click, and the message loop runs until exit.
Everything is plain ``ctypes``; there are no third-party dependencies.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from typing import Callable, Sequence

from .message import MSG, POINT

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)

WM_APP = 0x8000
WM_TRAYICON = WM_APP + 1
WM_TRAY_REFRESH = WM_APP + 2
WM_COMMAND = 0x0111
WM_DESTROY = 0x0002
WM_NULL = 0x0000
WM_RBUTTONUP = 0x0205
WM_CONTEXTMENU = 0x007B
WM_LBUTTONDBLCLK = 0x0203

NIM_ADD = 0
NIM_MODIFY = 1
NIM_DELETE = 2

NIF_MESSAGE = 0x01
NIF_ICON = 0x02
NIF_TIP = 0x04
NIF_INFO = 0x10

NIIF_INFO = 0x01
NIIF_WARNING = 0x02
NIIF_ERROR = 0x03
NIIF_NOSOUND = 0x10

MF_STRING = 0x0000
MF_GRAYED = 0x0001
MF_CHECKED = 0x0008
MF_SEPARATOR = 0x0800

TPM_RIGHTBUTTON = 0x0002
TPM_RETURNCMD = 0x0100

IMAGE_ICON = 1
LR_LOADFROMFILE = 0x0010
LR_DEFAULTSIZE = 0x0040
IDI_APPLICATION = 32512

WINDOW_CLASS_NAME = "RebindMeTrayWindow"


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class _VersionUnion(ctypes.Union):
    _fields_ = [("uTimeout", wintypes.UINT), ("uVersion", wintypes.UINT)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("u", _VersionUnion),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", GUID),
        ("hBalloonIcon", wintypes.HICON),
    ]


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("style", wintypes.UINT),
        ("lpfnWndProc", ctypes.c_void_p),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
        ("hIconSm", wintypes.HICON),
    ]


WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
)

user32.RegisterClassExW.argtypes = (ctypes.POINTER(WNDCLASSEXW),)
user32.RegisterClassExW.restype = wintypes.WORD
user32.CreateWindowExW.restype = wintypes.HWND
user32.CreateWindowExW.argtypes = (
    wintypes.DWORD,
    wintypes.LPCWSTR,
    wintypes.LPCWSTR,
    wintypes.DWORD,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.HWND,
    wintypes.HMENU,
    wintypes.HINSTANCE,
    ctypes.c_void_p,
)
user32.DefWindowProcW.restype = ctypes.c_ssize_t
user32.DefWindowProcW.argtypes = (
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
)
user32.DestroyWindow.argtypes = (wintypes.HWND,)
user32.GetMessageW.argtypes = (ctypes.POINTER(MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT)
user32.GetMessageW.restype = wintypes.BOOL
user32.TranslateMessage.argtypes = (ctypes.POINTER(MSG),)
user32.DispatchMessageW.restype = ctypes.c_ssize_t
user32.DispatchMessageW.argtypes = (ctypes.POINTER(MSG),)
user32.PostQuitMessage.argtypes = (ctypes.c_int,)
user32.RegisterWindowMessageW.argtypes = (wintypes.LPCWSTR,)
user32.RegisterWindowMessageW.restype = wintypes.UINT
user32.CreatePopupMenu.restype = wintypes.HMENU
user32.AppendMenuW.argtypes = (
    wintypes.HMENU,
    wintypes.UINT,
    ctypes.c_size_t,
    wintypes.LPCWSTR,
)
user32.TrackPopupMenu.argtypes = (
    wintypes.HMENU,
    wintypes.UINT,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.HWND,
    ctypes.c_void_p,
)
user32.TrackPopupMenu.restype = wintypes.UINT
user32.DestroyMenu.argtypes = (wintypes.HMENU,)
user32.GetCursorPos.argtypes = (ctypes.POINTER(POINT),)
user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
user32.PostMessageW.argtypes = (
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
)
user32.LoadImageW.restype = wintypes.HANDLE
user32.LoadImageW.argtypes = (
    wintypes.HINSTANCE,
    wintypes.LPCWSTR,
    wintypes.UINT,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.UINT,
)
user32.LoadIconW.restype = wintypes.HICON
user32.LoadIconW.argtypes = (wintypes.HINSTANCE, wintypes.LPCWSTR)
user32.DestroyIcon.argtypes = (wintypes.HICON,)
shell32.Shell_NotifyIconW.argtypes = (wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW))
shell32.Shell_NotifyIconW.restype = wintypes.BOOL
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
kernel32.GetModuleHandleW.argtypes = (wintypes.LPCWSTR,)


@dataclass(frozen=True)
class MenuItem:
    """One popup entry; ``id is None`` means a separator."""

    id: int | None
    label: str = ""
    checked: bool = False
    enabled: bool = True


class TrayIcon:
    """Owns the notification icon and its message loop.

    ``menu_items`` is called each time the menu is shown so it can reflect
    current state. ``on_select`` receives the chosen item id.
    """

    def __init__(
        self,
        tooltip: str,
        icon_path: str | None = None,
        menu_items: Callable[[], Sequence[MenuItem]] | None = None,
        on_select: Callable[[int], None] | None = None,
        on_double_click: Callable[[], None] | None = None,
        on_taskbar_created: Callable[[], None] | None = None,
        on_refresh: Callable[[], None] | None = None,
    ):
        self.tooltip = tooltip
        self.icon_path = icon_path
        self.menu_items = menu_items or (lambda: [MenuItem(1, "Exit")])
        self.on_select = on_select or (lambda _id: None)
        self.on_double_click = on_double_click or (lambda: None)
        self.on_taskbar_created = on_taskbar_created or (lambda: None)
        self.on_refresh = on_refresh or (lambda: None)

        self.hwnd: int = 0
        self._hicon: int = 0
        self._owns_icon = False
        self._wndproc = WNDPROC(self._handle_message)
        self._taskbar_created = user32.RegisterWindowMessageW("TaskbarCreated")

    # -- lifecycle --------------------------------------------------------
    def add(self) -> None:
        instance = kernel32.GetModuleHandleW(None)
        window_class = WNDCLASSEXW()
        window_class.cbSize = ctypes.sizeof(WNDCLASSEXW)
        window_class.lpfnWndProc = ctypes.cast(self._wndproc, ctypes.c_void_p)
        window_class.hInstance = instance
        window_class.lpszClassName = WINDOW_CLASS_NAME
        if not user32.RegisterClassExW(ctypes.byref(window_class)):
            error = ctypes.get_last_error()
            if error not in (0, 1410):  # ERROR_CLASS_ALREADY_EXISTS
                raise OSError(error, "RegisterClassExW failed")

        self.hwnd = user32.CreateWindowExW(
            0,
            WINDOW_CLASS_NAME,
            WINDOW_CLASS_NAME,
            0,
            0,
            0,
            0,
            0,
            None,
            None,
            instance,
            None,
        )
        if not self.hwnd:
            raise OSError(ctypes.get_last_error(), "CreateWindowExW failed")

        self._hicon = self._load_icon()
        self._notify(NIM_ADD)

    def run(self) -> None:
        message = MSG()
        while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(message))
            user32.DispatchMessageW(ctypes.byref(message))

    def close(self) -> None:
        if self.hwnd:
            self._notify(NIM_DELETE)
        if self._hicon and self._owns_icon:
            user32.DestroyIcon(self._hicon)
            self._hicon = 0
        if self.hwnd:
            user32.DestroyWindow(self.hwnd)
            self.hwnd = 0

    def quit(self) -> None:
        if self.hwnd:
            user32.PostMessageW(self.hwnd, WM_NULL, 0, 0)
        user32.PostQuitMessage(0)

    def set_tooltip(self, text: str) -> None:
        self.tooltip = text
        if self.hwnd:
            self._notify(NIM_MODIFY)

    def post_refresh(self) -> None:
        if self.hwnd:
            user32.PostMessageW(self.hwnd, WM_TRAY_REFRESH, 0, 0)

    def notify(self, title: str, message: str, flags: int = NIIF_INFO) -> bool:
        """Show a balloon/toast for this icon. No-op before :meth:`add`."""
        if not self.hwnd:
            return False
        data = NOTIFYICONDATAW()
        data.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        data.hWnd = self.hwnd
        data.uID = 1
        data.uFlags = NIF_INFO
        data.szInfoTitle = title[:63]
        data.szInfo = message[:255]
        data.dwInfoFlags = flags
        return bool(shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(data)))

    # -- internals --------------------------------------------------------
    def _load_icon(self) -> int:
        if self.icon_path:
            handle = user32.LoadImageW(
                None,
                self.icon_path,
                IMAGE_ICON,
                0,
                0,
                LR_LOADFROMFILE | LR_DEFAULTSIZE,
            )
            if handle:
                self._owns_icon = True
                return handle
        return user32.LoadIconW(None, wintypes.LPCWSTR(IDI_APPLICATION))

    def _notify(self, action: int) -> bool:
        data = NOTIFYICONDATAW()
        data.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        data.hWnd = self.hwnd
        data.uID = 1
        data.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        data.uCallbackMessage = WM_TRAYICON
        data.hIcon = self._hicon
        data.szTip = self.tooltip[:127]
        return bool(shell32.Shell_NotifyIconW(action, ctypes.byref(data)))

    def _handle_message(self, hwnd, message, wparam, lparam):
        if message == WM_TRAYICON:
            event = lparam & 0xFFFF
            if event in (WM_RBUTTONUP, WM_CONTEXTMENU):
                self._show_menu()
            elif event == WM_LBUTTONDBLCLK:
                self.on_double_click()
            return 0
        if message == WM_COMMAND:
            self.on_select(wparam & 0xFFFF)
            return 0
        if message == WM_TRAY_REFRESH:
            self.on_refresh()
            return 0
        if message == self._taskbar_created:
            self._notify(NIM_ADD)
            self.on_taskbar_created()
            return 0
        if message == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, message, wparam, lparam)

    def _show_menu(self) -> None:
        menu = user32.CreatePopupMenu()
        if not menu:
            return
        try:
            for item in self.menu_items():
                if item.id is None:
                    user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
                    continue
                flags = MF_STRING
                if item.checked:
                    flags |= MF_CHECKED
                if not item.enabled:
                    flags |= MF_GRAYED
                user32.AppendMenuW(menu, flags, item.id, item.label)
            point = POINT()
            user32.GetCursorPos(ctypes.byref(point))
            user32.SetForegroundWindow(self.hwnd)
            chosen = user32.TrackPopupMenu(
                menu,
                TPM_RIGHTBUTTON | TPM_RETURNCMD,
                point.x,
                point.y,
                0,
                self.hwnd,
                None,
            )
            user32.PostMessageW(self.hwnd, WM_NULL, 0, 0)
        finally:
            user32.DestroyMenu(menu)
        if chosen:
            self.on_select(chosen)


__all__ = ["MenuItem", "TrayIcon"]
