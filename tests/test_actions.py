"""Tests for action selection and dispatch."""

import unittest

from rebind_me.actions import ActionRunner, choose_terminal
from rebind_me.errors import RebindError


class FakeWindows:
    def __init__(self, windows, names=None):
        self._windows = windows
        self._names = names or {}
        self.focused: list[int] = []

    def list_windows(self):
        return list(self._windows)

    def process_name(self, pid):
        return self._names.get(pid, "")

    def focus_window(self, hwnd):
        self.focused.append(hwnd)
        return True


def window(hwnd, pid, title="t", z=0):
    return {"hwnd": hwnd, "pid": pid, "title": title, "zOrder": z}


class ChooseTerminalTest(unittest.TestCase):
    def test_no_candidates(self) -> None:
        self.assertIsNone(choose_terminal([], []))

    def test_no_sessions_uses_topmost(self) -> None:
        candidates = [window(1, 100, z=0), window(2, 200, z=1)]
        self.assertEqual(choose_terminal(candidates, []), 1)

    def test_completed_beats_working(self) -> None:
        candidates = [window(1, 100, z=0), window(2, 200, z=1)]
        sessions = [
            {"pid": 200, "status": "working", "lastActive": 10},
            {"pid": 100, "status": "completed", "lastActive": 1},
        ]
        self.assertEqual(choose_terminal(candidates, sessions), 1)

    def test_working_beats_most_recent(self) -> None:
        candidates = [window(1, 100, z=0), window(2, 200, z=1)]
        sessions = [
            {"pid": 200, "status": "idle", "lastActive": 99},
            {"pid": 100, "status": "working", "lastActive": 1},
        ]
        self.assertEqual(choose_terminal(candidates, sessions), 1)

    def test_recent_activity_when_same_status(self) -> None:
        candidates = [window(1, 100, z=0), window(2, 200, z=1)]
        sessions = [
            {"pid": 100, "status": "working", "lastActive": 1},
            {"pid": 200, "status": "working", "lastActive": 5},
        ]
        self.assertEqual(choose_terminal(candidates, sessions), 2)

    def test_all_sessions_same_window_falls_back_to_zorder(self) -> None:
        candidates = [window(1, 100, z=0), window(2, 200, z=1)]
        sessions = [
            {"pid": 100, "status": "working", "lastActive": 1},
            {"pid": 100, "status": "working", "lastActive": 5},
        ]
        self.assertEqual(choose_terminal(candidates, sessions), 1)

    def test_unknown_pids_fall_back(self) -> None:
        candidates = [window(1, 100, z=0)]
        sessions = [{"pid": 999, "status": "working", "lastActive": 1}]
        self.assertEqual(choose_terminal(candidates, sessions), 1)


class ActionRunnerTest(unittest.TestCase):
    def test_focus_terminal(self) -> None:
        windows = FakeWindows([window(7, 100)])
        runner = ActionRunner(windows, sessions_provider=lambda: [])
        result = runner.run("triangle", "focus-terminal", {})
        self.assertEqual(result, {"focused": True, "hwnd": 7})
        self.assertEqual(windows.focused, [7])

    def test_switch_to_app(self) -> None:
        windows = FakeWindows(
            [window(1, 100), window(2, 200)], names={100: "explorer.exe", 200: "OpenChamber.exe"}
        )
        runner = ActionRunner(windows)
        result = runner.run("triangle", "switch-to-app", {"process": "OpenChamber"})
        self.assertEqual(result["hwnd"], 2)
        self.assertEqual(windows.focused, [2])

    def test_switch_to_app_not_running(self) -> None:
        windows = FakeWindows([window(1, 100)], names={100: "explorer.exe"})
        runner = ActionRunner(windows)
        result = runner.run("triangle", "switch-to-app", {"process": "Nope"})
        self.assertFalse(result["focused"])

    def test_toggle_mouse_mode(self) -> None:
        calls: list[str] = []
        runner = ActionRunner(FakeWindows([]), toggle_mouse_mode=lambda: calls.append("t"))
        runner.run("l1", "toggle-mouse-mode", {})
        self.assertEqual(calls, ["t"])

    def test_open_config_ui(self) -> None:
        calls: list[str] = []
        runner = ActionRunner(FakeWindows([]), open_ui=lambda: calls.append("o"))
        runner.run("l1", "open-config-ui", {})
        self.assertEqual(calls, ["o"])

    def test_unknown_action(self) -> None:
        runner = ActionRunner(FakeWindows([]))
        with self.assertRaises(RebindError):
            runner.run("l1", "explode", {})


if __name__ == "__main__":
    unittest.main()
