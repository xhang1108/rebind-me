"""Adaptive trigger normalization and encoding. See plan.md §10.

Effect encoding itself lives in :mod:`rebind_me.protocol`; this module owns the
range rules and the wire-format factory.
"""

from __future__ import annotations

from .errors import RebindError
from .protocol import encode_trigger_effect

TRIGGER_MODES = ("off", "feedback", "weapon")
DEFAULT_TRIGGER = {"mode": "off", "start": 3, "end": 6, "strength": 5}


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def normalize_trigger(trigger: object) -> dict[str, int | str]:
    """Validate and clamp one trigger config.

    Raises:
        RebindError: ``INVALID_TRIGGER_MODE`` for an unknown mode or a
            weapon-only range violation, ``SCHEMA_ERROR`` otherwise.
    """
    if trigger is None:
        trigger = {}
    if not isinstance(trigger, dict):
        raise RebindError("SCHEMA_ERROR", "trigger configuration must be an object")

    mode = str(trigger.get("mode", "off")).strip().lower()
    if mode not in TRIGGER_MODES:
        raise RebindError(
            "INVALID_TRIGGER_MODE", "trigger mode must be off, feedback or weapon"
        )

    start = _clamp(int(trigger.get("start", 3)), 0, 9)
    strength = _clamp(int(trigger.get("strength", 5)), 1, 8)
    requested_end = _clamp(int(trigger.get("end", max(start + 1, 6))), 1, 9)
    end = min(9, max(start + 1, requested_end))

    if mode == "weapon":
        if not 2 <= start <= 7:
            raise RebindError(
                "INVALID_TRIGGER_MODE", "weapon trigger start must be 2..7"
            )
        if not start < end <= 8:
            raise RebindError(
                "INVALID_TRIGGER_MODE",
                "weapon trigger end must be after start and at most 8",
            )

    return {"mode": mode, "start": start, "end": end, "strength": strength}


def normalize_triggers(payload: object) -> dict[str, dict[str, int | str]]:
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise RebindError("SCHEMA_ERROR", "triggers must be an object")
    return {
        "left": normalize_trigger(payload.get("left", {})),
        "right": normalize_trigger(payload.get("right", {})),
    }


def encode_trigger(config: object) -> bytes:
    """Normalize ``config`` and encode the 11-byte effect block."""
    return encode_trigger_effect(normalize_trigger(config))


__all__ = [
    "DEFAULT_TRIGGER",
    "TRIGGER_MODES",
    "encode_trigger",
    "normalize_trigger",
    "normalize_triggers",
]
