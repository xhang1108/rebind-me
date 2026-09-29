"""Generic HTTP client for the ``webhook`` action.

A button can fire an arbitrary HTTP request: one on press (down) and, when
configured, another on release (up). This is the general primitive behind
push-to-talk and other local-API integrations -- TypeWhisper, OBS, VLC, Home
Assistant and similar tools are just configurations of it, never hardcoded.

A 411 ("Length Required") means the request carried no ``Content-Length``; an
empty body is still sent so the header is present. HTTP errors (e.g. a 409)
are treated as no-ops, while a connection failure propagates so the caller can
log it.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

_ALLOWED_METHODS = frozenset({"GET", "POST", "PUT", "DELETE", "PATCH"})


def normalize_method(method: str | None) -> str:
    """Return an upper-cased allowed method, defaulting to ``POST``."""
    candidate = (method or "POST").upper()
    return candidate if candidate in _ALLOWED_METHODS else "POST"


class WebhookClient:
    """Sends one HTTP request at a time. Injectable for tests."""

    def request(
        self,
        url: str,
        method: str | None = None,
        body: str | None = None,
        timeout: float = 2.0,
    ) -> dict | None:
        """Perform the request. Returns parsed JSON, ``{}`` on empty, or ``None``
        on an HTTP error. Raises on a connection failure."""
        data = body.encode("utf-8") if body else b""
        request = urllib.request.Request(
            url,
            data=data,
            method=normalize_method(method),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = response.read()
                return json.loads(payload) if payload else {}
        except urllib.error.HTTPError:
            # 409 when stopping while idle, etc.: treat as a no-op.
            return None
        except urllib.error.URLError as error:
            # Server not running or unreachable: let the caller log it.
            raise
