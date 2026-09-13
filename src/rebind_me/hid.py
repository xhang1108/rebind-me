"""DualSense USB HID enumeration and I/O. See plan.md §4.

Standard library only, via ``ctypes``. The interface is selected by HID caps
(``OutputReportByteLength == 48`` and ``InputReportByteLength >= 11``), never
by report ID.

This stage provides blocking reads, which is all the fixture recorder needs.
Overlapped / non-blocking reads and reconnect handling land in stage 3.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass

DUALSENSE_VENDOR_ID = 0x054C
DUALSENSE_PRODUCT_ID = 0x0CE6
DUALSENSE_EDGE_PRODUCT_ID = 0x0DF2
DUALSENSE_PRODUCT_IDS = (DUALSENSE_PRODUCT_ID, DUALSENSE_EDGE_PRODUCT_ID)

REQUIRED_OUTPUT_REPORT_LENGTH = 48
MIN_INPUT_REPORT_LENGTH = 11

DIGCF_PRESENT = 0x02
DIGCF_DEVICEINTERFACE = 0x10
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x01
FILE_SHARE_WRITE = 0x02
OPEN_EXISTING = 3
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("InterfaceClassGuid", GUID),
        ("Flags", wintypes.DWORD),
        ("Reserved", ctypes.POINTER(ctypes.c_ulong)),
    ]


class SP_DEVICE_INTERFACE_DETAIL_DATA_W(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("DevicePath", wintypes.WCHAR * 1),
    ]


class HIDD_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("Size", wintypes.ULONG),
        ("VendorID", wintypes.USHORT),
        ("ProductID", wintypes.USHORT),
        ("VersionNumber", wintypes.USHORT),
    ]


class HIDP_CAPS(ctypes.Structure):
    _fields_ = [
        ("Usage", wintypes.USHORT),
        ("UsagePage", wintypes.USHORT),
        ("InputReportByteLength", wintypes.USHORT),
        ("OutputReportByteLength", wintypes.USHORT),
        ("FeatureReportByteLength", wintypes.USHORT),
        ("Reserved", wintypes.USHORT * 17),
        ("NumberLinkCollectionNodes", wintypes.USHORT),
        ("NumberInputButtonCaps", wintypes.USHORT),
        ("NumberInputValueCaps", wintypes.USHORT),
        ("NumberInputDataIndices", wintypes.USHORT),
        ("NumberOutputButtonCaps", wintypes.USHORT),
        ("NumberOutputValueCaps", wintypes.USHORT),
        ("NumberOutputDataIndices", wintypes.USHORT),
        ("NumberFeatureButtonCaps", wintypes.USHORT),
        ("NumberFeatureValueCaps", wintypes.USHORT),
        ("NumberFeatureDataIndices", wintypes.USHORT),
    ]


_setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
_hid = ctypes.WinDLL("hid", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

_setupapi.SetupDiGetClassDevsW.restype = ctypes.c_void_p
_setupapi.SetupDiGetClassDevsW.argtypes = (
    ctypes.POINTER(GUID),
    wintypes.LPCWSTR,
    ctypes.c_void_p,
    wintypes.DWORD,
)
_setupapi.SetupDiEnumDeviceInterfaces.argtypes = (
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.POINTER(GUID),
    wintypes.DWORD,
    ctypes.POINTER(SP_DEVICE_INTERFACE_DATA),
)
_setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = (
    ctypes.c_void_p,
    ctypes.POINTER(SP_DEVICE_INTERFACE_DATA),
    ctypes.POINTER(SP_DEVICE_INTERFACE_DETAIL_DATA_W),
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
    ctypes.c_void_p,
)
_setupapi.SetupDiDestroyDeviceInfoList.argtypes = (ctypes.c_void_p,)

_hid.HidD_GetHidGuid.argtypes = (ctypes.POINTER(GUID),)
_hid.HidD_GetAttributes.argtypes = (ctypes.c_void_p, ctypes.POINTER(HIDD_ATTRIBUTES))
_hid.HidD_GetPreparsedData.argtypes = (
    ctypes.c_void_p,
    ctypes.POINTER(ctypes.c_void_p),
)
_hid.HidD_FreePreparsedData.argtypes = (ctypes.c_void_p,)
_hid.HidP_GetCaps.argtypes = (ctypes.c_void_p, ctypes.POINTER(HIDP_CAPS))

_kernel32.CreateFileW.restype = ctypes.c_void_p
_kernel32.CreateFileW.argtypes = (
    wintypes.LPCWSTR,
    wintypes.DWORD,
    wintypes.DWORD,
    ctypes.c_void_p,
    wintypes.DWORD,
    wintypes.DWORD,
    ctypes.c_void_p,
)
_kernel32.ReadFile.argtypes = (
    ctypes.c_void_p,
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
    ctypes.c_void_p,
)
_kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)


@dataclass(frozen=True)
class HidInterface:
    """A HID interface that matches the DualSense USB output/input caps."""

    path: str
    vendor_id: int
    product_id: int
    input_report_length: int
    output_report_length: int


def _open_path(path: str, access: int) -> int:
    handle = _kernel32.CreateFileW(
        path,
        access,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        None,
        OPEN_EXISTING,
        0,
        None,
    )
    if not handle or handle == INVALID_HANDLE_VALUE:
        raise OSError(
            ctypes.get_last_error(),
            f"CreateFileW failed for {path!r}",
            path,
        )
    return handle


def _query_caps(handle: int) -> tuple[HIDD_ATTRIBUTES, HIDP_CAPS]:
    attributes = HIDD_ATTRIBUTES(Size=ctypes.sizeof(HIDD_ATTRIBUTES))
    if not _hid.HidD_GetAttributes(handle, ctypes.byref(attributes)):
        raise OSError(ctypes.get_last_error(), "HidD_GetAttributes failed")

    preparsed = ctypes.c_void_p()
    if not _hid.HidD_GetPreparsedData(handle, ctypes.byref(preparsed)):
        raise OSError(ctypes.get_last_error(), "HidD_GetPreparsedData failed")
    try:
        caps = HIDP_CAPS()
        status = _hid.HidP_GetCaps(preparsed, ctypes.byref(caps))
        if status != 0x00110000:  # HIDP_STATUS_SUCCESS
            raise OSError(f"HidP_GetCaps failed with status 0x{status:08X}")
    finally:
        _hid.HidD_FreePreparsedData(preparsed)
    return attributes, caps


def _device_paths() -> list[str]:
    guid = GUID()
    _hid.HidD_GetHidGuid(ctypes.byref(guid))
    info = _setupapi.SetupDiGetClassDevsW(
        ctypes.byref(guid), None, None, DIGCF_PRESENT | DIGCF_DEVICEINTERFACE
    )
    if info == INVALID_HANDLE_VALUE:
        raise OSError(ctypes.get_last_error(), "SetupDiGetClassDevsW failed")

    detail_size = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
    paths: list[str] = []
    try:
        index = 0
        while True:
            interface = SP_DEVICE_INTERFACE_DATA(
                cbSize=ctypes.sizeof(SP_DEVICE_INTERFACE_DATA)
            )
            if not _setupapi.SetupDiEnumDeviceInterfaces(
                info, None, ctypes.byref(guid), index, ctypes.byref(interface)
            ):
                break
            index += 1

            required = wintypes.DWORD(0)
            _setupapi.SetupDiGetDeviceInterfaceDetailW(
                info, ctypes.byref(interface), None, 0, ctypes.byref(required), None
            )
            if not required.value:
                continue
            buffer = ctypes.create_string_buffer(required.value)
            detail = ctypes.cast(
                buffer, ctypes.POINTER(SP_DEVICE_INTERFACE_DETAIL_DATA_W)
            )
            detail.contents.cbSize = detail_size
            if not _setupapi.SetupDiGetDeviceInterfaceDetailW(
                info,
                ctypes.byref(interface),
                detail,
                required.value,
                ctypes.byref(required),
                None,
            ):
                continue
            paths.append(ctypes.wstring_at(ctypes.addressof(detail.contents) + 4))
    finally:
        _setupapi.SetupDiDestroyDeviceInfoList(info)
    return paths


def enumerate_interfaces() -> list[HidInterface]:
    """Return DualSense USB interfaces selected by HID caps (plan.md §4)."""
    found: list[HidInterface] = []
    for path in _device_paths():
        handle = 0
        try:
            handle = _open_path(path, GENERIC_READ)
            attributes, caps = _query_caps(handle)
        except OSError:
            continue
        finally:
            if handle:
                _kernel32.CloseHandle(handle)

        if attributes.VendorID != DUALSENSE_VENDOR_ID:
            continue
        if attributes.ProductID not in DUALSENSE_PRODUCT_IDS:
            continue
        if caps.OutputReportByteLength != REQUIRED_OUTPUT_REPORT_LENGTH:
            continue
        if caps.InputReportByteLength < MIN_INPUT_REPORT_LENGTH:
            continue
        found.append(
            HidInterface(
                path=path,
                vendor_id=int(attributes.VendorID),
                product_id=int(attributes.ProductID),
                input_report_length=int(caps.InputReportByteLength),
                output_report_length=int(caps.OutputReportByteLength),
            )
        )
    return found


def open_device(interface: HidInterface) -> int:
    """Open a HID handle for reading and writing. Caller must :func:`close_device`."""
    return _open_path(interface.path, GENERIC_READ | GENERIC_WRITE)


def close_device(handle: int) -> None:
    if handle:
        _kernel32.CloseHandle(handle)


def read_report(handle: int, length: int) -> bytes:
    """Read one input report (blocking). ``length`` is ``InputReportByteLength``."""
    buffer = ctypes.create_string_buffer(length)
    read = wintypes.DWORD(0)
    if not _kernel32.ReadFile(handle, buffer, length, ctypes.byref(read), None):
        raise OSError(ctypes.get_last_error(), "ReadFile failed")
    return buffer.raw[: read.value]


def find_dualsense() -> HidInterface | None:
    """Return the first matching DualSense interface, or ``None``."""
    interfaces = enumerate_interfaces()
    return interfaces[0] if interfaces else None


__all__ = [
    "DUALSENSE_PRODUCT_IDS",
    "DUALSENSE_VENDOR_ID",
    "HidInterface",
    "close_device",
    "enumerate_interfaces",
    "find_dualsense",
    "open_device",
    "read_report",
]
