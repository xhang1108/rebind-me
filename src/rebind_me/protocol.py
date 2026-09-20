"""DualSense USB report decode / encode. See PROTOCOL.md.

Input report ID ``0x01`` (64 bytes on the wire). Output report ID ``0x02``
(48 bytes including the report ID). All offsets are into the full report, so
index ``0`` is the report ID.

This module is pure: it takes bytes in and returns bytes / dataclasses out.
Device I/O and mapping live in :mod:`rebind_me.hid` and
:mod:`rebind_me.engine`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

INPUT_REPORT_ID = 0x01
INPUT_REPORT_MIN_LENGTH = 11
OUTPUT_REPORT_ID = 0x02
OUTPUT_REPORT_LENGTH = 48
TRIGGER_EFFECT_LENGTH = 11

# --- Input offsets -------------------------------------------------------
IN_LEFT_X = 1
IN_LEFT_Y = 2
IN_RIGHT_X = 3
IN_RIGHT_Y = 4
IN_L2 = 5
IN_R2 = 6
IN_SEQUENCE = 7
IN_FACE_DPAD = 8
IN_MISC = 9
IN_SYSTEM = 10
IN_TOUCH_FIRST = 33
IN_TOUCH_SECOND = 37

# --- Output offsets ------------------------------------------------------
OUT_VALID_FLAG0 = 1
OUT_VALID_FLAG1 = 2
OUT_MOTOR_RIGHT = 3
OUT_MOTOR_LEFT = 4
OUT_MIC_LED = 9
OUT_POWER_SAVE = 10
OUT_RIGHT_TRIGGER = 11
OUT_LEFT_TRIGGER = 22
OUT_LED_BRIGHTNESS = 43
OUT_PLAYER_LEDS = 44
OUT_LIGHTBAR = 45

# --- Output valid flags --------------------------------------------------
FLAG0_COMPATIBLE_VIBRATION = 0x01
FLAG0_HAPTICS_SELECT = 0x02
FLAG0_RIGHT_TRIGGER = 0x04
FLAG0_LEFT_TRIGGER = 0x08

FLAG1_MIC_MUTE_LED = 0x01
FLAG1_POWER_SAVE = 0x02
FLAG1_LIGHTBAR = 0x04
FLAG1_PLAYER_LEDS = 0x10

FLAG1_STEADY_STATE = (
    FLAG1_MIC_MUTE_LED | FLAG1_POWER_SAVE | FLAG1_LIGHTBAR | FLAG1_PLAYER_LEDS
)

POWER_SAVE_MIC_MUTE = 0x10
MIC_LED_ON = 0x01

# --- Trigger effect modes -----------------------------------------------
TRIGGER_MODE_OFF = 0x00
TRIGGER_MODE_FEEDBACK = 0x21
TRIGGER_MODE_WEAPON = 0x25

# --- Button names --------------------------------------------------------
FACE_BUTTONS = ("square", "cross", "circle", "triangle")
DPAD_BUTTONS = ("dpad_up", "dpad_right", "dpad_down", "dpad_left")
SHOULDER_BUTTONS = ("l1", "r1", "l2", "r2", "create", "options", "l3", "r3")
SYSTEM_BUTTONS = ("ps", "touchpad", "mute")
BUTTON_NAMES = FACE_BUTTONS + DPAD_BUTTONS + SHOULDER_BUTTONS + SYSTEM_BUTTONS

_DPAD_MAP: tuple[tuple[str, ...], ...] = (
    ("dpad_up",),
    ("dpad_up", "dpad_right"),
    ("dpad_right",),
    ("dpad_right", "dpad_down"),
    ("dpad_down",),
    ("dpad_down", "dpad_left"),
    ("dpad_left",),
    ("dpad_up", "dpad_left"),
    (),
)


@dataclass(frozen=True)
class TouchPoint:
    """One decoded touchpad contact."""

    active: bool
    id: int
    x: int
    y: int


@dataclass(frozen=True)
class InputState:
    """Decoded buttons, sticks, triggers and the first active touch point."""

    buttons: frozenset[str]
    left_x: float
    left_y: float
    right_x: float
    right_y: float
    left_trigger: float
    right_trigger: float
    sequence: int
    touch: TouchPoint | None


def _clamp_byte(value: object) -> int:
    return max(0, min(255, int(value)))  # type: ignore[arg-type]


def _distance(value: int) -> float:
    normalized = (value - 127.5) / 127.5
    return round(max(-1.0, min(1.0, normalized)), 3)


def _decode_touch(report: bytes) -> TouchPoint | None:
    for offset in (IN_TOUCH_FIRST, IN_TOUCH_SECOND):
        if len(report) < offset + 4:
            continue
        block = report[offset : offset + 4]
        if block[0] & 0x80:
            continue
        x = ((block[2] & 0x0F) << 8) | block[1]
        y = (block[3] << 4) | (block[2] >> 4)
        return TouchPoint(active=True, id=block[0] & 0x7F, x=x, y=y)
    return None


def decode_input_report(report: bytes) -> InputState:
    """Decode a DualSense USB input report.

    Raises:
        ValueError: if the report is too short or is not report ID ``0x01``.
    """
    if len(report) < INPUT_REPORT_MIN_LENGTH or report[0] != INPUT_REPORT_ID:
        raise ValueError("unsupported DualSense USB input report")

    face_dpad = report[IN_FACE_DPAD]
    misc = report[IN_MISC]
    system = report[IN_SYSTEM]

    buttons: set[str] = set(_DPAD_MAP[face_dpad & 0x0F])
    for bit, name in enumerate(FACE_BUTTONS, start=4):
        if face_dpad & (1 << bit):
            buttons.add(name)

    for bit, name in enumerate(SHOULDER_BUTTONS):
        if misc & (1 << bit):
            buttons.add(name)

    for bit, name in enumerate(SYSTEM_BUTTONS):
        if system & (1 << bit):
            buttons.add(name)

    return InputState(
        buttons=frozenset(buttons),
        left_x=_distance(report[IN_LEFT_X]),
        left_y=_distance(report[IN_LEFT_Y]),
        right_x=_distance(report[IN_RIGHT_X]),
        right_y=_distance(report[IN_RIGHT_Y]),
        left_trigger=round(report[IN_L2] / 255, 3),
        right_trigger=round(report[IN_R2] / 255, 3),
        sequence=report[IN_SEQUENCE],
        touch=_decode_touch(report),
    )


def encode_trigger_effect(config: Mapping[str, object]) -> bytes:
    """Encode one adaptive trigger effect (11 bytes). See PROTOCOL.md §2.3."""
    effect = bytearray(TRIGGER_EFFECT_LENGTH)
    mode = str(config.get("mode", "off")).strip().lower()

    if mode == "off":
        return bytes(effect)

    if mode == "weapon":
        start = int(config["start"])  # type: ignore[arg-type]
        end = int(config["end"])  # type: ignore[arg-type]
        strength = int(config["strength"])  # type: ignore[arg-type]
        breakpoints = (1 << start) | (1 << end)
        effect[0] = TRIGGER_MODE_WEAPON
        effect[1:3] = breakpoints.to_bytes(2, "little")
        effect[3] = strength - 1
        return bytes(effect)

    if mode == "feedback":
        start = int(config["start"])  # type: ignore[arg-type]
        strength = int(config["strength"])  # type: ignore[arg-type]
        active_zones = ((1 << (10 - start)) - 1) << start
        force_zones = sum((strength - 1) << (zone * 3) for zone in range(start, 10))
        effect[0] = TRIGGER_MODE_FEEDBACK
        effect[1:3] = active_zones.to_bytes(2, "little")
        effect[3:7] = force_zones.to_bytes(4, "little")
        return bytes(effect)

    raise ValueError(f"unknown trigger mode: {mode!r}")


def _brightness_bucket(brightness: int) -> int:
    if brightness <= 0:
        return 0
    if brightness < 34:
        return 1
    if brightness < 67:
        return 2
    return 3


def encode_output_report(
    *,
    lightbar: Sequence[int] = (0, 0, 0),
    brightness: int = 100,
    player_leds: int = 0,
    mic_muted: bool = False,
    mic_led_inverted: bool = True,
    triggers: Mapping[str, Mapping[str, object]] | None = None,
    zero_motors: bool = False,
) -> bytes:
    """Encode a DualSense USB output report (48 bytes).

    ``lightbar`` is ``(red, green, blue)``; ``brightness`` is ``0..100``;
    ``player_leds`` is a 5-bit mask. Pass ``triggers`` with ``"left"`` and/or
    ``"right"`` configs to update adaptive triggers; ``None`` leaves them
    untouched. ``zero_motors`` clears both rumble motors (used on shutdown).
    """
    report = bytearray(OUTPUT_REPORT_LENGTH)
    report[0] = OUTPUT_REPORT_ID

    if zero_motors:
        report[OUT_VALID_FLAG0] |= FLAG0_COMPATIBLE_VIBRATION | FLAG0_HAPTICS_SELECT

    if triggers is not None:
        report[OUT_VALID_FLAG0] |= FLAG0_RIGHT_TRIGGER | FLAG0_LEFT_TRIGGER
        right = triggers.get("right", {"mode": "off"})
        left = triggers.get("left", {"mode": "off"})
        report[OUT_RIGHT_TRIGGER : OUT_RIGHT_TRIGGER + TRIGGER_EFFECT_LENGTH] = (
            encode_trigger_effect(right)
        )
        report[OUT_LEFT_TRIGGER : OUT_LEFT_TRIGGER + TRIGGER_EFFECT_LENGTH] = (
            encode_trigger_effect(left)
        )

    report[OUT_VALID_FLAG1] = FLAG1_STEADY_STATE

    led_on = (not mic_muted) if mic_led_inverted else mic_muted
    report[OUT_MIC_LED] = MIC_LED_ON if led_on else 0x00
    if mic_muted:
        report[OUT_POWER_SAVE] |= POWER_SAVE_MIC_MUTE

    report[OUT_LED_BRIGHTNESS] = _brightness_bucket(int(brightness))
    report[OUT_PLAYER_LEDS] = max(0, min(0x1F, int(player_leds)))

    red, green, blue = (_clamp_byte(channel) for channel in lightbar)
    report[OUT_LIGHTBAR] = red
    report[OUT_LIGHTBAR + 1] = green
    report[OUT_LIGHTBAR + 2] = blue

    return bytes(report)


__all__ = [
    "BUTTON_NAMES",
    "FACE_BUTTONS",
    "DPAD_BUTTONS",
    "SHOULDER_BUTTONS",
    "SYSTEM_BUTTONS",
    "INPUT_REPORT_ID",
    "OUTPUT_REPORT_ID",
    "OUTPUT_REPORT_LENGTH",
    "TRIGGER_EFFECT_LENGTH",
    "TRIGGER_MODE_OFF",
    "TRIGGER_MODE_FEEDBACK",
    "TRIGGER_MODE_WEAPON",
    "InputState",
    "TouchPoint",
    "decode_input_report",
    "encode_trigger_effect",
    "encode_output_report",
]
