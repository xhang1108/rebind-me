"""Persistent data model, preset and atomic store. See plan.md §5 and §14.

Version 1 only. There is no legacy migration: on first start (or after
"restore defaults") the bundled preset is written and any unrecognised file is
replaced. Writes are atomic (temp + rename) and guarded by a ``baseVersion``
optimistic lock.
"""

from __future__ import annotations

import copy
import json
import os
import secrets
import threading
from pathlib import Path
from typing import Callable

from .errors import RebindError
from .keys import MOUSE_BUTTON_CODES, SCROLL_CODES, is_keyboard_code
from .protocol import BUTTON_NAMES
from .triggers import normalize_triggers

MAPPING_VERSION = 1
SETTINGS_VERSION = 1

MAPPING_STORE_FILENAME = "mapping-store.json"
SETTINGS_FILENAME = "settings.json"
TOKEN_FILENAME = "bridge.token"
LOGS_DIRNAME = "logs"
DEFAULT_PORT = 4173

STICK_DIRECTIONS = (
    "left_stick_up",
    "left_stick_right",
    "left_stick_down",
    "left_stick_left",
    "right_stick_up",
    "right_stick_right",
    "right_stick_down",
    "right_stick_left",
)
INPUT_NAMES = BUTTON_NAMES + STICK_DIRECTIONS

MAPPING_MODES = ("single", "repeat", "hold", "toggle")
ACTIONS = ("focus-terminal", "switch-to-app", "toggle-mouse-mode", "open-config-ui")

MAX_CHORD_SEGMENTS = 2
MAX_KEYS_PER_SEGMENT = 5
REPEAT_MIN_MS = 10
REPEAT_MAX_MS = 2000
DEFAULT_REPEAT = {"delayMs": 300, "intervalMs": 50}
DEFAULT_CHORD_DELAY_MS = 80
TOUCHPAD_MAX_X = 1919

_EFFECTS = ("static", "breathe", "blink")
_STATUS_STATES = ("idle", "working", "approval", "error")


def runtime_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.path.join(
        os.path.expanduser("~"), "AppData", "Local"
    )
    return Path(base) / "RebindMe"


DEFAULT_MAPPING_STORE: dict = {
    "version": MAPPING_VERSION,
    "enabled": True,
    "mappings": {
        "cross": {"mode": "single", "sequence": [["ControlLeft", "KeyK"], ["KeyL"]]},
        "circle": {
            "mode": "repeat",
            "sequence": [["Delete"]],
            "repeat": dict(DEFAULT_REPEAT),
        },
        "right_stick_up": {"mode": "single", "scroll": "ScrollUp"},
        "touchpad": {"mode": "single", "mouse": "MouseLeft"},
    },
    "actions": {
        "triangle": {"action": "switch-to-app", "params": {"process": "OpenChamber"}},
        "l1": {"action": "focus-terminal"},
    },
    "touchpad": {
        "mouseControl": True,
        "sensitivity": 1.5,
        "splitX": 960,
        "tap": {"left": "MouseLeft", "right": "MouseRight"},
        "click": {"left": "MouseLeft", "right": "MouseRight"},
    },
}

DEFAULT_SETTINGS: dict = {
    "version": SETTINGS_VERSION,
    "ui": {"language": "zh-Hant", "theme": "dark"},
    "logging": {"level": "info"},
    "lighting": {
        "mode": "status",
        "brightness": 100,
        "playerLeds": 0,
        "muteLedInvert": False,
        "status": {
            "idle": {"color": [0, 255, 0], "effect": "static", "speed": 3},
            "working": {"color": [255, 0, 0], "effect": "breathe", "speed": 3},
            "approval": {"color": [255, 255, 0], "effect": "blink", "speed": 3},
            "error": {"color": [255, 0, 0], "effect": "blink", "speed": 5},
        },
        "manual": {"color": [0, 0, 255], "effect": "static", "speed": 3},
    },
    "triggers": {
        "left": {"mode": "off", "start": 3, "end": 6, "strength": 5},
        "right": {"mode": "off", "start": 3, "end": 6, "strength": 5},
    },
    "port": DEFAULT_PORT,
    "autostart": {"bridge": False, "tray": False},
}


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def _schema(message: str) -> RebindError:
    return RebindError("SCHEMA_ERROR", message)


def _validate_sequence(value: object) -> list[list[str]]:
    if not isinstance(value, list):
        raise _schema("sequence must be a list of segments")
    if len(value) > MAX_CHORD_SEGMENTS:
        raise RebindError("MAPPING_LIMIT", "a chord may have at most 2 segments")
    segments: list[list[str]] = []
    for segment in value:
        if not isinstance(segment, list):
            raise _schema("each chord segment must be a list of key codes")
        if not 1 <= len(segment) <= MAX_KEYS_PER_SEGMENT:
            raise RebindError(
                "MAPPING_LIMIT", "each chord segment must have 1..5 key codes"
            )
        for code in segment:
            if not isinstance(code, str) or not is_keyboard_code(code):
                raise RebindError(
                    "INVALID_KEY_CODE", f"unknown keyboard code: {code!r}"
                )
        segments.append(list(segment))
    return segments


def _validate_repeat(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        raise _schema("repeat must be an object")
    delay = int(value.get("delayMs", DEFAULT_REPEAT["delayMs"]))
    interval = int(value.get("intervalMs", DEFAULT_REPEAT["intervalMs"]))
    if not REPEAT_MIN_MS <= delay <= REPEAT_MAX_MS:
        raise _schema(f"repeat.delayMs must be {REPEAT_MIN_MS}..{REPEAT_MAX_MS}")
    if not REPEAT_MIN_MS <= interval <= REPEAT_MAX_MS:
        raise _schema(f"repeat.intervalMs must be {REPEAT_MIN_MS}..{REPEAT_MAX_MS}")
    return {"delayMs": delay, "intervalMs": interval}


def _validate_mapping(entry: object) -> dict:
    if not isinstance(entry, dict):
        raise _schema("mapping entry must be an object")

    mode = str(entry.get("mode", "single")).strip().lower()
    if mode not in MAPPING_MODES:
        raise RebindError("INVALID_MODE", f"unknown mode: {mode!r}")

    present = [key for key in ("sequence", "mouse", "scroll") if key in entry]
    if len(present) != 1:
        raise _schema("a mapping needs exactly one of sequence, mouse or scroll")

    result: dict = {"mode": mode}
    if present[0] == "sequence":
        sequence = _validate_sequence(entry["sequence"])
        if len(sequence) > 1 and mode != "single":
            raise RebindError("INVALID_MODE", "a chord must use mode single")
        result["sequence"] = sequence
    elif present[0] == "mouse":
        mouse = entry["mouse"]
        if mouse not in MOUSE_BUTTON_CODES:
            raise RebindError("INVALID_KEY_CODE", f"unknown mouse code: {mouse!r}")
        result["mouse"] = mouse
    else:
        scroll = entry["scroll"]
        if scroll not in SCROLL_CODES:
            raise RebindError("INVALID_KEY_CODE", f"unknown scroll code: {scroll!r}")
        result["scroll"] = scroll

    if mode == "repeat":
        result["repeat"] = _validate_repeat(entry.get("repeat", {}))
    elif "repeat" in entry:
        raise _schema("repeat is only valid for mode repeat")

    if mode == "toggle":
        initial = str(entry.get("toggleInitial", "off")).strip().lower()
        if initial not in ("off", "on"):
            raise _schema("toggleInitial must be off or on")
        result["toggleInitial"] = initial
    elif "toggleInitial" in entry:
        raise _schema("toggleInitial is only valid for mode toggle")

    return result


def _validate_action(entry: object) -> dict:
    if not isinstance(entry, dict):
        raise _schema("action entry must be an object")
    action = str(entry.get("action", "")).strip()
    if action not in ACTIONS:
        raise _schema(f"unknown action: {action!r}")
    params = entry.get("params", {})
    if not isinstance(params, dict):
        raise _schema("action params must be an object")
    if action == "switch-to-app":
        process = params.get("process")
        if not isinstance(process, str) or not process:
            raise _schema("switch-to-app requires params.process")
        return {"action": action, "params": {"process": process}}
    if params:
        raise _schema(f"action {action!r} takes no params")
    return {"action": action}


def _validate_zone_mouse(value: object) -> str:
    if value in (None, ""):
        return ""
    if value not in MOUSE_BUTTON_CODES:
        raise RebindError("INVALID_KEY_CODE", f"unknown mouse code: {value!r}")
    return str(value)


def _validate_touchpad(value: object) -> dict:
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise _schema("touchpad must be an object")

    sensitivity = float(value.get("sensitivity", 1.5))
    if not 0.1 <= sensitivity <= 5.0:
        raise _schema("touchpad.sensitivity must be 0.1..5.0")

    split_x = int(value.get("splitX", 960))
    if not 0 <= split_x <= TOUCHPAD_MAX_X:
        raise RebindError("INVALID_SPLIT_X", f"splitX must be 0..{TOUCHPAD_MAX_X}")

    def zones(raw: object) -> dict[str, str]:
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            raise _schema("touchpad zones must be an object")
        return {
            "left": _validate_zone_mouse(raw.get("left")),
            "right": _validate_zone_mouse(raw.get("right")),
        }

    return {
        "mouseControl": bool(value.get("mouseControl", True)),
        "sensitivity": sensitivity,
        "splitX": split_x,
        "tap": zones(value.get("tap")),
        "click": zones(value.get("click")),
    }


def validate_mapping_store(document: object) -> dict:
    if not isinstance(document, dict):
        raise _schema("mapping store must be an object")
    if int(document.get("version", 0)) != MAPPING_VERSION:
        raise _schema(f"unsupported mapping store version: {document.get('version')!r}")

    mappings_in = document.get("mappings", {})
    actions_in = document.get("actions", {})
    if not isinstance(mappings_in, dict) or not isinstance(actions_in, dict):
        raise _schema("mappings and actions must be objects")

    mappings: dict[str, dict] = {}
    for name, entry in mappings_in.items():
        if name not in INPUT_NAMES:
            raise RebindError("UNKNOWN_BUTTON", f"unknown button: {name!r}")
        mappings[name] = _validate_mapping(entry)

    actions: dict[str, dict] = {}
    for name, entry in actions_in.items():
        if name not in INPUT_NAMES:
            raise RebindError("UNKNOWN_BUTTON", f"unknown button: {name!r}")
        if name in mappings:
            raise _schema(f"{name!r} cannot have both a mapping and an action")
        actions[name] = _validate_action(entry)

    return {
        "version": MAPPING_VERSION,
        "enabled": bool(document.get("enabled", True)),
        "mappings": mappings,
        "actions": actions,
        "touchpad": _validate_touchpad(document.get("touchpad")),
    }


def _validate_light(value: object) -> dict:
    if not isinstance(value, dict):
        raise _schema("light entry must be an object")
    color = value.get("color", [0, 0, 0])
    if not isinstance(color, list) or len(color) != 3:
        raise _schema("light color must be [r, g, b]")
    rgb = [_clamp(int(channel), 0, 255) for channel in color]
    effect = str(value.get("effect", "static")).strip().lower()
    if effect not in _EFFECTS:
        raise _schema(f"unknown light effect: {effect!r}")
    speed = _clamp(int(value.get("speed", 3)), 1, 5)
    return {"color": rgb, "effect": effect, "speed": speed}


def validate_settings(document: object) -> dict:
    if not isinstance(document, dict):
        raise _schema("settings must be an object")
    if int(document.get("version", 0)) != SETTINGS_VERSION:
        raise _schema(f"unsupported settings version: {document.get('version')!r}")

    ui_in = document.get("ui", {})
    if not isinstance(ui_in, dict):
        raise _schema("ui must be an object")
    language = str(ui_in.get("language", "zh-Hant"))
    if language not in ("zh-Hant", "en"):
        raise _schema(f"unknown ui.language: {language!r}")
    theme = str(ui_in.get("theme", "dark"))
    if theme not in ("dark", "light"):
        raise _schema(f"unknown ui.theme: {theme!r}")

    logging_in = document.get("logging", {})
    if not isinstance(logging_in, dict):
        raise _schema("logging must be an object")
    level = str(logging_in.get("level", "info"))
    if level not in ("debug", "info", "warning", "error"):
        raise _schema(f"unknown logging.level: {level!r}")

    lighting_in = document.get("lighting", {})
    if not isinstance(lighting_in, dict):
        raise _schema("lighting must be an object")
    mode = str(lighting_in.get("mode", "status"))
    if mode not in ("status", "manual"):
        raise _schema(f"unknown lighting.mode: {mode!r}")
    brightness = _clamp(int(lighting_in.get("brightness", 100)), 0, 100)
    player_leds = _clamp(int(lighting_in.get("playerLeds", 0)), 0, 0x1F)
    status_in = lighting_in.get("status", {})
    if not isinstance(status_in, dict):
        raise _schema("lighting.status must be an object")
    status = {
        state: _validate_light(status_in.get(state, {})) for state in _STATUS_STATES
    }
    manual = _validate_light(lighting_in.get("manual", {}))

    port = int(document.get("port", DEFAULT_PORT))
    if not 1 <= port <= 65535:
        raise _schema("port must be 1..65535")
    autostart_in = document.get("autostart", {})
    if not isinstance(autostart_in, dict):
        raise _schema("autostart must be an object")

    return {
        "version": SETTINGS_VERSION,
        "ui": {"language": language, "theme": theme},
        "logging": {"level": level},
        "lighting": {
            "mode": mode,
            "brightness": brightness,
            "playerLeds": player_leds,
            "muteLedInvert": bool(lighting_in.get("muteLedInvert", False)),
            "status": status,
            "manual": manual,
        },
        "triggers": normalize_triggers(document.get("triggers")),
        "port": port,
        "autostart": {
            "bridge": bool(autostart_in.get("bridge", False)),
            "tray": bool(autostart_in.get("tray", False)),
        },
    }


def atomic_write_text(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` atomically (temp file + os.replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    temp.write_text(text, encoding="utf-8")
    os.replace(temp, path)


def atomic_write_json(path: Path, document: object) -> None:
    atomic_write_text(path, json.dumps(document, ensure_ascii=False, indent=2) + "\n")


def load_or_create_token(path: Path) -> str:
    """Return the bridge token, creating it on first use."""
    if path.exists():
        token = path.read_text(encoding="utf-8").strip()
        if token:
            return token
    token = secrets.token_hex(32)
    atomic_write_text(path, token + "\n")
    return token


class JsonStore:
    """A validated JSON document with atomic writes and a baseVersion lock."""

    def __init__(
        self,
        path: Path,
        validator: Callable[[object], dict],
        default: dict,
    ):
        self.path = path
        self.validator = validator
        self.default = default
        self._lock = threading.RLock()
        self._document: dict = copy.deepcopy(default)
        self._base_version = 1

    def load(self) -> dict:
        """Load from disk; fall back to the preset on missing/invalid data."""
        with self._lock:
            if self.path.exists():
                try:
                    raw = json.loads(self.path.read_text(encoding="utf-8"))
                    document = self.validator(raw)
                    version = int(raw.get("baseVersion", 1))
                except (OSError, ValueError, RebindError):
                    document = self.validator(copy.deepcopy(self.default))
                    version = 1
                    self._document = document
                    self._base_version = version
                    self._write()
                    return self.snapshot()
                self._document = document
                self._base_version = version
            else:
                self._document = self.validator(copy.deepcopy(self.default))
                self._base_version = 1
                self._write()
            return self.snapshot()

    def snapshot(self) -> dict:
        with self._lock:
            document = copy.deepcopy(self._document)
            document["baseVersion"] = self._base_version
            return document

    def replace(self, document: object, base_version: int) -> dict:
        """Replace the document if ``base_version`` matches; else STALE_STORE."""
        with self._lock:
            if base_version != self._base_version:
                raise RebindError(
                    "STALE_STORE",
                    "baseVersion does not match the current document",
                )
            normalized = self.validator(document)
            self._document = normalized
            self._base_version += 1
            self._write()
            return self.snapshot()

    def reset(self) -> dict:
        with self._lock:
            self._document = self.validator(copy.deepcopy(self.default))
            self._base_version = 1
            self._write()
            return self.snapshot()

    def _write(self) -> None:
        document = copy.deepcopy(self._document)
        document["baseVersion"] = self._base_version
        atomic_write_json(self.path, document)


__all__ = [
    "ACTIONS",
    "DEFAULT_CHORD_DELAY_MS",
    "DEFAULT_MAPPING_STORE",
    "DEFAULT_PORT",
    "DEFAULT_REPEAT",
    "DEFAULT_SETTINGS",
    "INPUT_NAMES",
    "JsonStore",
    "MAPPING_STORE_FILENAME",
    "MAPPING_VERSION",
    "SETTINGS_FILENAME",
    "SETTINGS_VERSION",
    "STICK_DIRECTIONS",
    "TOKEN_FILENAME",
    "atomic_write_json",
    "atomic_write_text",
    "load_or_create_token",
    "runtime_dir",
    "validate_mapping_store",
    "validate_settings",
]
