"""Tests for action selection and dispatch."""

import unittest

from rebind_me.actions import ActionRunner, choose_terminal
from rebind_me.errors import RebindError


class FakeWindows:
    def __init__(self, windows, names=None, foreground=0):
        self._windows = windows
        self._names = names or {}
        self._foreground = foreground
        self.focused: list[int] = []

    def list_windows(self):
        return list(self._windows)

    def process_name(self, pid):
        return self._names.get(pid, "")

    def foreground_hwnd(self):
        return self._foreground

    def focus_window(self, hwnd):
        self.focused.append(hwnd)
        self._foreground = hwnd
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

    def test_switch_to_app_toggles_back(self) -> None:
        windows = FakeWindows(
            [window(1, 100), window(2, 200)],
            names={100: "explorer.exe", 200: "OpenChamber.exe"},
            foreground=1,
        )
        runner = ActionRunner(windows)
        first = runner.run("triangle", "switch-to-app", {"process": "OpenChamber"})
        self.assertEqual(first["hwnd"], 2)
        second = runner.run("triangle", "switch-to-app", {"process": "OpenChamber"})
        self.assertEqual(second["hwnd"], 1)
        self.assertEqual(windows.focused, [2, 1])

    def test_switch_to_app_target_already_foreground(self) -> None:
        windows = FakeWindows(
            [window(1, 100), window(2, 200)],
            names={100: "explorer.exe", 200: "OpenChamber.exe"},
            foreground=2,
        )
        runner = ActionRunner(windows)
        first = runner.run("triangle", "switch-to-app", {"process": "OpenChamber"})
        second = runner.run("triangle", "switch-to-app", {"process": "OpenChamber"})
        self.assertEqual((first["hwnd"], second["hwnd"]), (2, 2))

    def test_switch_to_app_forgets_gone_return_window(self) -> None:
        listed = [window(1, 100), window(2, 200)]
        windows = FakeWindows(
            listed,
            names={100: "explorer.exe", 200: "OpenChamber.exe"},
            foreground=1,
        )
        runner = ActionRunner(windows)
        runner.run("triangle", "switch-to-app", {"process": "OpenChamber"})
        listed.pop(0)
        result = runner.run("triangle", "switch-to-app", {"process": "OpenChamber"})
        self.assertFalse(result["focused"])
        self.assertEqual(result["reason"], "gone")

    def test_switch_to_app_release_edge_does_not_toggle_back(self) -> None:
        # One physical tap reaches the action handler twice: press then release.
        # switch-to-app must only act on the press, or it jumps away and back.
        windows = FakeWindows(
            [window(1, 100), window(2, 200)],
            names={100: "explorer.exe", 200: "OpenChamber.exe"},
            foreground=1,
        )
        runner = ActionRunner(windows)
        params = {"process": "OpenChamber"}
        runner.run("triangle", "switch-to-app", params, pressed=True)
        runner.run("triangle", "switch-to-app", params, pressed=False)
        self.assertEqual(windows.focused, [2])

    def test_toggle_mouse_mode(self) -> None:
        calls: list[str] = []
        runner = ActionRunner(FakeWindows([]), toggle_mouse_mode=lambda: calls.append("t"))
        runner.run("l1", "toggle-mouse-mode", {})
        self.assertEqual(calls, ["t"])

    def test_toggle_mouse_mode_release_edge_is_ignored(self) -> None:
        calls: list[str] = []
        runner = ActionRunner(FakeWindows([]), toggle_mouse_mode=lambda: calls.append("t"))
        runner.run("l1", "toggle-mouse-mode", {}, pressed=True)
        runner.run("l1", "toggle-mouse-mode", {}, pressed=False)
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


class FakeWebhook:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def request(self, url, method=None, body=None, timeout=2.0):
        self.calls.append({"url": url, "method": method or "POST", "body": body})
        return {}


class WebhookActionTest(unittest.TestCase):
    def test_press_fires_down_url_release_fires_up_url(self) -> None:
        client = FakeWebhook()
        runner = ActionRunner(FakeWindows([]), webhook=client)
        runner.run(
            "square",
            "webhook",
            {
                "url": "http://127.0.0.1:8978/v1/dictation/start",
                "upUrl": "http://127.0.0.1:8978/v1/dictation/stop",
            },
            pressed=True,
        )
        runner.run(
            "square",
            "webhook",
            {
                "url": "http://127.0.0.1:8978/v1/dictation/start",
                "upUrl": "http://127.0.0.1:8978/v1/dictation/stop",
            },
            pressed=False,
        )
        self.assertEqual(
            client.calls,
            [
                {"url": "http://127.0.0.1:8978/v1/dictation/start", "method": "POST", "body": None},
                {"url": "http://127.0.0.1:8978/v1/dictation/stop", "method": "POST", "body": None},
            ],
        )

    def test_press_only_webhook_ignores_release(self) -> None:
        client = FakeWebhook()
        runner = ActionRunner(FakeWindows([]), webhook=client)
        runner.run("square", "webhook", {"url": "http://127.0.0.1:9/x"}, pressed=True)
        runner.run("square", "webhook", {"url": "http://127.0.0.1:9/x"}, pressed=False)
        # A single call: release with no upUrl is a no-op.
        self.assertEqual(len(client.calls), 1)

    def test_method_and_body_are_forwarded(self) -> None:
        client = FakeWebhook()
        runner = ActionRunner(FakeWindows([]), webhook=client)
        runner.run(
            "square",
            "webhook",
            {"url": "http://h/x", "method": "PUT", "body": "hi", "upUrl": "http://h/y", "upMethod": "DELETE"},
            pressed=True,
        )
        self.assertEqual(client.calls[0], {"url": "http://h/x", "method": "PUT", "body": "hi"})


if __name__ == "__main__":
    unittest.main()
