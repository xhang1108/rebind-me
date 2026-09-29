"""Button actions.

Selection logic is pure (see :func:`choose_terminal`) so it can be tested with
fake window and session data; execution goes through injected callables.
"""

from __future__ import annotations

from typing import Callable, Sequence

from .errors import RebindError
from .webhook import WebhookClient

STATUS_RANK = {"completed": 0, "done": 0, "working": 1, "busy": 1}


def choose_terminal(
    candidates: Sequence[dict], sessions: Sequence[dict]
) -> int | None:
    """Pick a window to focus.

    Priority: completed -> working -> most recently active. If the reported
    sessions collapse to one window (or none were reported), fall back to the
    top-most visible window in Z-order.
    """
    if not candidates:
        return None
    by_pid: dict[int, dict] = {}
    for window in candidates:
        by_pid.setdefault(window["pid"], window)

    if sessions:
        ranked = sorted(
            sessions,
            key=lambda session: (
                STATUS_RANK.get(str(session.get("status", "")).lower(), 2),
                -float(session.get("lastActive", 0) or 0),
            ),
        )
        ordered_pids = [s["pid"] for s in ranked if s.get("pid") in by_pid]
        if len(set(ordered_pids)) > 1:
            return by_pid[ordered_pids[0]]["hwnd"]

    return candidates[0]["hwnd"]


def _matches_process(name: str, target: str) -> bool:
    if not name or not target:
        return False
    stem = name[:-4] if name.lower().endswith(".exe") else name
    return stem.lower() == target.lower()


class ActionRunner:
    def __init__(
        self,
        windows: object,
        sessions_provider: Callable[[], Sequence[dict]] | None = None,
        toggle_mouse_mode: Callable[[], None] | None = None,
        open_ui: Callable[[], None] | None = None,
        webhook: WebhookClient | None = None,
    ):
        self.windows = windows
        self.sessions_provider = sessions_provider or (lambda: [])
        self.toggle_mouse_mode = toggle_mouse_mode or (lambda: None)
        self.open_ui = open_ui or (lambda: None)
        self.webhook = webhook or WebhookClient()
        self._return_hwnd: int | None = None

    def run(
        self,
        name: str,
        action: str,
        params: dict | None = None,
        pressed: bool = True,
    ) -> dict:
        params = params or {}
        if action == "focus-terminal":
            return self._focus_terminal()
        if action == "switch-to-app":
            return self._switch_to_app(str(params.get("process", "")))
        if action == "toggle-mouse-mode":
            self.toggle_mouse_mode()
            return {"toggled": True}
        if action == "open-config-ui":
            self.open_ui()
            return {"opened": True}
        if action == "webhook":
            return self._webhook(params, pressed)
        raise RebindError("SCHEMA_ERROR", f"unknown action: {action!r}")

    def _webhook(self, params: dict, pressed: bool) -> dict:
        """Fire a configured request. Press fires ``url``; release fires ``upUrl``
        when present. A press-only webhook simply omits ``upUrl``."""
        if pressed:
            url = params.get("url")
            if not url:
                return {"skipped": True, "reason": "no-url"}
            self.webhook.request(
                url, method=params.get("method"), body=params.get("body")
            )
            return {"fired": "down"}
        up_url = params.get("upUrl")
        if not up_url:
            return {"ignored": True}
        self.webhook.request(
            up_url, method=params.get("upMethod"), body=params.get("upBody")
        )
        return {"fired": "up"}

    def _focus_terminal(self) -> dict:
        candidates = self.windows.list_windows()
        hwnd = choose_terminal(candidates, self.sessions_provider())
        if hwnd is None:
            return {"focused": False, "reason": "no-window"}
        focused = self.windows.focus_window(hwnd)
        return {"focused": bool(focused), "hwnd": int(hwnd)}

    def _switch_to_app(self, process: str) -> dict:
        """Focus ``process``, or toggle back to where the switch came from.

        The first press remembers the window that was foreground and focuses
        the target. Pressing again while the target is still foreground returns
        to the remembered window, so one button becomes an app toggle.
        """
        if not process:
            raise RebindError("SCHEMA_ERROR", "switch-to-app requires a process")
        candidates = self.windows.list_windows()
        target = next(
            (
                window
                for window in candidates
                if _matches_process(self.windows.process_name(window["pid"]), process)
            ),
            None,
        )
        if target is None:
            return {"focused": False, "reason": "not-running"}

        hwnd = int(target["hwnd"])
        current = self.windows.foreground_hwnd()
        if hwnd == current and self._return_hwnd is not None:
            back = self._return_hwnd
            if not any(int(window["hwnd"]) == back for window in candidates):
                self._return_hwnd = None
                return {"focused": False, "reason": "gone"}
            self._return_hwnd = current
            focused = self.windows.focus_window(back)
            return {"focused": bool(focused), "hwnd": back}

        self._return_hwnd = current if current and current != hwnd else None
        focused = self.windows.focus_window(hwnd)
        return {"focused": bool(focused), "hwnd": hwnd}


__all__ = ["ActionRunner", "STATUS_RANK", "choose_terminal"]
