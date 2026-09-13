"""DualSense USB HID enumeration and I/O. See plan.md §4.

Standard library only, via ``ctypes``. The interface is selected by HID caps
(``OutputReportByteLength == 48`` and ``InputReportByteLength >= 11``), never
by report ID.

This stage provides blocking reads, which is all the fixture recorder needs.
Overlapped / non-blocking reads and reconnect handling land in stage 3.
"""

from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes
from dataclasses import dataclass

from .errors import RebindError

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
FILE_FLAG_OVERLAPPED = 0x40000000
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

ERROR_ACCESS_DENIED = 5
ERROR_SHARING_VIOLATION = 32
ERROR_IO_PENDING = 997
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 258
WAIT_FAILED = 0xFFFFFFFF

ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong


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


class OVERLAPPED(ctypes.Structure):
    _fields_ = [
        ("Internal", ULONG_PTR),
        ("InternalHigh", ULONG_PTR),
        ("Offset", wintypes.DWORD),
        ("OffsetHigh", wintypes.DWORD),
        ("hEvent", wintypes.HANDLE),
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
    ctypes.POINTER(OVERLAPPED),
)
_kernel32.WriteFile.argtypes = (
    ctypes.c_void_p,
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
    ctypes.POINTER(OVERLAPPED),
)
_kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
_kernel32.CreateEventW.restype = wintypes.HANDLE
_kernel32.CreateEventW.argtypes = (
    ctypes.c_void_p,
    wintypes.BOOL,
    wintypes.BOOL,
    wintypes.LPCWSTR,
)
_kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
_kernel32.WaitForSingleObject.restype = wintypes.DWORD
_kernel32.GetOverlappedResult.argtypes = (
    ctypes.c_void_p,
    ctypes.POINTER(OVERLAPPED),
    ctypes.POINTER(wintypes.DWORD),
    wintypes.BOOL,
)
_kernel32.CancelIo.argtypes = (ctypes.c_void_p,)


@dataclass(frozen=True)
class HidInterface:
    """A HID interface that matches the DualSense USB output/input caps."""

    path: str
    vendor_id: int
    product_id: int
    input_report_length: int
    output_report_length: int


def _open_path(path: str, access: int, flags: int = 0) -> int:
    handle = _kernel32.CreateFileW(
        path,
        access,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        None,
        OPEN_EXISTING,
        flags,
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


class WindowsHidDevice:
    """Overlapped, interruptible HID handle for one DualSense interface."""

    def __init__(self, interface: HidInterface):
        self.interface = interface
        self.input_report_length = interface.input_report_length
        self.output_report_length = interface.output_report_length
        self._handle = _open_path(
            interface.path, GENERIC_READ | GENERIC_WRITE, FILE_FLAG_OVERLAPPED
        )
        self._read_event = _kernel32.CreateEventW(None, False, False, None)
        self._write_event = _kernel32.CreateEventW(None, False, False, None)
        if not self._read_event or not self._write_event:
            self.close()
            raise OSError(ctypes.get_last_error(), "CreateEventW failed")

    def read(self, timeout_ms: int) -> bytes | None:
        """Read one report; ``None`` on timeout (so the caller can poll stop)."""
        buffer = ctypes.create_string_buffer(self.input_report_length)
        read = wintypes.DWORD(0)
        overlapped = OVERLAPPED()
        overlapped.hEvent = self._read_event
        if not _kernel32.ReadFile(
            self._handle,
            buffer,
            self.input_report_length,
            ctypes.byref(read),
            ctypes.byref(overlapped),
        ):
            error = ctypes.get_last_error()
            if error != ERROR_IO_PENDING:
                raise OSError(error, "ReadFile failed")
            wait = _kernel32.WaitForSingleObject(self._read_event, timeout_ms)
            if wait == WAIT_TIMEOUT:
                _kernel32.CancelIo(self._handle)
                _kernel32.WaitForSingleObject(self._read_event, 1000)
                return None
            if wait != WAIT_OBJECT_0:
                raise OSError(ctypes.get_last_error(), "WaitForSingleObject failed")
            if not _kernel32.GetOverlappedResult(
                self._handle, ctypes.byref(overlapped), ctypes.byref(read), False
            ):
                raise OSError(ctypes.get_last_error(), "GetOverlappedResult failed")
        return buffer.raw[: read.value]

    def write(self, data: bytes) -> None:
        payload = bytes(data)
        buffer = ctypes.create_string_buffer(payload, len(payload))
        written = wintypes.DWORD(0)
        overlapped = OVERLAPPED()
        overlapped.hEvent = self._write_event
        if not _kernel32.WriteFile(
            self._handle,
            buffer,
            len(payload),
            ctypes.byref(written),
            ctypes.byref(overlapped),
        ):
            error = ctypes.get_last_error()
            if error != ERROR_IO_PENDING:
                raise OSError(error, "WriteFile failed")
            wait = _kernel32.WaitForSingleObject(self._write_event, 1000)
            if wait != WAIT_OBJECT_0:
                _kernel32.CancelIo(self._handle)
                raise OSError(ctypes.get_last_error(), "WriteFile timed out")
            if not _kernel32.GetOverlappedResult(
                self._handle, ctypes.byref(overlapped), ctypes.byref(written), False
            ):
                raise OSError(ctypes.get_last_error(), "GetOverlappedResult failed")

    def close(self) -> None:
        for attribute in ("_read_event", "_write_event"):
            handle = getattr(self, attribute, None)
            if handle:
                _kernel32.CloseHandle(handle)
                setattr(self, attribute, None)
        if getattr(self, "_handle", None):
            _kernel32.CloseHandle(self._handle)
            self._handle = None


class HidLoop:
    """Reconnecting reader. Device access is injected so tests can fake it.

    ``provider`` returns an object with ``read(timeout_ms)``, ``write(bytes)``,
    ``close()`` and an ``interface`` attribute, or raises ``OSError``.
    """

    def __init__(
        self,
        provider: object,
        on_report: object,
        on_status: object | None = None,
        retry_seconds: float = 1.0,
        read_timeout_ms: int = 200,
    ):
        self._provider = provider
        self._on_report = on_report
        self._on_status = on_status or (lambda state, detail=None: None)
        self._retry_seconds = retry_seconds
        self._read_timeout_ms = read_timeout_ms
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.device = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="rebind-hid", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
        self._drop_device()

    def poll(self) -> None:
        """One connect / read step. Exposed for deterministic tests."""
        if self.device is None:
            try:
                self.device = self._provider()  # type: ignore[operator]
            except OSError as error:
                state = (
                    "busy"
                    if getattr(error, "winerror", None) in (ERROR_ACCESS_DENIED, ERROR_SHARING_VIOLATION)
                    else "disconnected"
                )
                self._on_status(state, error)
                return
            except Exception as error:  # noqa: BLE001
                self._on_status("disconnected", error)
                return
            self._on_status("connected", self.device.interface)
        try:
            report = self.device.read(self._read_timeout_ms)
        except OSError as error:
            self._on_status("disconnected", error)
            self._drop_device()
            return
        if report:
            self._on_report(report, self.device)

    def _run(self) -> None:
        while not self._stop.is_set():
            before = self.device
            self.poll()
            if self.device is None:
                self._stop.wait(self._retry_seconds)
            elif self.device is before is not None:
                continue

    def write(self, data: bytes) -> None:
        device = self.device
        if device is None:
            raise RebindError("DEVICE_NOT_CONNECTED", "no DualSense connected")
        try:
            device.write(data)
        except OSError as error:
            self._drop_device()
            raise RebindError("DEVICE_IO_ERROR", str(error)) from error

    def _drop_device(self) -> None:
        device, self.device = self.device, None
        if device is not None:
            try:
                device.close()
            except Exception:  # noqa: BLE001
                pass


def open_first_device() -> WindowsHidDevice:
    """Provider for :class:`HidLoop`; re-enumerates on every call."""
    interface = find_dualsense()
    if interface is None:
        raise FileNotFoundError(2, "no DualSense over USB")
    return WindowsHidDevice(interface)


__all__ = [
    "DUALSENSE_PRODUCT_IDS",
    "DUALSENSE_VENDOR_ID",
    "HidInterface",
    "HidLoop",
    "WindowsHidDevice",
    "close_device",
    "enumerate_interfaces",
    "find_dualsense",
    "open_device",
    "open_first_device",
    "read_report",
]
