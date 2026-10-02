"""Process occupant attribution and conflict detection for locked/busy HID devices.

Uses NtQuerySystemInformation with SystemExtendedHandleInformation,
DuplicateHandle, GetFinalPathNameByHandleW with timeout worker threads,
and running process checks for common conflicting apps (Steam, DSX, DS4Windows, etc.).
"""

from __future__ import annotations

import ctypes
import logging
import os
import time
from ctypes import wintypes

_log = logging.getLogger(__name__)

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_ntdll = ctypes.WinDLL("ntdll", use_last_error=True)

STATUS_INFO_LENGTH_MISMATCH = 0xC0000004
SystemExtendedHandleInformation = 64

PROCESS_DUP_HANDLE = 0x0040
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

_kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
_kernel32.DuplicateHandle.argtypes = (
    wintypes.HANDLE,
    wintypes.HANDLE,
    wintypes.HANDLE,
    ctypes.POINTER(wintypes.HANDLE),
    wintypes.DWORD,
    wintypes.BOOL,
    wintypes.DWORD,
)
_kernel32.DuplicateHandle.restype = wintypes.BOOL
_kernel32.GetFinalPathNameByHandleW.argtypes = (
    wintypes.HANDLE,
    wintypes.LPWSTR,
    wintypes.DWORD,
    wintypes.DWORD,
)
_kernel32.GetFinalPathNameByHandleW.restype = wintypes.DWORD
_kernel32.QueryFullProcessImageNameW.argtypes = (
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.LPWSTR,
    ctypes.POINTER(wintypes.DWORD),
)
_kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL

TH32CS_SNAPPROCESS = 0x00000002
MAX_PATH = 260


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_void_p),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * MAX_PATH),
    ]


_kernel32.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
_kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
_kernel32.Process32FirstW.argtypes = (wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W))
_kernel32.Process32FirstW.restype = wintypes.BOOL
_kernel32.Process32NextW.argtypes = (wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W))
_kernel32.Process32NextW.restype = wintypes.BOOL

_ntdll.NtQuerySystemInformation.argtypes = (
    wintypes.ULONG,
    ctypes.c_void_p,
    wintypes.ULONG,
    ctypes.POINTER(wintypes.ULONG),
)
_ntdll.NtQuerySystemInformation.restype = wintypes.LONG

CONFLICTING_PROCESS_NAMES = {
    "steam.exe",
    "dsx.exe",
    "ds4windows.exe",
    "rewasd.exe",
    "dualsensex.exe",
    "dsx_client.exe",
    "gameinputsvc.exe",
}


class SYSTEM_EXTENDED_HANDLE_TABLE_ENTRY_INFO(ctypes.Structure):
    _fields_ = [
        ("Object", ctypes.c_void_p),
        ("UniqueProcessId", ctypes.c_void_p),
        ("HandleValue", ctypes.c_void_p),
        ("GrantedAccess", wintypes.ULONG),
        ("CreatorBackTraceIndex", wintypes.USHORT),
        ("ObjectTypeCodeIndex", wintypes.USHORT),
        ("HandleAttributes", wintypes.ULONG),
        ("Reserved", wintypes.ULONG),
    ]


class SYSTEM_EXTENDED_HANDLE_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("NumberOfHandles", ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong),
        ("Reserved", ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong),
        ("Handles", SYSTEM_EXTENDED_HANDLE_TABLE_ENTRY_INFO * 1),
    ]


def _get_process_name(pid: int) -> tuple[str, str]:
    handle = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle or handle == INVALID_HANDLE_VALUE:
        return "", ""
    try:
        size = wintypes.DWORD(260)
        buffer = ctypes.create_unicode_buffer(size.value)
        if _kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            path = buffer.value
            return os.path.basename(path).lower(), path
        return "", ""
    finally:
        _kernel32.CloseHandle(handle)


OCCUPANT_SCAN_DEADLINE_SECONDS = 10.0
MAX_SCANNED_HANDLES = 50000


def _inspect_handle_once(process_handle, target_pid: int, handle_value: int, target_path_lower: str) -> dict | None:
    """Duplicate one foreign handle; return its owner if it points at the device."""
    dup_handle = wintypes.HANDLE()
    try:
        if not _kernel32.DuplicateHandle(
            process_handle,
            wintypes.HANDLE(handle_value),
            _kernel32.GetCurrentProcess(),
            ctypes.byref(dup_handle),
            0,
            False,
            2,  # DUPLICATE_SAME_ACCESS
        ):
            return None

        buf_size = 512
        path_buf = ctypes.create_unicode_buffer(buf_size)
        chars = _kernel32.GetFinalPathNameByHandleW(dup_handle, path_buf, buf_size, 0)
        if chars <= 0:
            return None
        final_path = path_buf.value.lower()
        if target_path_lower not in final_path and final_path not in target_path_lower:
            return None
        name, full_path = _get_process_name(target_pid)
        if not name:
            return None
        return {"pid": target_pid, "name": name, "path": full_path}
    except Exception as error:
        _log.debug("occupant handle inspect failed for pid %s: %s", target_pid, error)
        return None
    finally:
        if dup_handle and dup_handle != INVALID_HANDLE_VALUE:
            _kernel32.CloseHandle(dup_handle)


def find_device_occupant(device_path: str, deadline_seconds: float = OCCUPANT_SCAN_DEADLINE_SECONDS) -> dict | None:
    """Find the process locking/occupying the device path using NtQuerySystemInformation.

    Single-threaded: process handles are opened once per pid and cached for
    the scan, and the whole scan is bounded by ``deadline_seconds`` so one
    wedged handle cannot stall the HID reconnect loop.
    """
    target_path_lower = device_path.lower().strip()
    if not target_path_lower:
        return None

    # Query system handles
    return_length = wintypes.ULONG(0)
    buffer_size = 1024 * 1024
    buffer = ctypes.create_string_buffer(buffer_size)
    
    status = _ntdll.NtQuerySystemInformation(
        SystemExtendedHandleInformation,
        buffer,
        buffer_size,
        ctypes.byref(return_length),
    )
    # NOTE: NtQuerySystemInformation has restype LONG (signed), so a
    # mismatch comes back negative; compare it unsigned.
    if status & 0xFFFFFFFF == STATUS_INFO_LENGTH_MISMATCH:
        buffer_size = return_length.value + 4096
        buffer = ctypes.create_string_buffer(buffer_size)
        status = _ntdll.NtQuerySystemInformation(
            SystemExtendedHandleInformation,
            buffer,
            buffer_size,
            ctypes.byref(return_length),
        )
    
    if status != 0:
        return None

    try:
        num_handles = ctypes.cast(buffer, ctypes.POINTER(wintypes.ULARGE_INTEGER)).contents.value
    except Exception:
        try:
            num_handles = ctypes.cast(buffer, ctypes.POINTER(wintypes.DWORD)).contents.value
        except Exception:
            return None

    # Parse handles array pointer
    # Offset depends on pointer size (8 bytes for 64-bit, 4 for 32-bit)
    offset = 16 if ctypes.sizeof(ctypes.c_void_p) == 8 else 8
    base_addr = ctypes.addressof(buffer) + offset
    entry_size = ctypes.sizeof(SYSTEM_EXTENDED_HANDLE_TABLE_ENTRY_INFO)

    # Single-threaded scan: no per-handle threads, so a wedged handle can
    # neither pile up joins nor leak daemon threads; the deadline bounds the
    # total, and a timeout is logged so it cannot be mistaken for "no occupant".
    current_pid = os.getpid()
    deadline = time.monotonic() + deadline_seconds
    # Process handles are opened once per pid (PROCESS_DUP_HANDLE only) and
    # closed in the finally below; the count is bounded by live processes,
    # far under MAX_SCANNED_HANDLES.
    proc_handles: dict[int, object] = {}
    dead_pids: set[int] = set()
    try:
        for i in range(min(int(num_handles), MAX_SCANNED_HANDLES)):
            # NOTE: >=, not >: on coarse clocks (Windows ~15.6ms) a zero
            # deadline must still expire on the first check.
            if time.monotonic() >= deadline:
                _log.warning(
                    "occupant scan exceeded %.1fs deadline for %s",
                    deadline_seconds,
                    device_path,
                )
                return None
            entry_addr = base_addr + i * entry_size
            entry = SYSTEM_EXTENDED_HANDLE_TABLE_ENTRY_INFO.from_address(entry_addr)
            pid = int(ctypes.cast(entry.UniqueProcessId, ctypes.c_void_p).value or 0)
            if pid == 0 or pid == current_pid or pid in dead_pids:
                continue

            handle_val = int(ctypes.cast(entry.HandleValue, ctypes.c_void_p).value or 0)

            process_handle = proc_handles.get(pid)
            if process_handle is None:
                process_handle = _kernel32.OpenProcess(PROCESS_DUP_HANDLE, False, pid)
                if not process_handle or process_handle == INVALID_HANDLE_VALUE:
                    dead_pids.add(pid)
                    continue
                proc_handles[pid] = process_handle
            match = _inspect_handle_once(process_handle, pid, handle_val, target_path_lower)
            if match is not None:
                return match
    finally:
        for process_handle in proc_handles.values():
            _kernel32.CloseHandle(process_handle)

    return None


def list_conflicting_processes() -> list[dict]:
    """List running processes that commonly conflict with DualSense controllers.

    Pure-ctypes Toolhelp snapshot using only the standard library.
    """
    conflicts: list[dict] = []
    seen_pids: set[int] = set()

    snapshot = _kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snapshot or snapshot == INVALID_HANDLE_VALUE:
        return []
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        if not _kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
            return []
        while True:
            name = str(entry.szExeFile or "").lower()
            pid = int(entry.th32ProcessID)
            if name in CONFLICTING_PROCESS_NAMES and pid not in seen_pids:
                seen_pids.add(pid)
                _, full_path = _get_process_name(pid)
                conflicts.append({
                    "pid": pid,
                    "name": name,
                    "path": full_path,
                })
            if not _kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                break
    finally:
        _kernel32.CloseHandle(snapshot)

    return conflicts


__all__ = [
    "CONFLICTING_PROCESS_NAMES",
    "find_device_occupant",
    "list_conflicting_processes",
]
