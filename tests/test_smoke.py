"""Smoke tests for the package skeleton."""

import unittest

import rebind_me
from rebind_me import protocol


class SmokeTest(unittest.TestCase):
    def test_version_is_semver(self) -> None:
        self.assertRegex(rebind_me.__version__, r"^\d+\.\d+\.\d+$")

    def test_report_ids(self) -> None:
        self.assertEqual(protocol.INPUT_REPORT_ID, 0x01)
        self.assertEqual(protocol.OUTPUT_REPORT_ID, 0x02)
        self.assertEqual(protocol.OUTPUT_REPORT_LENGTH, 48)


if __name__ == "__main__":
    unittest.main()
