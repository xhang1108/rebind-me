"""Tests for the Toolhelp conflicting-process enumeration (stdlib only)."""

import ctypes
import inspect
import threading
import time
import unittest
from ctypes import wintypes
from unittest import mock

from rebind_me.winapi import occupant


class ProcessEntryLayoutTest(unittest.TestCase):
    def test_exe_name_is_wide(self) -> None:
        fields = dict(occupant.PROCESSENTRY32W._fields_)
        self.assertEqual(fields["szExeFile"], wintypes.WCHAR * occupant.MAX_PATH)

    def test_struct_size_matches_wchar_layout(self) -> None:
        expected = 568 if ctypes.sizeof(ctypes.c_void_p) == 8 else 556
        self.assertEqual(ctypes.sizeof(occupant.PROCESSENTRY32W), expected)

    def test_toolhelp_prototypes_are_set(self) -> None:
        kernel32 = occupant._kernel32
        self.assertIsNotNone(kernel32.CreateToolhelp32Snapshot.argtypes)
        self.assertIsNotNone(kernel32.CreateToolhelp32Snapshot.restype)
        self.assertIsNotNone(kernel32.Process32FirstW.argtypes)
        self.assertIsNotNone(kernel32.Process32NextW.argtypes)

    def test_no_undeclared_psutil_dependency(self) -> None:
        self.assertNotIn("psutil", inspect.getsource(occupant.list_conflicting_processes))


class ListConflictingProcessesTest(unittest.TestCase):
    def test_returns_shaped_list(self) -> None:
        conflicts = occupant.list_conflicting_processes()
        self.assertIsInstance(conflicts, list)
        for item in conflicts:
            self.assertIn(item["name"], occupant.CONFLICTING_PROCESS_NAMES)
            self.assertIsInstance(item["pid"], int)
            self.assertIsInstance(item["path"], str)

    def test_snapshot_enumerates_processes(self) -> None:
        snapshot = occupant._kernel32.CreateToolhelp32Snapshot(
            occupant.TH32CS_SNAPPROCESS, 0
        )
        self.assertTrue(snapshot)
        self.assertNotEqual(snapshot, occupant.INVALID_HANDLE_VALUE)
        try:
            entry = occupant.PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(occupant.PROCESSENTRY32W)
            self.assertTrue(
                occupant._kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
            )
            count = 0
            while count < 5000:
                count += 1
                self.assertIsInstance(str(entry.szExeFile or ""), str)
                if not occupant._kernel32.Process32NextW(
                    snapshot, ctypes.byref(entry)
                ):
                    break
            self.assertGreater(count, 0)
        finally:
            occupant._kernel32.CloseHandle(snapshot)


class FindOccupantTest(unittest.TestCase):
    def test_blank_path_returns_none_without_scanning(self) -> None:
        self.assertIsNone(occupant.find_device_occupant(""))
        self.assertIsNone(occupant.find_device_occupant("   "))

    def test_scan_body_spawns_no_per_handle_threads(self) -> None:
        # The scan body must stay single-threaded (no per-handle workers to
        # pile up); the deadline wrapper in find_device_occupant owns the one
        # worker thread it can abandon when a kernel call wedges.
        source = inspect.getsource(occupant._scan_handles)
        self.assertNotIn("Thread(", source)

    def test_wedged_scan_returns_at_deadline(self) -> None:
        # GetFinalPathNameByHandleW can block forever on some handles; the
        # caller must get None at the deadline, not hang with the worker.
        stuck = threading.Event()
        with mock.patch.object(
            occupant, "_scan_handles", side_effect=lambda *a: stuck.wait()
        ):
            started = time.monotonic()
            with self.assertLogs("rebind_me.winapi.occupant", level="WARNING"):
                self.assertIsNone(
                    occupant.find_device_occupant(
                        r"\\?\hid#vid_054c&pid_0ce6#nonexistent", deadline_seconds=0.2
                    )
                )
            self.assertLess(time.monotonic() - started, 30.0)

    def test_zero_deadline_returns_none_immediately(self) -> None:
        started = time.monotonic()
        self.assertIsNone(
            occupant.find_device_occupant(
                r"\\?\hid#vid_054c&pid_0ce6#nonexistent", deadline_seconds=0
            )
        )
        self.assertLess(time.monotonic() - started, 30.0)

    def test_deadline_expiry_is_logged(self) -> None:
        with self.assertLogs("rebind_me.winapi.occupant", level="WARNING"):
            self.assertIsNone(
                occupant.find_device_occupant(
                    r"\\?\hid#vid_054c&pid_0ce6#nonexistent", deadline_seconds=0
                )
            )

    def test_inspect_helper_rejects_a_bad_handle(self) -> None:
        self.assertIsNone(
            occupant._inspect_handle_once(
                occupant._kernel32.GetCurrentProcess(),
                123456789,
                0xFFFFFFFF,
                "hid#vid_054c",
            )
        )

    def test_scan_iterates_entries(self) -> None:
        # The 1MB first query always mismatches on a real handle table; the
        # realloc branch must be taken (NTSTATUS is signed, compare unsigned).
        with mock.patch.object(
            occupant._kernel32, "OpenProcess", return_value=1234
        ) as openproc:
            self.assertIsNone(
                occupant.find_device_occupant(
                    r"\\?\hid#vid_054c&pid_0ce6#nonexistent", deadline_seconds=60
                )
            )
            self.assertGreater(openproc.call_count, 0)

    def test_full_scan_of_a_bogus_path_finds_nothing(self) -> None:
        self.assertIsNone(
            occupant.find_device_occupant(r"\\?\hid#vid_054c&pid_0ce6#nonexistent")
        )


if __name__ == "__main__":
    unittest.main()