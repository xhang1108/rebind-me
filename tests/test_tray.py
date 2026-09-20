"""Tests for the tray's pure logic and bridge client (no GUI)."""

import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from rebind_me.store import SETTINGS_FILENAME, TOKEN_FILENAME
from rebind_me.tray import (
    AUTOSTART_ID,
    RESTART_ID,
    START_ID,
    STOP_ID,
    BridgeClient,
    autostart_targets,
    build_menu,
    probe_state,
    read_port,
    read_token,
    restart_bridge,
    start_bridge,
    stop_bridge,
)


class RecordingHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    requests: list[dict] = []
    response: dict = {"ok": True, "error": None, "data": {"seen": True}}
    status_code = 200

    def log_message(self, *args):
        pass

    def _handle(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        type(self).requests.append(
            {
                "method": self.command,
                "path": self.path,
                "token": self.headers.get("X-Bridge-Token"),
                "body": json.loads(body) if body else None,
            }
        )
        payload = json.dumps(type(self).response).encode("utf-8")
        self.send_response(type(self).status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    do_GET = _handle
    do_POST = _handle


class BridgeClientTest(unittest.TestCase):
    def setUp(self):
        RecordingHandler.requests = []
        RecordingHandler.response = {"ok": True, "error": None, "data": {"seen": True}}
        RecordingHandler.status_code = 200
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), RecordingHandler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._close_server)
        self.client = BridgeClient(f"http://127.0.0.1:{self.port}", "tok")

    def _close_server(self):
        self.server.shutdown()
        self.server.server_close()

    def test_status(self):
        self.assertEqual(self.client.status(), {"seen": True})
        self.assertEqual(RecordingHandler.requests[0]["method"], "GET")

    def test_token_endpoints_send_header(self):
        self.client.autostart(True, False)
        request = RecordingHandler.requests[-1]
        self.assertEqual(request["path"], "/api/autostart")
        self.assertEqual(request["token"], "tok")
        self.assertEqual(request["body"], {"bridge": True, "tray": False})

    def test_error_envelope_returns_none(self):
        RecordingHandler.response = {
            "ok": False,
            "error": {"code": "UNAUTHORIZED", "message": "no"},
            "data": None,
        }
        self.assertIsNone(self.client.shutdown())

    def test_http_error_returns_none(self):
        RecordingHandler.status_code = 500
        self.assertIsNone(self.client.status())

    def test_offline_returns_none(self):
        self.assertIsNone(BridgeClient("http://127.0.0.1:1", "tok", timeout=0.2).status())


class RestartBridgeTest(unittest.TestCase):
    def test_restart_uses_graceful_stop_then_start(self):
        events = []
        state = {"online": True, "runs": 0}

        class Client:
            def shutdown(self):
                events.append("shutdown")
                state["online"] = False

            def status(self):
                return {"device": "pad"} if state["online"] else None

        class Task:
            def end(self):
                events.append("end")

            def run_now(self):
                events.append("run")
                state["online"] = True

        self.assertTrue(restart_bridge(Client(), Task(), sleep=lambda _: None))
        # Graceful shutdown worked, so the task must not be force-ended.
        self.assertEqual(events, ["shutdown", "run"])

    def test_restart_force_ends_when_shutdown_fails(self):
        events = []
        state = {"online": True}

        class Client:
            def shutdown(self):
                events.append("shutdown")  # bridge ignores it and stays online

            def status(self):
                return {"device": "pad"} if state["online"] else None

        class Task:
            def end(self):
                events.append("end")
                state["online"] = False

            def run_now(self):
                events.append("run")
                state["online"] = True

        self.assertTrue(restart_bridge(Client(), Task(), sleep=lambda _: None))
        self.assertEqual(events, ["shutdown", "end", "run"])

    def test_restart_retries_ignored_run(self):
        state = {"online": True, "runs": 0}

        class Client:
            def shutdown(self):
                state["online"] = False

            def status(self):
                return {"device": "pad"} if state["online"] else None

        class Task:
            def end(self):
                pass

            def run_now(self):
                state["runs"] += 1
                if state["runs"] >= 2:
                    state["online"] = True

        self.assertTrue(restart_bridge(Client(), Task(), sleep=lambda _: None))
        self.assertEqual(state["runs"], 2)

    def test_restart_reports_failure(self):
        state = {"online": True}

        class Client:
            def shutdown(self):
                state["online"] = False

            def status(self):
                return {"device": "pad"} if state["online"] else None

        class Task:
            def end(self):
                pass

            def run_now(self):
                pass  # ignored while the task is considered still running

        self.assertFalse(
            restart_bridge(Client(), Task(), sleep=lambda _: None, attempts=2)
        )


class StartStopTest(unittest.TestCase):
    def test_start_retries_until_online(self):
        state = {"online": False, "runs": 0}

        class Client:
            def status(self):
                return {"device": "pad"} if state["online"] else None

        class Task:
            def run_now(self):
                state["runs"] += 1
                if state["runs"] >= 2:
                    state["online"] = True

        self.assertTrue(start_bridge(Client(), Task(), sleep=lambda _: None))
        self.assertEqual(state["runs"], 2)

    def test_start_reports_failure(self):
        class Client:
            def status(self):
                return None

        class Task:
            def run_now(self):
                raise RuntimeError("task missing")

        self.assertFalse(
            start_bridge(Client(), Task(), sleep=lambda _: None, attempts=2)
        )

    def test_stop_graceful(self):
        state = {"online": True}

        class Client:
            def shutdown(self):
                state["online"] = False

            def status(self):
                return {} if state["online"] else None

        class Task:
            def end(self):
                raise AssertionError("graceful stop must not end the task")

        self.assertTrue(stop_bridge(Client(), Task(), sleep=lambda _: None))

    def test_stop_falls_back_to_end(self):
        state = {"online": True}

        class Client:
            def shutdown(self):
                pass  # ignored

            def status(self):
                return {} if state["online"] else None

        class Task:
            def end(self):
                state["online"] = False

        self.assertTrue(stop_bridge(Client(), Task(), sleep=lambda _: None))


class ProbeStateTest(unittest.TestCase):
    class Client:
        def __init__(self, status, settings=None):
            self._status = status
            self._settings = settings or {}

        def status(self):
            return self._status

        def settings(self):
            return self._settings

    class Task:
        def __init__(self, exists):
            self._exists = exists

        def exists(self):
            return self._exists

    def test_online_reports_pid_uptime_and_autostart(self):
        state = probe_state(
            self.Client(
                {"device": "pad", "pid": 42, "uptime": 3.5},
                {"autostart": {"bridge": True, "tray": True}},
            ),
            self.Task(False),
        )
        self.assertTrue(state["online"])
        self.assertTrue(state["installed"])
        self.assertEqual(state["pid"], 42)
        self.assertEqual(state["autostart"], {"bridge": True, "tray": True})

    def test_offline_reports_installed_from_task(self):
        self.assertFalse(
            probe_state(self.Client(None), self.Task(False))["installed"]
        )
        self.assertTrue(
            probe_state(self.Client(None), self.Task(True))["installed"]
        )


class AutostartTargetsTest(unittest.TestCase):
    def test_toggles_both_together(self):
        self.assertEqual(
            autostart_targets({"bridge": True, "tray": True}),
            {"bridge": False, "tray": False},
        )
        self.assertEqual(
            autostart_targets({"bridge": False, "tray": False}),
            {"bridge": True, "tray": True},
        )

    def test_partial_state_turns_both_on(self):
        self.assertEqual(
            autostart_targets({"bridge": True, "tray": False}),
            {"bridge": True, "tray": True},
        )
        self.assertEqual(
            autostart_targets({}),
            {"bridge": True, "tray": True},
        )


class MenuTest(unittest.TestCase):
    def item(self, items, item_id):
        return next(item for item in items if item.id == item_id)

    def test_not_installed_disables_start_and_says_so(self):
        items = build_menu({"online": False, "installed": False})
        self.assertEqual(items[0].label, "Status: not installed")
        self.assertFalse(self.item(items, START_ID).enabled)
        self.assertFalse(self.item(items, STOP_ID).enabled)
        self.assertFalse(self.item(items, RESTART_ID).enabled)

    def test_stopped_allows_start_only(self):
        items = build_menu({"online": False, "installed": True})
        self.assertEqual(items[0].label, "Status: stopped")
        self.assertTrue(self.item(items, START_ID).enabled)
        self.assertFalse(self.item(items, RESTART_ID).enabled)

    def test_running_allows_stop_and_restart(self):
        items = build_menu(
            {"online": True, "installed": True, "device": "pad", "uptime": 12.0}
        )
        self.assertIn("running", items[0].label)
        self.assertTrue(self.item(items, STOP_ID).enabled)
        self.assertTrue(self.item(items, RESTART_ID).enabled)

    def test_autostart_checked_only_when_both_on(self):
        both = build_menu(
            {"online": True, "installed": True, "autostart": {"bridge": True, "tray": True}}
        )
        self.assertTrue(self.item(both, AUTOSTART_ID).checked)
        partial = build_menu(
            {"online": True, "installed": True, "autostart": {"bridge": True, "tray": False}}
        )
        self.assertFalse(self.item(partial, AUTOSTART_ID).checked)


class NotifyIconTest(unittest.TestCase):
    def test_notify_before_add_is_a_noop(self):
        from rebind_me.winapi.notifyicon import NIIF_ERROR, TrayIcon

        icon = TrayIcon(tooltip="Rebind Me")
        self.assertFalse(icon.notify("Rebind Me", "started"))
        self.assertFalse(icon.notify("Rebind Me", "failed", NIIF_ERROR))


class RuntimeFileTest(unittest.TestCase):
    def test_read_token_missing_and_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertIsNone(read_token(root))
            (root / TOKEN_FILENAME).write_text("abc\n", encoding="utf-8")
            self.assertEqual(read_token(root), "abc")

    def test_read_port_default_and_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(read_port(root), 4173)
            (root / SETTINGS_FILENAME).write_text(
                json.dumps({"port": 5000}), encoding="utf-8"
            )
            self.assertEqual(read_port(root), 5000)

    def test_read_port_ignores_bad_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / SETTINGS_FILENAME).write_text("{not json", encoding="utf-8")
            self.assertEqual(read_port(root), 4173)
            (root / SETTINGS_FILENAME).write_text(
                json.dumps({"port": 999999}), encoding="utf-8"
            )
            self.assertEqual(read_port(root), 4173)


if __name__ == "__main__":
    unittest.main()
