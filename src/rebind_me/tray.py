"""Tray application (separate process, normal privileges).

Started at startup through the HKCU ``...\\Run`` entry. It controls the elevated
bridge with ``schtasks`` (start / restart) and the local API (stop, status,
autostart), and opens the UI in the default browser. The icon lives in its own
process so a bridge restart never disturbs it.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from typing import Callable

from .autostart import ScheduledTask
from .logsetup import setup_logging
from .store import (
    DEFAULT_PORT,
    SETTINGS_FILENAME,
    TOKEN_FILENAME,
    runtime_dir,
)
from .winapi.mutex import TRAY_MUTEX, SingleInstance
from .winapi.notifyicon import MenuItem, NIIF_ERROR, TrayIcon

ICON_PATH = Path(__file__).resolve().parent / "ui" / "assets" / "tray.ico"
POLL_SECONDS = 2.0
RESTART_POLL = 0.25

STATUS_ID = 1000
START_ID = 1001
STOP_ID = 1002
RESTART_ID = 1003
OPEN_UI_ID = 1004
AUTOSTART_ID = 1005
EXIT_ID = 1006


class BridgeClient:
    """Minimal HTTP client for the local bridge API. Failures are silent."""

    def __init__(self, base_url: str, token: str | None, timeout: float = 2.0):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def _call(self, method: str, path: str, body: dict | None = None, token: bool = False):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Content-Type": "application/json"}
        if token and self.token:
            headers["X-Bridge-Token"] = self.token
        request = urllib.request.Request(
            self.base_url + path, data=data, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                envelope = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError):
            return None
        if not isinstance(envelope, dict) or not envelope.get("ok"):
            return None
        return envelope.get("data")

    def status(self):
        return self._call("GET", "/api/status")

    def settings(self):
        return self._call("GET", "/api/settings")

    def shutdown(self):
        return self._call("POST", "/api/shutdown", {}, token=True)

    def autostart(self, bridge: bool, tray: bool):
        return self._call(
            "POST", "/api/autostart", {"bridge": bridge, "tray": tray}, token=True
        )


def read_token(root: Path) -> str | None:
    try:
        token = (root / TOKEN_FILENAME).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return token or None


def read_port(root: Path) -> int:
    try:
        document = json.loads((root / SETTINGS_FILENAME).read_text(encoding="utf-8"))
        port = int(document.get("port", DEFAULT_PORT))
    except (OSError, ValueError, TypeError):
        return DEFAULT_PORT
    return port if 1 <= port <= 65535 else DEFAULT_PORT


def _wait_until(
    condition: Callable[[], bool], timeout: float, sleep: Callable[[float], None]
) -> bool:
    remaining = timeout
    while True:
        if condition():
            return True
        if remaining <= 0:
            return False
        sleep(RESTART_POLL)
        remaining -= RESTART_POLL


def stop_bridge(
    client: "BridgeClient",
    task: ScheduledTask,
    log=None,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Stop the bridge gracefully, falling back to ``schtasks /End`` if needed.

    Ending the task immediately before a later ``/Run`` can make the scheduler
    ignore the start (the previous instance is still being reaped under
    ``MultipleInstances=IgnoreNew``), so the graceful HTTP shutdown is always
    tried first. Returns whether the API went offline.
    """
    client.shutdown()
    stopped = _wait_until(lambda: client.status() is None, 5.0, sleep)
    if not stopped:
        task.end()
        stopped = _wait_until(lambda: client.status() is None, 5.0, sleep)
    if not stopped and log:
        log.warning("stop: bridge did not stop")
    return stopped


def start_bridge(
    client: "BridgeClient",
    task: ScheduledTask,
    log=None,
    sleep: Callable[[float], None] = time.sleep,
    attempts: int = 5,
) -> bool:
    """Run the bridge task, retrying until the API answers again."""
    for _ in range(attempts):
        try:
            task.run_now()
        except Exception as error:  # noqa: BLE001 - a failed start is retried
            if log:
                log.warning("start: schtasks /Run failed: %s", error)
        if _wait_until(lambda: client.status() is not None, 5.0, sleep):
            if log:
                log.info("start: bridge is online")
            return True
    if log:
        log.warning("start: bridge did not come online")
    return False


def restart_bridge(
    client: "BridgeClient",
    task: ScheduledTask,
    log=None,
    sleep: Callable[[float], None] = time.sleep,
    attempts: int = 5,
) -> bool:
    """Stop the bridge, wait for it to exit, then start the task again."""
    stop_bridge(client, task, log, sleep)
    return start_bridge(client, task, log, sleep, attempts)


def probe_state(client: "BridgeClient", task: ScheduledTask) -> dict:
    """Snapshot the bridge for the menu: online state, device, uptime and
    whether the autostart task exists at all (so "stopped" can be told apart
    from "not installed"). The task is only queried while the bridge is down,
    so a running bridge costs a single HTTP call per poll."""
    status = client.status()
    online = status is not None
    settings = client.settings() if online else None
    return {
        "online": online,
        "device": (status or {}).get("device", "?"),
        "status": (status or {}).get("status", "?"),
        "pid": (status or {}).get("pid"),
        "uptime": (status or {}).get("uptime", 0.0),
        "installed": True if online else task.exists(),
        "autostart": (settings or {}).get("autostart", {}),
    }


def autostart_targets(current: dict) -> dict:
    """A single switch drives both entries: on only when both are on."""
    enabled = bool(current.get("bridge")) and bool(current.get("tray"))
    desired = not enabled
    return {"bridge": desired, "tray": desired}


def build_menu(snapshot: dict) -> list[MenuItem]:
    """Menu entries for a bridge snapshot, grouped by state."""
    online = bool(snapshot.get("online"))
    installed = bool(snapshot.get("installed"))
    autostart = snapshot.get("autostart") or {}
    if online:
        label = f"Status: running ({snapshot.get('device', '?')}) · up {snapshot.get('uptime', 0):.0f}s"
    elif installed:
        label = "Status: stopped"
    else:
        label = "Status: not installed"
    return [
        MenuItem(STATUS_ID, label, enabled=False),
        MenuItem(None),
        MenuItem(START_ID, "Start", enabled=installed and not online),
        MenuItem(STOP_ID, "Stop", enabled=online),
        MenuItem(RESTART_ID, "Restart", enabled=online),
        MenuItem(None),
        MenuItem(OPEN_UI_ID, "Open UI"),
        MenuItem(
            AUTOSTART_ID,
            "Start at startup",
            checked=bool(autostart.get("bridge")) and bool(autostart.get("tray")),
            enabled=online,
        ),
        MenuItem(None),
        MenuItem(EXIT_ID, "Exit"),
    ]


class TrayApp:
    def __init__(self, root: Path | None = None):
        self.root = root or runtime_dir()
        port = read_port(self.root)
        self.client = BridgeClient(f"http://127.0.0.1:{port}", read_token(self.root))
        self.task = ScheduledTask()
        self._lock = threading.Lock()
        self._snapshot: dict = {
            "online": False,
            "device": "?",
            "status": "?",
            "pid": None,
            "uptime": 0.0,
            "installed": False,
            "autostart": {},
        }
        self._stop = threading.Event()
        self._log = None
        self.icon = TrayIcon(
            tooltip="Rebind Me",
            icon_path=str(ICON_PATH) if ICON_PATH.exists() else None,
            menu_items=self._menu_items,
            on_select=self._on_select,
            on_double_click=self._open_ui,
            on_refresh=self._refresh_ui,
        )
        self._thread: threading.Thread | None = None

    # -- lifecycle --------------------------------------------------------
    def run(self) -> int:
        try:
            self._log = setup_logging(self.root / "logs", "info")
        except OSError:
            self._log = None
        if self._log:
            self._log.info("tray started")
        self.icon.add()
        self._thread = threading.Thread(target=self._poll, name="rebind-tray-poll", daemon=True)
        self._thread.start()
        try:
            self.icon.run()
        finally:
            self._stop.set()
            self.icon.close()
            if self._log:
                self._log.info("tray stopped")
        return 0

    # -- polling ----------------------------------------------------------
    def _poll(self) -> None:
        while not self._stop.is_set():
            self._sample()
            self.icon.post_refresh()
            self._stop.wait(POLL_SECONDS)

    def _sample(self) -> None:
        snapshot = probe_state(self.client, self.task)
        with self._lock:
            self._snapshot = snapshot

    def _snapshot_copy(self) -> dict:
        with self._lock:
            return dict(self._snapshot)

    def _refresh_ui(self) -> None:
        snapshot = self._snapshot_copy()
        if snapshot["online"]:
            tooltip = (
                f"Rebind Me - running (pid {snapshot.get('pid')}, "
                f"up {snapshot.get('uptime', 0):.0f}s)"
            )
        elif snapshot.get("installed"):
            tooltip = "Rebind Me - stopped"
        else:
            tooltip = "Rebind Me - not installed"
        self.icon.set_tooltip(tooltip[:127])

    # -- menu -------------------------------------------------------------
    def _menu_items(self) -> list[MenuItem]:
        return build_menu(self._snapshot_copy())

    def _on_select(self, item_id: int) -> None:
        try:
            if item_id == START_ID:
                self._run_action("start", start_bridge)
            elif item_id == STOP_ID:
                self._run_action("stop", stop_bridge)
            elif item_id == RESTART_ID:
                self._run_action("restart", restart_bridge)
            elif item_id == OPEN_UI_ID:
                self._open_ui()
            elif item_id == AUTOSTART_ID:
                self._toggle_autostart()
            elif item_id == EXIT_ID:
                self.icon.quit()
        except Exception as error:  # noqa: BLE001 - a tray action must never crash
            if self._log:
                self._log.warning("tray action %s failed: %s", item_id, error)

    def _open_ui(self) -> None:
        webbrowser.open(self.client.base_url + "/")

    def _run_action(self, label: str, action) -> None:
        """Run a bridge action off the tray message loop, then report the
        result with a balloon and a fresh tooltip."""
        past = {"start": "started", "stop": "stopped", "restart": "restarted"}[label]
        present = {"start": "starting", "stop": "stopping", "restart": "restarting"}[label]

        def work() -> None:
            self.icon.set_tooltip(f"Rebind Me - {present}...")
            ok = action(self.client, self.task, self._log)
            self._sample()
            self.icon.post_refresh()
            if ok:
                self.icon.notify("Rebind Me", f"Bridge {past}")
            else:
                self.icon.notify(
                    "Rebind Me", f"Failed to {label} the bridge", NIIF_ERROR
                )

        threading.Thread(target=work, name=f"rebind-tray-{label}", daemon=True).start()

    def _toggle_autostart(self) -> None:
        snapshot = self._snapshot_copy()
        targets = autostart_targets(snapshot.get("autostart") or {})
        result = self.client.autostart(targets["bridge"], targets["tray"])
        if result is None:
            if self._log:
                self._log.info("autostart toggle skipped: bridge is offline")
            self.icon.notify(
                "Rebind Me",
                "Autostart not changed: bridge is offline",
                NIIF_ERROR,
            )
            return
        with self._lock:
            self._snapshot["autostart"] = {
                "bridge": bool(result.get("bridge", targets["bridge"])),
                "tray": bool(result.get("tray", targets["tray"])),
            }
        self.icon.post_refresh()
        if not result.get("applied", True):
            if self._log:
                self._log.warning("autostart change did not apply")
            self.icon.notify(
                "Rebind Me",
                "Autostart not changed: run the installer as administrator",
                NIIF_ERROR,
            )


def main(argv: list[str] | None = None) -> int:
    _ = list(argv or [])
    instance = SingleInstance(TRAY_MUTEX)
    if not instance.acquire():
        return 1
    try:
        return TrayApp().run()
    finally:
        instance.release()


__all__ = [
    "BridgeClient",
    "TrayApp",
    "autostart_targets",
    "build_menu",
    "main",
    "probe_state",
    "read_port",
    "read_token",
    "restart_bridge",
    "start_bridge",
    "stop_bridge",
]


if __name__ == "__main__":
    raise SystemExit(main())
