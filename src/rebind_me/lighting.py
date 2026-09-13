"""Light bar / player LEDs state machine. See plan.md §9.

Produces a :class:`LightFrame` (RGB, brightness, player LEDs) for a given
monotonic time. Effects: ``static``, ``breathe`` and ``blink``; speed is 1..5.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

STATUS_STATES = ("idle", "working", "approval", "error")

# Periods in seconds for speed 1..5 (faster speed -> shorter period).
BLINK_PERIOD_SECONDS = (2.0, 1.6, 1.2, 0.8, 0.55)
BREATHE_PERIOD_SECONDS = (5.0, 4.0, 3.2, 2.4, 1.7)


@dataclass(frozen=True)
class LightFrame:
    red: int
    green: int
    blue: int
    brightness: int
    player_leds: int


def _speed_index(speed: int) -> int:
    return max(1, min(5, int(speed))) - 1


def effect_factor(effect: str, speed: int, now: float) -> float:
    """Return the 0.0..1.0 intensity multiplier for an effect at ``now``."""
    if effect == "static":
        return 1.0
    if effect == "breathe":
        period = BREATHE_PERIOD_SECONDS[_speed_index(speed)]
        return 0.5 * (1.0 - math.cos(2.0 * math.pi * now / period))
    if effect == "blink":
        period = BLINK_PERIOD_SECONDS[_speed_index(speed)]
        return 1.0 if (now % period) < period / 2.0 else 0.0
    raise ValueError(f"unknown light effect: {effect!r}")


class LightingController:
    """Turns the current status (or manual override) into light frames."""

    def __init__(self, lighting_settings: dict):
        self._settings = lighting_settings
        self._status = "idle"
        self._manual_override = False

    def apply(self, lighting_settings: dict) -> None:
        self._settings = lighting_settings

    @property
    def mode(self) -> str:
        if self._manual_override:
            return "manual"
        return str(self._settings.get("mode", "status"))

    def set_status(self, state: str) -> None:
        if state not in STATUS_STATES:
            raise ValueError(f"unknown status: {state!r}")
        self._status = state

    @property
    def status(self) -> str:
        return self._status

    def set_manual_override(self, enabled: bool) -> None:
        self._manual_override = bool(enabled)

    def _active_light(self) -> dict:
        if self.mode == "manual":
            return self._settings["manual"]
        return self._settings["status"][self._status]

    def frame(self, now: float) -> LightFrame:
        light = self._active_light()
        factor = effect_factor(light["effect"], light["speed"], now)
        red, green, blue = light["color"]
        return LightFrame(
            red=round(red * factor),
            green=round(green * factor),
            blue=round(blue * factor),
            brightness=int(self._settings.get("brightness", 100)),
            player_leds=max(0, min(0x1F, int(self._settings.get("playerLeds", 0)))),
        )


__all__ = [
    "BLINK_PERIOD_SECONDS",
    "BREATHE_PERIOD_SECONDS",
    "LightFrame",
    "LightingController",
    "STATUS_STATES",
    "effect_factor",
]
