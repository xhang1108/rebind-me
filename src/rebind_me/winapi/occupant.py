"""Process occupant attribution and conflict detection for locked/busy HID devices.

Uses NtQuerySystemInformation with SystemExtendedHandleInformation,
DuplicateHandle, GetFinalPathNameByHandleW with timeout worker threads,
and running process checks for common conflicting apps (Steam, DSX, DS4Windows, etc.).
"""

from __future__ import annotations

import ctypes
import os
import threading
from ctypes import wintypes

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


def _inspect_handle(target_pid: int, handle_value: int, target_path_lower: str, result_holder: list) -> None:
    current_process = _kernel32.OpenProcess(PROCESS_DUP_HANDLE, False, target_pid)
    if not current_process or current_process == INVALID_HANDLE_VALUE:
        return
    dup_handle = wintypes.HANDLE()
    try:
        if not _kernel32.DuplicateHandle(
            current_process,
            wintypes.HANDLE(handle_value),
            _kernel32.GetCurrentProcess(),
            ctypes.byref(dup_handle),
            0,
            False,
            2,  # DUPLICATE_SAME_ACCESS
        ):
            return
        
        buf_size = 512
        path_buf = ctypes.create_unicode_buffer(buf_size)
        chars = _kernel32.GetFinalPathNameByHandleW(dup_handle, path_buf, buf_size, 0)
        if chars > 0:
            final_path = path_buf.value.lower()
            if target_path_lower in final_path or final_path in target_path_lower:
                name, full_path = _get_process_name(target_pid)
                if name:
                    result_holder.append({"pid": target_pid, "name": name, "path": full_path})
    except Exception:
        pass
    finally:
        if dup_handle and dup_handle != INVALID_HANDLE_VALUE:
            _kernel32.CloseHandle(dup_handle)
        _kernel32.CloseHandle(current_process)


def find_device_occupant(device_path: str) -> dict | None:
    """Find the process locking/occupying the device path using NtQuerySystemInformation."""
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
    if status == STATUS_INFO_LENGTH_MISMATCH:
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

    results: list[dict] = []
    
    # Iterate through handles with a timeout worker or limited check
    current_pid = os.getpid()
    for i in range(min(int(num_handles), 50000)):
        entry_addr = base_addr + i * entry_size
        entry = SYSTEM_EXTENDED_HANDLE_TABLE_ENTRY_INFO.from_address(entry_addr)
        pid = int(cast_ptr := ctypes.cast(entry.UniqueProcessId, ctypes.c_void_p).value or 0)
        if pid == 0 or pid == current_pid:
            continue
        
        handle_val = int(cast_h := ctypes.cast(entry.HandleValue, ctypes.c_void_p).value or 0)
        
        # Run inspect in thread with timeout to avoid freezing
        holder: list[dict] = []
        t = threading.Thread(target=_inspect_handle, args=(pid, handle_val, target_path_lower, holder))
        t.daemon = True
        t.start()
        t.join(timeout=0.05)
        if holder:
            return holder[0]

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
