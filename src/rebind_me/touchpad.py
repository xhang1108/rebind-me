"""Touchpad mouse movement and zone-based tap / click.

Only the first active contact is used. Left/right zones are decided by
the midpoint of the 12-bit X range. Movement is written through an injected
object with ``mouse_move(dx, dy)``; tap and click are returned to the caller
as gesture events so the bridge can resolve them through the mapping engine.
"""

from __future__ import annotations

from .protocol import TouchPoint

TAP_MAX_SECONDS = 0.30
TAP_MAX_DELTA = 25
SPLIT_X = 960


class TouchpadController:
    def __init__(self, config: dict | None = None):
        self.apply(config or {})
        self._tracking = False
        self._start_x = 0
        self._start_y = 0
        self._last_x = 0
        self._last_y = 0
        self._start_time = 0.0
        self._button_down = False
        self._clicked = False

    def apply(self, config: dict) -> None:
        self.mouse_control = bool(config.get("mouseControl", True))
        self.sensitivity = float(config.get("sensitivity", 1.5))

    def zone(self, x: int) -> str:
        return "left" if x < SPLIT_X else "right"

    def update(
        self,
        touch: TouchPoint | None,
        button_pressed: bool,
        now: float,
        output: object,
    ) -> list[tuple[str, str]]:
        """Move the pointer through ``output`` and return gesture events.

        Each event is ``(kind, zone)`` with kind ``tap``, ``click-down`` or
        ``click-up``. A tap fires on release of a short, still contact; a click
        reports both edges so a held touchpad button can hold its mapping.
        """
        events: list[tuple[str, str]] = []
        clicked_now = False
        if button_pressed != self._button_down:
            zone = self.zone(touch.x if touch is not None else self._last_x)
            events.append(("click-down" if button_pressed else "click-up", zone))
            self._button_down = button_pressed
            if button_pressed:
                clicked_now = True
                self._clicked = True

        if touch is None:
            events.extend(self._finish_touch(now))
            return events

        if not self._tracking:
            self._tracking = True
            self._clicked = clicked_now
            self._start_x = self._last_x = touch.x
            self._start_y = self._last_y = touch.y
            self._start_time = now
            return events

        if self.mouse_control:
            dx = int((touch.x - self._last_x) * self.sensitivity)
            dy = int((touch.y - self._last_y) * self.sensitivity)
            if dx or dy:
                output.mouse_move(dx, dy)
        self._last_x = touch.x
        self._last_y = touch.y
        return events

    def _finish_touch(self, now: float) -> list[tuple[str, str]]:
        if not self._tracking:
            return []
        moved = max(abs(self._last_x - self._start_x), abs(self._last_y - self._start_y))
        tapped = (
            not self._clicked
            and now - self._start_time <= TAP_MAX_SECONDS
            and moved <= TAP_MAX_DELTA
        )
        self._tracking = False
        self._clicked = False
        return [("tap", self.zone(self._last_x))] if tapped else []

    def reset(self) -> None:
        self._tracking = False
        self._button_down = False
        self._clicked = False


__all__ = ["SPLIT_X", "TAP_MAX_DELTA", "TAP_MAX_SECONDS", "TouchpadController"]
