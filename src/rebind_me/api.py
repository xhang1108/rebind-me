"""Local HTTP API and same-origin static file serving. See plan.md §13.

One port (default ``127.0.0.1:4173``). UI endpoints are guarded by an
Origin / Host allow-list; program endpoints require ``X-Bridge-Token``.

The request logic lives in :class:`ApiApp`, which takes an injected backend so
it can be tested without hardware or a socket. :class:`ApiServer` wraps it in a
``http.server`` handler for real use.
"""

from __future__ import annotations

import json
import mimetypes
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit

from .errors import RebindError

DEFAULT_PORT = 4173
TOKEN_HEADER = "X-Bridge-Token"

# path -> allowed methods
ROUTES: dict[str, set[str]] = {
    "/api/status": {"GET"},
    "/api/mapping": {"GET", "PUT"},
    "/api/lighting": {"GET", "PUT"},
    "/api/triggers": {"GET", "PUT"},
    "/api/settings": {"GET", "PUT"},
    "/api/autostart": {"POST"},
    "/api/key-capture": {"POST"},
    "/api/focus-terminal": {"POST"},
    "/api/scan-windows": {"POST"},
    "/api/sessions": {"POST"},
    "/api/shutdown": {"POST"},
}
TOKEN_ENDPOINTS = frozenset({"/api/autostart", "/api/sessions", "/api/shutdown"})

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}


@dataclass
class Request:
    method: str
    path: str
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes = b""


@dataclass
class Response:
    status: int
    body: bytes
    content_type: str = "application/json"


def envelope_ok(data: object) -> dict:
    return {"ok": True, "error": None, "data": data}


def envelope_error(code: str, message: str) -> dict:
    return {"ok": False, "error": {"code": code, "message": message}, "data": None}


def _json_response(status: int, document: object) -> Response:
    return Response(status, json.dumps(document, ensure_ascii=False).encode("utf-8"))


def _error(code: str, message: str = "", status: int | None = None) -> Response:
    error = RebindError(code, message or code, status)
    return _json_response(error.status, envelope_error(error.code, error.message))


class ApiApp:
    """Pure request handler. The backend supplies state and actions."""

    def __init__(self, backend: object, token: str, port: int = DEFAULT_PORT, ui_dir: Path | None = None):
        self.backend = backend
        self.token = token
        self.port = port
        self.ui_dir = ui_dir

    # -- auth -------------------------------------------------------------
    def _host_allowed(self, headers: Mapping[str, str]) -> bool:
        host = headers.get("Host") or headers.get("host")
        allowed = {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}
        return host in allowed

    def _origin_allowed(self, headers: Mapping[str, str]) -> bool:
        origin = headers.get("Origin") or headers.get("origin")
        if origin is None:
            return True
        allowed = {f"http://127.0.0.1:{self.port}", f"http://localhost:{self.port}"}
        return origin in allowed

    def _ui_authorized(self, request: Request) -> None:
        if not self._host_allowed(request.headers):
            raise RebindError("ORIGIN_NOT_ALLOWED", "host is not in the allow-list", 403)
        if not self._origin_allowed(request.headers):
            raise RebindError("ORIGIN_NOT_ALLOWED", "origin is not in the allow-list", 403)

    def _token_authorized(self, request: Request) -> None:
        supplied = request.headers.get(TOKEN_HEADER) or request.headers.get(TOKEN_HEADER.lower())
        if supplied is None:
            raise RebindError("MISSING_TOKEN", "X-Bridge-Token is required", 401)
        import secrets

        if not secrets.compare_digest(str(supplied), str(self.token)):
            raise RebindError("INVALID_TOKEN", "token does not match", 401)

    # -- dispatch ---------------------------------------------------------
    def handle(self, request: Request) -> Response:
        path = urlsplit(request.path).path
        try:
            if path.startswith("/api/"):
                return self._handle_api(request, path)
            return self._handle_static(request, path)
        except RebindError as error:
            return _json_response(error.status, envelope_error(error.code, error.message))
        except Exception:  # noqa: BLE001 - last-resort guard for the socket
            return _error("INTERNAL_ERROR", "internal error", 500)

    def _handle_api(self, request: Request, path: str) -> Response:
        methods = ROUTES.get(path)
        if methods is None:
            return _error("NOT_FOUND", "unknown path", 404)
        if request.method not in methods:
            return _error("METHOD_NOT_ALLOWED", "method not allowed", 405)

        if path in TOKEN_ENDPOINTS:
            self._token_authorized(request)
        else:
            self._ui_authorized(request)

        body = self._parse_body(request)
        backend = self.backend

        if path == "/api/status":
            return _json_response(200, envelope_ok(backend.status()))
        if path == "/api/mapping":
            if request.method == "GET":
                return _json_response(200, envelope_ok(backend.get_mapping()))
            return _json_response(200, envelope_ok(self._put(backend.put_mapping, body)))
        if path == "/api/lighting":
            if request.method == "GET":
                return _json_response(200, envelope_ok(backend.get_lighting()))
            return _json_response(200, envelope_ok(self._put(backend.put_lighting, body)))
        if path == "/api/triggers":
            if request.method == "GET":
                return _json_response(200, envelope_ok(backend.get_triggers()))
            return _json_response(200, envelope_ok(self._put(backend.put_triggers, body)))
        if path == "/api/settings":
            if request.method == "GET":
                return _json_response(200, envelope_ok(backend.get_settings()))
            return _json_response(200, envelope_ok(self._put(backend.put_settings, body)))
        if path == "/api/autostart":
            return _json_response(200, envelope_ok(backend.autostart(body)))
        if path == "/api/key-capture":
            return _json_response(200, envelope_ok(backend.key_capture()))
        if path == "/api/focus-terminal":
            return _json_response(200, envelope_ok(backend.focus_terminal(body)))
        if path == "/api/scan-windows":
            return _json_response(200, envelope_ok(backend.scan_windows()))
        if path == "/api/sessions":
            return _json_response(200, envelope_ok(backend.sessions(body)))
        if path == "/api/shutdown":
            return _json_response(200, envelope_ok(backend.shutdown()))
        return _error("NOT_FOUND", "unknown path", 404)

    def _put(self, method: object, body: dict) -> object:
        base_version = body.get("baseVersion")
        if not isinstance(base_version, int):
            raise RebindError("SCHEMA_ERROR", "baseVersion is required")
        document = {key: value for key, value in body.items() if key != "baseVersion"}
        return method(document, base_version)  # type: ignore[operator]

    def _parse_body(self, request: Request) -> dict:
        if not request.body:
            return {}
        try:
            document = json.loads(request.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as error:
            raise RebindError("SCHEMA_ERROR", "body must be valid JSON") from error
        if not isinstance(document, dict):
            raise RebindError("SCHEMA_ERROR", "body must be a JSON object")
        return document

    # -- static -----------------------------------------------------------
    def _handle_static(self, request: Request, path: str) -> Response:
        if request.method != "GET":
            return _error("METHOD_NOT_ALLOWED", "method not allowed", 405)
        if self.ui_dir is None:
            return _error("NOT_FOUND", "static UI is not configured", 404)
        self._ui_authorized(request)

        relative = "index.html" if path in ("/", "") else path.lstrip("/")
        target = (self.ui_dir / relative).resolve()
        try:
            target.relative_to(self.ui_dir.resolve())
        except ValueError:
            return _error("NOT_FOUND", "not found", 404)
        if not target.is_file():
            return _error("NOT_FOUND", "not found", 404)
        content_type = _CONTENT_TYPES.get(target.suffix.lower())
        if content_type is None:
            content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
            if content_type.startswith("text/") or content_type in (
                "application/javascript",
                "application/json",
            ):
                content_type = f"{content_type}; charset=utf-8"
        return Response(200, target.read_bytes(), content_type)


class ApiServer:
    """Owns the listening socket; delegates each request to :class:`ApiApp`."""

    def __init__(self, app: ApiApp, host: str = "127.0.0.1", port: int = DEFAULT_PORT):
        self.app = app
        self.host = host
        self.port = port
        self._httpd: ThreadingHTTPServer | None = None

    def serve_forever(self) -> None:
        app = self.app

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args: object) -> None:
                pass

            def _dispatch(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                request = Request(
                    method=self.command,
                    path=self.path,
                    headers={key: value for key, value in self.headers.items()},
                    body=body,
                )
                response = app.handle(request)
                self.send_response(response.status)
                self.send_header("Content-Type", response.content_type)
                self.send_header("Content-Length", str(len(response.body)))
                self.end_headers()
                self.wfile.write(response.body)

            do_GET = _dispatch
            do_POST = _dispatch
            do_PUT = _dispatch
            do_DELETE = _dispatch

        self._httpd = ThreadingHTTPServer((self.host, self.port), Handler)
        self._httpd.serve_forever()

    def shutdown(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()


__all__ = [
    "ApiApp",
    "ApiServer",
    "DEFAULT_PORT",
    "Request",
    "Response",
    "ROUTES",
    "TOKEN_ENDPOINTS",
    "TOKEN_HEADER",
    "envelope_error",
    "envelope_ok",
]
