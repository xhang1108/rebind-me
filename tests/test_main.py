"""Tests for the top-level argument dispatcher."""

import unittest
from unittest import mock

from rebind_me.__main__ import main


class DispatchTest(unittest.TestCase):
    def test_plugin_subcommand(self) -> None:
        with mock.patch("rebind_me.opencode_plugin.main", return_value=7) as sub:
            self.assertEqual(main(["plugin", "status"]), 7)
        sub.assert_called_once_with(["status"])

    def test_tray_subcommand(self) -> None:
        with mock.patch("rebind_me.tray.main", return_value=3) as sub:
            self.assertEqual(main(["tray"]), 3)
        sub.assert_called_once_with([])

    def test_autostart_subcommand(self) -> None:
        with mock.patch("rebind_me.autostart.main", return_value=0) as sub:
            self.assertEqual(main(["autostart", "enable"]), 0)
        sub.assert_called_once_with(["enable"])

    def test_default_runs_the_bridge(self) -> None:
        with mock.patch("rebind_me.bridge.Bridge") as bridge:
            bridge.return_value.run.return_value = 0
            self.assertEqual(main([]), 0)
        bridge.return_value.run.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
