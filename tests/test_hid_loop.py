"""Tests for the reconnecting HID loop using fake devices."""

import unittest
from dataclasses import dataclass

from rebind_me.errors import RebindError
from rebind_me.hid import HidLoop


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
