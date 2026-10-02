"""Tests for the reconnecting HID loop using fake devices."""

import time
import unittest
from dataclasses import dataclass
from unittest import mock

from rebind_me import hid as hid_mod
from rebind_me.errors import RebindError
from rebind_me.hid import HidLoop, _diagnose_occupant_async, open_first_device


@dataclass
class FakeInterface:
    path: str = "fake"
    vendor_id: int = 0x054C
    product_id: int = 0x0CE6
    input_report_length: int = 64
    output_report_length: int = 48


class FakeDevice:
    def __init__(self, reports=None, fail_write=False):
        self.interface = FakeInterface()
        self._reports = list(reports or [])
        self.fail_read = False
        self.fail_write = fail_write
        self.closed = False
        self.writes: list[bytes] = []

    def read(self, timeout_ms: int):
        if self._reports:
            return self._reports.pop(0)
        if self.fail_read:
            raise OSError(1, "device gone")
        return None

    def write(self, data: bytes) -> None:
        if self.fail_write:
            raise OSError(1, "write failed")
        self.writes.append(bytes(data))

    def close(self) -> None:
        self.closed = True


def busy_error() -> OSError:
    error = OSError("busy")
    error.winerror = 5  # type: ignore[attr-defined]
    return error


class PollTest(unittest.TestCase):
    def setUp(self) -> None:
        self.reports: list = []
        self.statuses: list = []

    def make_loop(self, devices):
        queue = list(devices)

        def provider():
            item = queue.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        return HidLoop(
            provider,
            on_report=lambda report, device: self.reports.append(report),
            on_status=lambda state, detail=None: self.statuses.append(state),
        )

    def test_connect_read_and_disconnect(self) -> None:
        device = FakeDevice([b"r1", b"r2"])
        loop = self.make_loop([device])
        loop.poll()  # connect + first report
        loop.poll()
        self.assertEqual(self.reports, [b"r1", b"r2"])
        device.fail_read = True
        loop.poll()
        self.assertEqual(self.statuses, ["connected", "disconnected"])
        self.assertTrue(device.closed)
        self.assertIsNone(loop.device)

    def test_busy_provider(self) -> None:
        loop = self.make_loop([busy_error()])
        loop.poll()
        self.assertEqual(self.statuses, ["busy"])

    def test_missing_provider(self) -> None:
        loop = self.make_loop([FileNotFoundError(2, "none")])
        loop.poll()
        self.assertEqual(self.statuses, ["disconnected"])

    def test_reconnect_after_disconnect(self) -> None:
        first = FakeDevice()
        second = FakeDevice([b"r3"])
        loop = self.make_loop([first, second])
        loop.poll()  # connect first
        first.fail_read = True
        loop.poll()  # disconnect
        loop.poll()  # connect second + read r3
        self.assertEqual(self.reports, [b"r3"])
        self.assertEqual(self.statuses, ["connected", "disconnected", "connected"])


class RunGuardTest(unittest.TestCase):
    def test_run_survives_a_failing_report(self) -> None:
        device = FakeDevice([b"bad", b"good"])
        calls: list = []

        def on_report(report, dev):
            calls.append(report)
            if report == b"bad":
                raise RuntimeError("boom")

        loop = HidLoop(
            lambda: device,
            on_report=on_report,
            on_status=lambda state, detail=None: None,
            retry_seconds=0.01,
        )
        with self.assertLogs("rebind_me.hid", level="ERROR"):
            loop.start()
            deadline = time.monotonic() + 5.0
            while b"good" not in calls and time.monotonic() < deadline:
                time.sleep(0.005)
            self.assertIn(b"good", calls)
            self.assertTrue(loop._thread.is_alive())
            loop.stop()

    def test_run_survives_a_failing_status_callback(self) -> None:
        device = FakeDevice([b"r1"])

        def on_status(state, detail=None):
            raise RuntimeError("status boom")

        loop = HidLoop(
            lambda: device,
            on_report=lambda report, dev: None,
            on_status=on_status,
            retry_seconds=0.01,
        )
        loop.start()
        time.sleep(0.2)
        try:
            self.assertTrue(loop._thread.is_alive())
        finally:
            loop.stop()


class OccupantAsyncTest(unittest.TestCase):
    def setUp(self) -> None:
        hid_mod._occupant_cache.clear()
        hid_mod._occupant_inflight.clear()
        self._cache_seconds = hid_mod.OCCUPANT_CACHE_SECONDS

    def tearDown(self) -> None:
        hid_mod.OCCUPANT_CACHE_SECONDS = self._cache_seconds
        hid_mod._occupant_cache.clear()
        hid_mod._occupant_inflight.clear()

    def _wait_for_cache(self, path: str, timeout: float = 5.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with hid_mod._occupant_lock:
                if path in hid_mod._occupant_cache:
                    return
            time.sleep(0.005)
        self.fail("occupant background scan did not finish")

    def test_first_call_returns_none_and_fills_cache(self) -> None:
        calls: list = []
        result = {"pid": 7, "name": "steam.exe", "path": "C:\\s"}
        with mock.patch.object(
            hid_mod, "find_device_occupant", side_effect=lambda p: calls.append(p) or result
        ):
            self.assertIsNone(_diagnose_occupant_async("fake-path"))
            self._wait_for_cache("fake-path")
            self.assertEqual(_diagnose_occupant_async("fake-path"), result)
            self.assertEqual(len(calls), 1)

    def test_stale_cache_triggers_a_rescan(self) -> None:
        hid_mod.OCCUPANT_CACHE_SECONDS = 0
        with mock.patch.object(
            hid_mod, "find_device_occupant", return_value=None
        ) as scan:
            _diagnose_occupant_async("fake-path")
            self._wait_for_cache("fake-path")
            _diagnose_occupant_async("fake-path")
            deadline = time.monotonic() + 5.0
            while scan.call_count < 2 and time.monotonic() < deadline:
                time.sleep(0.005)
            self.assertEqual(scan.call_count, 2)

    def test_failed_scan_caches_none_and_releases_inflight(self) -> None:
        with mock.patch.object(
            hid_mod, "find_device_occupant", side_effect=OSError("wedged")
        ) as scan:
            self.assertIsNone(_diagnose_occupant_async("fake-path"))
            self._wait_for_cache("fake-path")
            with hid_mod._occupant_lock:
                self.assertNotIn("fake-path", hid_mod._occupant_inflight)
            # A fresh negative result is served from cache: no rescan.
            self.assertIsNone(_diagnose_occupant_async("fake-path"))
            self.assertEqual(scan.call_count, 1)
            # Once stale, the next poll retries the scan.
            hid_mod.OCCUPANT_CACHE_SECONDS = 0
            self.assertIsNone(_diagnose_occupant_async("fake-path"))
            deadline = time.monotonic() + 5.0
            while scan.call_count < 2 and time.monotonic() < deadline:
                time.sleep(0.005)
            self.assertEqual(scan.call_count, 2)

    def test_busy_open_attaches_occupant_without_blocking(self) -> None:
        class BusyDevice:
            def __init__(self, interface):
                raise busy_error()

        with (
            mock.patch.object(hid_mod, "find_dualsense", return_value=FakeInterface()),
            mock.patch.object(hid_mod, "WindowsHidDevice", BusyDevice),
            mock.patch.object(
                hid_mod, "_diagnose_occupant_async", return_value={"pid": 9}
            ) as diagnose,
        ):
            try:
                open_first_device()
                self.fail("expected OSError")
            except OSError as error:
                self.assertEqual(error.occupant, {"pid": 9})
                self.assertIsInstance(error.conflicts, list)
        self.assertEqual(diagnose.call_count, 1)


class WriteTest(unittest.TestCase):
    def test_write_without_device(self) -> None:
        loop = HidLoop(lambda: FakeDevice(), on_report=lambda *a: None)
        with self.assertRaises(RebindError) as ctx:
            loop.write(b"x")
        self.assertEqual(ctx.exception.code, "DEVICE_NOT_CONNECTED")

    def test_write_ok_and_failure(self) -> None:
        device = FakeDevice()
        loop = HidLoop(lambda: device, on_report=lambda *a: None)
        loop.poll()
        loop.write(b"\x02\x00")
        self.assertEqual(device.writes, [b"\x02\x00"])

        failing = FakeDevice(fail_write=True)
        loop2 = HidLoop(lambda: failing, on_report=lambda *a: None)
        loop2.poll()
        with self.assertRaises(RebindError) as ctx:
            loop2.write(b"x")
        self.assertEqual(ctx.exception.code, "DEVICE_IO_ERROR")
        self.assertIsNone(loop2.device)


if __name__ == "__main__":
    unittest.main()
