"""Tests for the local HTTP API (fake backend, no socket)."""

import json
import socket
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from rebind_me.api import (
    DEFAULT_PORT,
    TOKEN_HEADER,
    ApiApp,
    ApiServer,
    Request,
    envelope_error,
)
from rebind_me.errors import RebindError

HOST = {"Host": f"127.0.0.1:{DEFAULT_PORT}"}
ORIGIN = {"Host": f"127.0.0.1:{DEFAULT_PORT}", "Origin": f"http://127.0.0.1:{DEFAULT_PORT}"}
TOKEN = "s3cret"


class FakeBackend:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.raise_on_put: RebindError | None = None

    def _put(self, name: str, document: dict, base_version: int) -> dict:
        if self.raise_on_put is not None:
            raise self.raise_on_put
        self.calls.append((name, document, base_version))
        return {"updated": name, "baseVersion": base_version + 1}

    def status(self) -> dict:
        return {"running": True}

    def ui_active(self, body: dict) -> dict:
        self.calls.append(("ui-active", body))
        return {"active": bool(body.get("active", True))}

    def get_mapping(self) -> dict:
        return {"enabled": True, "baseVersion": 1}

    def put_mapping(self, document: dict, base_version: int) -> dict:
        return self._put("mapping", document, base_version)

    def get_presets(self) -> dict:
        return {"presets": {"openchamber": {"mappings": {}}}, "baseVersion": 1}

    def put_preset(self, body: dict) -> dict:
        self.calls.append(("preset", body))
        return {"action": body.get("action"), "presets": {"presets": {}}}

    def get_mic(self) -> dict:
        return {"muted": False, "autoMuteSeconds": 60}

    def put_mic(self, body: dict) -> dict:
        self.calls.append(("mic", body))
        return {"muted": not body.get("muted", False)}

    def get_settings(self) -> dict:
        return {"ui": {"language": "zh-Hant"}, "baseVersion": 1}

    def put_settings(self, document: dict, base_version: int) -> dict:
        return self._put("settings", document, base_version)

    def autostart(self, body: dict) -> dict:
        self.calls.append(("autostart", body))
        return {"ok": True}

    def plugin(self, body: dict) -> dict:
        self.calls.append(("plugin", body))
        return {"installed": False, "action": body.get("action")}

    def key_capture(self) -> dict:
        return {"captured": "KeyK"}

    def cancel_key_capture(self) -> dict:
        return {"cancelled": True}

    def focus_terminal(self, body: dict) -> dict:
        return {"focused": True}

    def scan_windows(self) -> list:
        return []

    def sessions(self, body: dict) -> dict:
        self.calls.append(("sessions", body))
        return {"accepted": True}

    def shutdown(self) -> dict:
        return {"stopping": True}


def app_with(backend: FakeBackend, ui_dir: Path | None = None) -> ApiApp:
    return ApiApp(backend, TOKEN, DEFAULT_PORT, ui_dir)


def body_of(response) -> dict:
    return json.loads(response.body.decode("utf-8"))


class AuthTest(unittest.TestCase):
    def setUp(self) -> None:
        self.backend = FakeBackend()
        self.app = app_with(self.backend)

    def test_ui_bad_host(self) -> None:
        response = self.app.handle(Request("GET", "/api/status", {"Host": "evil.test"}))
        self.assertEqual(response.status, 403)
        self.assertEqual(body_of(response)["error"]["code"], "ORIGIN_NOT_ALLOWED")

    def test_ui_bad_origin(self) -> None:
        headers = {"Host": f"127.0.0.1:{DEFAULT_PORT}", "Origin": "http://evil.test"}
        response = self.app.handle(Request("GET", "/api/status", headers))
        self.assertEqual(response.status, 403)

    def test_ui_good(self) -> None:
        response = self.app.handle(Request("GET", "/api/status", ORIGIN))
        self.assertEqual(response.status, 200)
        self.assertTrue(body_of(response)["ok"])

    def test_token_missing(self) -> None:
        response = self.app.handle(Request("POST", "/api/shutdown", HOST))
        self.assertEqual(response.status, 401)
        self.assertEqual(body_of(response)["error"]["code"], "MISSING_TOKEN")

    def test_token_wrong(self) -> None:
        headers = dict(HOST, **{TOKEN_HEADER: "nope"})
        response = self.app.handle(Request("POST", "/api/shutdown", headers))
        self.assertEqual(response.status, 401)
        self.assertEqual(body_of(response)["error"]["code"], "INVALID_TOKEN")

    def test_token_good(self) -> None:
        headers = dict(HOST, **{TOKEN_HEADER: TOKEN})
        response = self.app.handle(Request("POST", "/api/shutdown", headers))
        self.assertEqual(response.status, 200)
        self.assertTrue(body_of(response)["data"]["stopping"])


class RoutingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.backend = FakeBackend()
        self.app = app_with(self.backend)

    def test_unknown_path(self) -> None:
        self.assertEqual(self.app.handle(Request("GET", "/api/nope", ORIGIN)).status, 404)

    def test_removed_codex_endpoint(self) -> None:
        self.assertEqual(
            self.app.handle(Request("POST", "/api/codex-hook", ORIGIN)).status, 404
        )

    def test_method_not_allowed(self) -> None:
        self.assertEqual(
            self.app.handle(Request("DELETE", "/api/status", ORIGIN)).status, 405
        )

    def test_ui_active_reports_state(self) -> None:
        payload = json.dumps({"active": False}).encode()
        response = self.app.handle(Request("POST", "/api/ui-active", ORIGIN, payload))
        self.assertEqual(response.status, 200)
        self.assertEqual(body_of(response)["data"]["active"], False)
        self.assertEqual(self.backend.calls[0], ("ui-active", {"active": False}))

    def test_key_capture_cancel(self) -> None:
        response = self.app.handle(Request("POST", "/api/key-capture/cancel", ORIGIN))
        self.assertEqual(response.status, 200)
        self.assertEqual(body_of(response)["data"], {"cancelled": True})

    def test_get_mapping(self) -> None:
        response = self.app.handle(Request("GET", "/api/mapping", ORIGIN))
        self.assertEqual(body_of(response)["data"]["enabled"], True)

    def test_get_mic(self) -> None:
        response = self.app.handle(Request("GET", "/api/mic", ORIGIN))
        self.assertEqual(response.status, 200)
        self.assertEqual(body_of(response)["data"], {"muted": False, "autoMuteSeconds": 60})

    def test_post_mic_toggles(self) -> None:
        response = self.app.handle(Request("POST", "/api/mic", ORIGIN))
        self.assertEqual(response.status, 200)
        self.assertEqual(body_of(response)["data"], {"muted": True})
        self.assertEqual(self.backend.calls[0], ("mic", {}))

    def test_get_settings(self) -> None:
        self.assertEqual(self.app.handle(Request("GET", "/api/settings", ORIGIN)).status, 200)

    def test_get_presets(self) -> None:
        response = self.app.handle(Request("GET", "/api/presets", ORIGIN))
        self.assertEqual(response.status, 200)
        self.assertIn("openchamber", body_of(response)["data"]["presets"])

    def test_post_preset(self) -> None:
        payload = json.dumps({"action": "save", "name": "openchamber"}).encode()
        response = self.app.handle(Request("POST", "/api/presets", ORIGIN, payload))
        self.assertEqual(response.status, 200)
        self.assertEqual(
            self.backend.calls[0], ("preset", {"action": "save", "name": "openchamber"})
        )

    def test_removed_section_endpoints(self) -> None:
        self.assertEqual(self.app.handle(Request("GET", "/api/lighting", ORIGIN)).status, 404)
        self.assertEqual(self.app.handle(Request("GET", "/api/triggers", ORIGIN)).status, 404)

    def test_scan_windows_and_focus_terminal(self) -> None:
        self.assertEqual(body_of(self.app.handle(Request("POST", "/api/scan-windows", ORIGIN)))["data"], [])
        focus = self.app.handle(Request("POST", "/api/focus-terminal", ORIGIN))
        self.assertEqual(body_of(focus)["data"], {"focused": True})

    def test_sessions_require_the_bridge_token(self) -> None:
        payload = json.dumps({"id": "s"}).encode()
        self.assertEqual(self.app.handle(Request("POST", "/api/sessions", ORIGIN, payload)).status, 401)
        headers = {TOKEN_HEADER: TOKEN}
        response = self.app.handle(Request("POST", "/api/sessions", headers, payload))
        self.assertEqual(body_of(response)["data"], {"accepted": True})

    def test_get_plugin_status(self) -> None:
        response = self.app.handle(Request("GET", "/api/plugin", ORIGIN))
        self.assertEqual(response.status, 200)
        self.assertEqual(self.backend.calls[0], ("plugin", {}))

    def test_post_plugin_install(self) -> None:
        payload = json.dumps({"action": "install"}).encode()
        response = self.app.handle(Request("POST", "/api/plugin", ORIGIN, payload))
        self.assertEqual(response.status, 200)
        self.assertEqual(body_of(response)["data"]["action"], "install")

    def test_put_mapping_requires_base_version(self) -> None:
        payload = json.dumps({"enabled": False}).encode()
        response = self.app.handle(Request("PUT", "/api/mapping", ORIGIN, payload))
        self.assertEqual(response.status, 400)
        self.assertEqual(body_of(response)["error"]["code"], "SCHEMA_ERROR")

    def test_put_mapping_ok(self) -> None:
        payload = json.dumps({"enabled": False, "baseVersion": 1}).encode()
        response = self.app.handle(Request("PUT", "/api/mapping", ORIGIN, payload))
        self.assertEqual(response.status, 200)
        self.assertEqual(self.backend.calls[0], ("mapping", {"enabled": False}, 1))

    def test_invalid_json(self) -> None:
        response = self.app.handle(Request("PUT", "/api/mapping", ORIGIN, b"{not json"))
        self.assertEqual(response.status, 400)

    def test_backend_error_envelope(self) -> None:
        self.backend.raise_on_put = RebindError("STALE_STORE", "stale")
        payload = json.dumps({"enabled": False, "baseVersion": 1}).encode()
        response = self.app.handle(Request("PUT", "/api/mapping", ORIGIN, payload))
        self.assertEqual(response.status, 409)
        self.assertEqual(body_of(response)["error"]["code"], "STALE_STORE")


class StaticTest(unittest.TestCase):
    def test_serves_index_and_blocks_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ui = Path(tmp)
            (ui / "index.html").write_text("<h1>hi</h1>", encoding="utf-8")
            app = app_with(FakeBackend(), ui)
            root = app.handle(Request("GET", "/", ORIGIN))
            self.assertEqual(root.status, 200)
            self.assertIn(b"hi", root.body)
            self.assertIn("text/html", root.content_type)

            outside = (ui.parent / "secret.txt").write_text("no", encoding="utf-8")
            traversal = app.handle(Request("GET", "/../secret.txt", ORIGIN))
            self.assertEqual(traversal.status, 404)

    def test_content_types(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ui = Path(tmp)
            (ui / "app.js").write_text("export const x = 1;", encoding="utf-8")
            (ui / "styles.css").write_text("body{}", encoding="utf-8")
            app = app_with(FakeBackend(), ui)
            js = app.handle(Request("GET", "/app.js", ORIGIN))
            self.assertIn("javascript", js.content_type)
            css = app.handle(Request("GET", "/styles.css", ORIGIN))
            self.assertIn("text/css", css.content_type)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class ApiServerTest(unittest.TestCase):
    """Drives the real socket handler on an ephemeral port."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        ui = Path(self._tmp.name)
        (ui / "index.html").write_text("<h1>hi</h1>", encoding="utf-8")
        (ui / "note.txt").write_text("plain", encoding="utf-8")
        (ui / "blob.bin").write_bytes(b"\x00\x01")

        self.backend = FakeBackend()
        self.port = free_port()
        app = ApiApp(self.backend, TOKEN, self.port, ui)
        self.server = ApiServer(app, "127.0.0.1", self.port)
        self.server.bind()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.thread.join(2.0)
        self.server.server_close()
        self._tmp.cleanup()

    def fetch(self, path: str, method: str = "GET", token: bool = False) -> tuple[int, bytes, str]:
        headers = {TOKEN_HEADER: TOKEN} if token else {}
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}", method=method, headers=headers
        )
        for _ in range(100):
            try:
                with urllib.request.urlopen(request, timeout=2) as response:
                    return response.status, response.read(), response.headers["Content-Type"]
            except urllib.error.HTTPError as error:
                return error.code, error.read(), error.headers["Content-Type"]
            except urllib.error.URLError:
                time.sleep(0.02)
        self.fail("server did not start listening")

    def test_api_get_over_the_socket(self) -> None:
        status, body, content_type = self.fetch("/api/status")
        self.assertEqual(status, 200)
        self.assertIn("application/json", content_type)
        self.assertTrue(json.loads(body)["ok"])

    def test_token_is_enforced_over_the_socket(self) -> None:
        self.assertEqual(self.fetch("/api/shutdown", "POST")[0], 401)
        self.assertEqual(self.fetch("/api/shutdown", "POST", token=True)[0], 200)

    def test_method_and_path_errors_over_the_socket(self) -> None:
        self.assertEqual(self.fetch("/api/status", "DELETE")[0], 405)
        self.assertEqual(self.fetch("/api/nope")[0], 404)

    def test_static_is_served_with_content_types(self) -> None:
        status, body, content_type = self.fetch("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", content_type)
        self.assertIn(b"hi", body)
        self.assertIn("charset=utf-8", self.fetch("/note.txt")[2])
        self.assertEqual(self.fetch("/blob.bin")[2], "application/octet-stream")
        self.assertEqual(self.fetch("/missing.txt")[0], 404)


if __name__ == "__main__":
    unittest.main()
