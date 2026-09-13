"""Tests for the local HTTP API (fake backend, no socket)."""

import json
import tempfile
import unittest
from pathlib import Path

from rebind_me.api import (
    DEFAULT_PORT,
    TOKEN_HEADER,
    ApiApp,
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

    def get_mapping(self) -> dict:
        return {"enabled": True, "baseVersion": 1}

    def put_mapping(self, document: dict, base_version: int) -> dict:
        return self._put("mapping", document, base_version)

    def get_lighting(self) -> dict:
        return {"mode": "status", "baseVersion": 1}

    def put_lighting(self, document: dict, base_version: int) -> dict:
        return self._put("lighting", document, base_version)

    def get_triggers(self) -> dict:
        return {"left": {"mode": "off"}, "baseVersion": 1}

    def put_triggers(self, document: dict, base_version: int) -> dict:
        return self._put("triggers", document, base_version)

    def get_settings(self) -> dict:
        return {"ui": {"language": "zh-Hant"}, "baseVersion": 1}

    def put_settings(self, document: dict, base_version: int) -> dict:
        return self._put("settings", document, base_version)

    def autostart(self, body: dict) -> dict:
        self.calls.append(("autostart", body))
        return {"ok": True}

    def key_capture(self) -> dict:
        return {"captured": "KeyK"}

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

    def test_get_mapping(self) -> None:
        response = self.app.handle(Request("GET", "/api/mapping", ORIGIN))
        self.assertEqual(body_of(response)["data"]["enabled"], True)

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


if __name__ == "__main__":
    unittest.main()
