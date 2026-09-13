"""Minimal CLI for the local bridge API, for testing and manual checks.

The bridge must already be running (``python -m rebind_me``). The token is read
from ``%LOCALAPPDATA%\\RebindMe\\bridge.token`` unless ``REBIND_ME_TOKEN`` is
set; the base URL defaults to ``http://127.0.0.1:4173`` and can be overridden
with ``REBIND_ME_URL``.

Examples:
    python tools/bridge_api.py status
    python tools/bridge_api.py session working --id a
    python tools/bridge_api.py session idle --id a
    python tools/bridge_api.py session approval --id a
    python tools/bridge_api.py session error --id a
    python tools/bridge_api.py shutdown
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib import request
from urllib.error import HTTPError, URLError

BASE_URL = os.environ.get("REBIND_ME_URL", "http://127.0.0.1:4173")
STATES = ("idle", "working", "approval", "error")


def token() -> str:
    override = os.environ.get("REBIND_ME_TOKEN")
    if override:
        return override.strip()
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return (Path(base) / "RebindMe" / "bridge.token").read_text(encoding="utf-8").strip()


def call(method: str, path: str, body: dict | None = None, need_token: bool = False) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = request.Request(BASE_URL + path, data=data, method=method)
    req.add_header("Origin", BASE_URL)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if need_token:
        req.add_header("X-Bridge-Token", token())
    try:
        with request.urlopen(req, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        return json.loads(error.read().decode("utf-8"))
    except URLError as error:
        print(f"cannot reach bridge at {BASE_URL}: {error.reason}", file=sys.stderr)
        raise SystemExit(1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status", help="show bridge status")
    session = subparsers.add_parser("session", help="set a session status (drives the light)")
    session.add_argument("state", choices=STATES)
    session.add_argument("--id", default="cli")
    session.add_argument("--pid", type=int, default=0)
    subparsers.add_parser("shutdown", help="stop the bridge")
    args = parser.parse_args(argv)

    if args.command == "status":
        result = call("GET", "/api/status")
    elif args.command == "session":
        result = call(
            "POST",
            "/api/sessions",
            {"id": args.id, "status": args.state, "pid": args.pid},
            need_token=True,
        )
    else:
        result = call("POST", "/api/shutdown", {}, need_token=True)

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
