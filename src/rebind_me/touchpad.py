"""Touchpad mouse movement and zone-based tap / click. See plan.md §8.

Only the first active contact is used. Left/right zones are decided by
``splitX`` (12-bit X, default 960). Output is emitted through an injected
object with ``mouse_move(dx, dy)``, ``key_down(code)`` and ``key_up(code)``.
"""

from __future__ import annotations

from .protocol import TouchPoint
from .store import TOUCHPAD_MAX_X

TAP_MAX_SECONDS = 0.30
TAP_MAX_DELTA = 25


class TouchpadController:
    def __init__(self, config: dict):
        self.apply(config)
        self._tracking = False
        self._start_x = 0
        self._start_y = 0
        self._last_x = 0
        self._last_y = 0
        self._start_time = 0.0
        self._button_down = False

    def apply(self, config: dict) -> None:
        self.mouse_control = bool(config.get("mouseControl", True))
        self.sensitivity = float(config.get("sensitivity", 1.5))
        self.split_x = int(config.get("splitX", 960))
        self.tap = config.get("tap", {"left": "MouseLeft", "right": "MouseRight"})
        self.click = config.get("click", {"left": "MouseLeft", "right": "MouseRight"})

    def zone(self, x: int) -> str:
        return "left" if x < self.split_x else "right"

    def update(self, touch: TouchPoint | None, button_pressed: bool, now: float, output: object) -> None:
        if button_pressed and not self._button_down:
            self._emit_click(output, touch)
        self._button_down = button_pressed

        if touch is None:
            self._finish_touch(now, output)
            return

        if not self._tracking:
            self._tracking = True
            self._start_x = self._last_x = touch.x
            self._start_y = self._last_y = touch.y
            self._start_time = now
            return

        if self.mouse_control:
            dx = int((touch.x - self._last_x) * self.sensitivity)
            dy = int((touch.y - self._last_y) * self.sensitivity)
            if dx or dy:
                output.mouse_move(dx, dy)
        self._last_x = touch.x
        self._last_y = touch.y

    def _finish_touch(self, now: float, output: object) -> None:
        if not self._tracking:
            return
        moved = max(abs(self._last_x - self._start_x), abs(self._last_y - self._start_y))
        if (
            self.mouse_control
            and now - self._start_time <= TAP_MAX_SECONDS
            and moved <= TAP_MAX_DELTA
        ):
            code = self.tap.get(self.zone(self._last_x), "")
            if code:
                output.key_down(code)
                output.key_up(code)
        self._tracking = False

    def _emit_click(self, output: object, touch: TouchPoint | None) -> None:
        x = touch.x if touch is not None else self._last_x
        code = self.click.get(self.zone(x), "")
        if code:
            output.key_down(code)
            output.key_up(code)

    def reset(self) -> None:
        self._tracking = False
        self._button_down = False


__all__ = ["TAP_MAX_DELTA", "TAP_MAX_SECONDS", "TOUCHPAD_MAX_X", "TouchpadController"]
