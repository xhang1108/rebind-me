"""Bridge runtime: owns the device loop, engine, lighting, triggers and API.

Ties the pieces together. Run through ``python -m rebind_me``
or the elevated scheduled task; the tray controls it through the API.
"""

from __future__ import annotations

import ctypes
import os
import threading
import time
from pathlib import Path

from .actions import ActionRunner
from .api import ApiApp, ApiServer
from .autostart import AutostartController
from .engine import MappingEngine, resolve_stick_directions
from .errors import RebindError
from .hid import HidLoop, open_first_device
from .keycapture import KeyCapture
from .lighting import LightingController
from .logsetup import setup_logging
from .opencode_plugin import OpenCodePluginInstaller
from .protocol import INPUT_REPORT_ID, decode_input_report, encode_output_report
from .store import (
    DEFAULT_MAPPING_STORE,
    DEFAULT_PORT,
    DEFAULT_PRESETS,
    DEFAULT_SETTINGS,
    MAPPING_STORE_FILENAME,
    MAPPING_VERSION,
    PRESETS_FILENAME,
    SETTINGS_FILENAME,
    TOKEN_FILENAME,
    JsonStore,
    load_or_create_token,
    runtime_dir,
    validate_mapping_store,
    validate_presets,
    validate_settings,
)
from .touchpad import TouchpadController
from .winapi.input import SendInputOutput
from .winapi.mutex import BRIDGE_MUTEX, SingleInstance
from .winapi.windows import Windows

OUTPUT_INTERVAL_SECONDS = 1 / 60
UI_ACTIVE_TIMEOUT_SECONDS = 1.5
SESSION_TTL_SECONDS = 300.0

# Touchpad gesture -> the mapping / action name the engine resolves it under.
TOUCHPAD_GESTURES = {
    ("tap", "left"): "touchpad_tap_left",
    ("tap", "right"): "touchpad_tap_right",
    ("click-down", "left"): "touchpad_click_left",
    ("click-down", "right"): "touchpad_click_right",
    ("click-up", "left"): "touchpad_click_left",
    ("click-up", "right"): "touchpad_click_right",
}


class Bridge:
    def __init__(self, root: Path | None = None):
        self.root = root or runtime_dir()
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._log = None
        self._device_state = "disconnected"
        self._device = None
        self._stick_directions: set[str] = set()
        self._active_inputs: set[str] = set()
        self._touchpad_zone: str | None = None
        self._touchpad_click: bool = False
        self._trigger_level: dict[str, float] = {"left": 0.0, "right": 0.0}
        self._axes = {"leftX": 0.0, "leftY": 0.0, "rightX": 0.0, "rightY": 0.0}
        self._mic_muted = False
        self._mic_led_inverted = False
        self._auto_mute_seconds = 60
        self._mic_button = ""
        self._mic_button_mode = "push"
        # Cached, validated settings slices read on the output thread. Only the
        # API handlers replace them, so no deepcopy is needed per frame.
        self._triggers = DEFAULT_SETTINGS["triggers"]
        self._last_activity_at = 0.0
        self._ui_active = False
        self._ui_last_seen = 0.0
        self._sessions: dict[str, dict] = {}
        self._status = "idle"
        self._capturing = False
        self._server: ApiServer | None = None
        self._port_number = DEFAULT_PORT
        self._started_at = time.monotonic()

        self._mapping = JsonStore(
            self.root / MAPPING_STORE_FILENAME,
            validate_mapping_store,
            DEFAULT_MAPPING_STORE,
        )
        self._settings = JsonStore(
            self.root / SETTINGS_FILENAME, validate_settings, DEFAULT_SETTINGS
        )
        self._presets = JsonStore(
            self.root / PRESETS_FILENAME, validate_presets, DEFAULT_PRESETS
        )
        self.token = ""
        self.output = SendInputOutput()
        self.engine = MappingEngine(self.output, action_handler=self._run_action)
        self.touchpad = TouchpadController(DEFAULT_MAPPING_STORE["touchpad"])
        self.lighting = LightingController(DEFAULT_SETTINGS["lighting"])
        self.windows = Windows()
        self.actions = ActionRunner(
            self.windows,
            sessions_provider=self._session_list,
            toggle_mouse_mode=self._toggle_mouse_mode,
            open_ui=self._open_ui,
        )
        self._key_capture = KeyCapture()
        self._autostart = AutostartController()
        self._plugin = OpenCodePluginInstaller()
        self.hid = HidLoop(open_first_device, self._on_report, self._on_device_status)
        self._timer = None

    # -- lifecycle --------------------------------------------------------
    def run(self) -> int:
        instance = SingleInstance(BRIDGE_MUTEX)
        if not instance.acquire():
            return 1
        try:
            self._log = setup_logging(self.root / "logs", "info")
            self.token = load_or_create_token(self.root / TOKEN_FILENAME)
            self._load_stores()
            try:
                self._start_server()
            except OSError as error:
                # Keep the hardware loop alive if the port is already taken;
                # only the API is unavailable until the next settings change.
                self._server = None
                self._log.warning("failed to bind API on port %s: %s", self._port(), error)
            self._timer = threading.Thread(target=self._output_loop, name="rebind-output", daemon=True)
            self._timer.start()
            self.hid.start()
            self._started_at = time.monotonic()
            self._log.info("bridge started on port %s", self._port())
            self._stop.wait()
            return 0
        finally:
            self._shutdown()
            instance.release()

    def stop(self) -> None:
        self._stop.set()

    def _shutdown(self) -> None:
        self._stop.set()
        if self._timer is not None:
            self._timer.join(1.0)
        self.engine.release_all()
        self._write_output(zero_motors=True)
        self.hid.stop()
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._log:
            self._log.info("bridge stopped")

    def _load_stores(self) -> None:
        self._apply_mapping(self._mapping.load())
        settings = self._settings.load()
        self._apply_lighting(settings["lighting"])
        self._triggers = settings["triggers"]
        self._presets.load()

    def _apply_mapping(self, document: dict) -> None:
        """Point the engine and touchpad at a validated mapping document."""
        self.engine.load(document)
        self.touchpad.apply(document["touchpad"])

    def _apply_lighting(self, lighting: dict) -> None:
        """Point the lighting controller and mic LED state at a validated doc."""
        self.lighting.apply(lighting)
        self._mic_led_inverted = bool(lighting["muteLedInvert"])
        self._auto_mute_seconds = int(lighting["autoMuteSeconds"])
        previous_button = self._mic_button
        self._mic_button = str(lighting.get("micButton", "") or "")
        self._mic_button_mode = str(lighting.get("micButtonMode", "push") or "push")
        if self._mic_button and self._mic_button != previous_button:
            # Start muted the moment a talk button is assigned; the first press
            # is what makes it live.
            self._mic_muted = True

    def _start_server(self, port: int | None = None) -> None:
        if port is None:
            port = int(self._settings.snapshot().get("port", DEFAULT_PORT))
        self._port_number = int(port)
        app = ApiApp(self, self.token, self._port_number, Path(__file__).resolve().parent / "ui")
        server = ApiServer(app, "127.0.0.1", self._port_number)
        # Bind synchronously so a taken port surfaces here instead of on the
        # serving thread, where it would only be logged.
        server.bind()
        self._server = server
        threading.Thread(target=server.serve_forever, name="rebind-api", daemon=True).start()

    def _restart_server(self, port: int) -> None:
        """Rebind the API on ``port``, restoring the old port on bind failure."""
        old = self._server
        old_port = self._port_number
        if old is not None:
            old.shutdown()
            old.server_close()
        self._server = None
        try:
            self._start_server(port)
        except OSError as error:
            if self._log:
                self._log.warning("failed to bind API on port %s: %s", port, error)
            try:
                self._start_server(old_port)
            except OSError:
                if self._log:
                    self._log.warning("failed to restore API on port %s", old_port)

    def _port(self) -> int:
        return self._port_number

    # -- device -----------------------------------------------------------
    def _on_device_status(self, state: str, detail: object = None) -> None:
        with self._lock:
            self._device_state = state
            if state != "connected":
                # A disconnect must not leave injected keys or mouse buttons
                # held down; release everything and forget the
                # pressed set so the next report starts clean.
                self.engine.release_all()
                self.touchpad.reset()
                self._active_inputs.clear()
                self._stick_directions.clear()
                self._touchpad_zone = None
                self._touchpad_click = False
                self._trigger_level = {"left": 0.0, "right": 0.0}
        if self._log:
            msg = str(detail or "")
            if hasattr(detail, "occupant") and detail.occupant:
                msg += f" (Occupant: {detail.occupant})"
            if hasattr(detail, "conflicts") and detail.conflicts:
                msg += f" (Conflicting apps: {detail.conflicts})"
            self._log.info("device %s: %s", state, msg)

    def _on_report(self, report: bytes, device: object) -> None:
        self._device = device
        if not report or report[0] != INPUT_REPORT_ID:
            return
        try:
            state = decode_input_report(report)
        except ValueError:
            return

        now = time.monotonic()
        with self._lock:
            self._axes = {
                "leftX": state.left_x,
                "leftY": state.left_y,
                "rightX": state.right_x,
                "rightY": state.right_y,
            }
            previous = self._active_inputs
            directions = resolve_stick_directions(
                state.left_x, state.left_y, state.right_x, state.right_y, self._stick_directions
            )
            self._stick_directions = directions
            inputs = set(state.buttons) | directions
            newly_pressed = inputs - previous
            self._active_inputs = inputs
            # Track which half of the touchpad is currently active so the UI can
            # light the matching side; keep the last side while the button is
            # held without an active contact.
            self._touchpad_zone = (
                self.touchpad.zone(state.touch.x)
                if state.touch is not None
                else (self._touchpad_zone if "touchpad" in state.buttons else None)
            )
            self._touchpad_click = "touchpad" in state.buttons
            self._trigger_level = {"left": state.left_trigger, "right": state.right_trigger}
            # The mic button is a fixed hardware control, not a mapping: it
            # toggles regardless of the mapping switch. When a mic button is
            # configured it drives the mic instead: hold to talk, or tap to
            # latch, depending on the configured mode.
            if "mute" in newly_pressed:
                self._mic_muted = not self._mic_muted
                self._last_activity_at = now
            if self._mic_button:
                if self._mic_button_mode == "toggle":
                    if self._mic_button in newly_pressed:
                        self._mic_muted = not self._mic_muted
                else:
                    self._mic_muted = self._mic_button not in inputs
            blocked = self._ui_blocks_input(now)
            if not blocked:
                for name in newly_pressed:
                    self.engine.press(name, now)
                for name in previous - inputs:
                    self.engine.release(name, now)
                self.engine.tick(now)

            # Tap and click are resolved through the engine, so they support
            # the same modes, chords and actions as any other mapping.
            events = self.touchpad.update(
                state.touch, "touchpad" in state.buttons, now, self.output
            )
            if not blocked:
                for kind, zone in events:
                    self._apply_touchpad_gesture(kind, zone, now)

            if newly_pressed:
                self._last_activity_at = now
            self._maybe_auto_mute(now)

    def _maybe_auto_mute(self, now: float) -> None:
        """Mute the mic once the controller has been idle for long enough."""
        if self._mic_button:
            # A configured mic button owns the state; the timer must not fight it.
            return
        if (
            not self._mic_muted
            and self._auto_mute_seconds > 0
            and self._last_activity_at
            and now - self._last_activity_at > self._auto_mute_seconds
        ):
            self._mic_muted = True

    def _ui_blocks_input(self, now: float) -> bool:
        """True while the config UI page holds the user's focus.

        The page reports ``active`` on focus and on a heartbeat, and reports
        ``active: false`` the moment it loses focus. The heartbeat timeout is a
        safety net: if a tab is closed without a final report, mappings resume
        within :data:`UI_ACTIVE_TIMEOUT_SECONDS` instead of wedging forever.
        """
        if not self._ui_active:
            return False
        if now - self._ui_last_seen > UI_ACTIVE_TIMEOUT_SECONDS:
            self._ui_active = False
            self.engine.release_all()
            return False
        return True

    def _apply_touchpad_gesture(self, kind: str, zone: str, now: float) -> None:
        """Resolve one touchpad gesture through the mapping engine.

        A tap is momentary: press then release, so ``single``, ``hold`` and
        ``repeat`` all fire once. A click reports both edges, letting a ``hold``
        mapping track the physical touchpad button.
        """
        name = TOUCHPAD_GESTURES.get((kind, zone))
        if name is None:
            return
        if kind == "tap":
            self.engine.press(name, now)
            self.engine.release(name, now)
        elif kind == "click-down":
            self.engine.press(name, now)
        else:
            self.engine.release(name, now)

    # -- output -----------------------------------------------------------
    def _write_output(self, zero_motors: bool = False) -> None:
        frame = self.lighting.frame(time.monotonic())
        triggers = self._triggers
        report = encode_output_report(
            lightbar=(frame.red, frame.green, frame.blue),
            brightness=frame.brightness,
            player_leds=frame.player_leds,
            mic_muted=self._mic_muted,
            mic_led_inverted=self._mic_led_inverted,
            triggers=triggers if not zero_motors else {
                "left": {"mode": "off"},
                "right": {"mode": "off"},
            },
            zero_motors=zero_motors,
        )
        try:
            self.hid.write(report)
        except RebindError:
            pass

    def _output_loop(self) -> None:
        try:
            ctypes.WinDLL("winmm").timeBeginPeriod(1)
        except (AttributeError, OSError):
            pass
        try:
            while not self._stop.is_set():
                self._write_output()
                self._stop.wait(OUTPUT_INTERVAL_SECONDS)
        finally:
            try:
                ctypes.WinDLL("winmm").timeEndPeriod(1)
            except (AttributeError, OSError):
                pass

    # -- actions ----------------------------------------------------------
    def _run_action(self, name: str, action: str, params: dict) -> None:
        try:
            self.actions.run(name, action, params)
        except RebindError as error:
            if self._log:
                self._log.warning("action %s failed: %s", action, error.message)

    def _session_list(self) -> list[dict]:
        with self._lock:
            self._prune_sessions()
            return list(self._sessions.values())

    def _prune_sessions(self) -> bool:
        """Drop sessions that have not reported within the TTL (called under lock)."""
        now = time.time()
        expired = [
            session_id
            for session_id, session in self._sessions.items()
            if now - float(session.get("lastActive", 0) or 0) > SESSION_TTL_SECONDS
        ]
        for session_id in expired:
            self._sessions.pop(session_id, None)
        return bool(expired)

    def _toggle_mouse_mode(self) -> None:
        with self._lock:
            document = self._mapping.snapshot()
            touchpad = dict(document["touchpad"])
            touchpad["mouseControl"] = not touchpad["mouseControl"]
            document["touchpad"] = touchpad
            result = self._mapping.replace(document, document["baseVersion"])
            self.touchpad.apply(result["touchpad"])

    def get_mic(self) -> dict:
        with self._lock:
            return {
                "muted": self._mic_muted,
                "autoMuteSeconds": self._auto_mute_seconds,
                "micButton": self._mic_button,
                "micButtonMode": self._mic_button_mode,
            }

    def put_mic(self, body: dict) -> dict:
        with self._lock:
            muted = body.get("muted")
            self._mic_muted = (not self._mic_muted) if muted is None else bool(muted)
            self._last_activity_at = time.monotonic()
            return {"muted": self._mic_muted}

    def _open_ui(self) -> None:
        import webbrowser

        webbrowser.open(f"http://127.0.0.1:{self._port()}/")

    # -- API backend ------------------------------------------------------
    def status(self) -> dict:
        with self._lock:
            if self._prune_sessions():
                self._update_lighting_status()
            mapping = self._mapping.snapshot()
            return {
                "running": True,
                "device": self._device_state,
                "enabled": mapping["enabled"],
                "status": self._status,
                "mouseControl": mapping["touchpad"]["mouseControl"],
                "port": self._port(),
                "inputs": sorted(self._active_inputs),
                "axes": dict(self._axes),
                "touchpadZone": self._touchpad_zone,
                "touchpadClick": self._touchpad_click,
                "triggerLevel": dict(self._trigger_level),
                "micMuted": self._mic_muted,
                "micButton": self._mic_button,
                "micButtonMode": self._mic_button_mode,
                "uiActive": self._ui_active,
                "pid": os.getpid(),
                "uptime": round(max(0.0, time.monotonic() - self._started_at), 1),
            }

    def ui_active(self, body: dict) -> dict:
        """The config UI reports whether it currently holds focus. While it does,
        button mappings are suppressed so the page cannot be driven by the keys
        it maps; releasing focus resumes them immediately."""
        active = bool(body.get("active", True))
        with self._lock:
            changed = active != self._ui_active
            self._ui_active = active
            if active:
                self._ui_last_seen = time.monotonic()
            if changed:
                self.engine.release_all()
        return {"active": active}

    def get_mapping(self) -> dict:
        return self._mapping.snapshot()

    def put_mapping(self, document: dict, base_version: int) -> dict:
        with self._lock:
            result = self._mapping.replace(document, base_version)
            self._apply_mapping(result)
            return result

    def get_presets(self) -> dict:
        return self._presets.snapshot()

    def put_preset(self, body: dict) -> dict:
        """Save, apply or delete a named mapping preset.

        ``save`` snapshots the current mapping document under ``name``;
        ``apply`` replaces the mapping document with the stored snapshot;
        ``delete`` removes it. Applying returns the new mapping snapshot too.
        """
        action = str(body.get("action") or "save").strip().lower()
        if action not in ("save", "apply", "delete"):
            raise RebindError("SCHEMA_ERROR", f"unknown preset action: {action!r}")
        name = str(body.get("name") or "").strip()

        with self._lock:
            document = self._presets.snapshot()
            presets = dict(document["presets"])

            if action == "save":
                if not name:
                    raise RebindError("SCHEMA_ERROR", "preset name is required")
                mapping = self._mapping.snapshot()
                presets[name] = {
                    "enabled": mapping["enabled"],
                    "mappings": mapping["mappings"],
                    "actions": mapping["actions"],
                    "touchpad": mapping["touchpad"],
                }
                document["presets"] = presets
                return {
                    "action": action,
                    "presets": self._presets.replace(document, document["baseVersion"]),
                }

            preset = presets.get(name)
            if preset is None:
                raise RebindError("UNKNOWN_PRESET", f"unknown preset: {name!r}")

            if action == "apply":
                mapping = self._mapping.snapshot()
                result = self._mapping.replace(
                    {
                        "version": MAPPING_VERSION,
                        "enabled": preset["enabled"],
                        "mappings": preset["mappings"],
                        "actions": preset["actions"],
                        "touchpad": preset["touchpad"],
                    },
                    mapping["baseVersion"],
                )
                self._apply_mapping(result)
                return {
                    "action": action,
                    "mapping": result,
                    "presets": self._presets.snapshot(),
                }

            del presets[name]
            document["presets"] = presets
            return {
                "action": action,
                "presets": self._presets.replace(document, document["baseVersion"]),
            }

    def get_settings(self) -> dict:
        return self._settings.snapshot()

    def put_settings(self, document: dict, base_version: int) -> dict:
        before = self._settings.snapshot().get("autostart", {})
        result = self._settings.replace(document, base_version)
        self._apply_lighting(result["lighting"])
        self._triggers = result["triggers"]
        desired = result["autostart"]
        if desired != before:
            # The scheduled task and Run entry are expensive to touch, so only
            # re-apply autostart when the document actually changed it.
            try:
                self._autostart.apply(desired["bridge"], desired["tray"])
            except (RebindError, OSError) as error:
                if self._log:
                    self._log.warning("autostart update failed: %s", error)
        port = int(result["port"])
        if port != self._port_number:
            # Restart off the request thread so this response is delivered
            # before the old listening socket is closed.
            threading.Thread(
                target=self._restart_server,
                args=(port,),
                name="rebind-api-restart",
                daemon=True,
            ).start()
        return result

    def autostart(self, body: dict) -> dict:
        settings = self._settings.snapshot()
        desired = {
            "bridge": bool(body.get("bridge", settings["autostart"]["bridge"])),
            "tray": bool(body.get("tray", settings["autostart"]["tray"])),
        }
        settings["autostart"] = desired
        result = self._settings.replace(settings, settings["baseVersion"])
        self._triggers = result["triggers"]
        try:
            result = self._autostart.apply(desired["bridge"], desired["tray"])
        except (RebindError, OSError) as error:
            if self._log:
                self._log.warning("autostart update failed: %s", error)
            return dict(desired, applied=False)
        return dict(result, applied=True)

    def plugin(self, body: dict) -> dict:
        """Report, install or remove the opencode plugin integration."""
        action = str(body.get("action") or "").lower()
        if action not in ("", "status", "install", "uninstall"):
            raise RebindError("SCHEMA_ERROR", "unknown plugin action")
        try:
            if action == "install":
                mode = body.get("mode")
                return self._plugin.install(mode if mode in ("npm", "local") else None)
            if action == "uninstall":
                return self._plugin.uninstall()
            return self._plugin.status()
        except OSError as error:
            raise RebindError("INTERNAL_ERROR", f"plugin {action or 'status'} failed: {error}") from error

    def key_capture(self) -> dict:
        with self._lock:
            if self._capturing:
                raise RebindError("CAPTURE_IN_PROGRESS", "another capture is running", 409)
            self._capturing = True
        try:
            return self._key_capture.capture()
        finally:
            self._capturing = False

    def cancel_key_capture(self) -> dict:
        return self._key_capture.cancel()

    def focus_terminal(self, body: dict) -> dict:
        return self.actions.run("api", "focus-terminal", body)

    def scan_windows(self) -> list:
        return self.windows.list_windows()

    def sessions(self, body: dict) -> dict:
        session_id = str(body.get("id", ""))
        if not session_id:
            raise RebindError("SCHEMA_ERROR", "session id is required")
        with self._lock:
            if body.get("deleted"):
                self._sessions.pop(session_id, None)
            else:
                self._sessions[session_id] = {
                    "id": session_id,
                    "status": body.get("status", ""),
                    "pid": body.get("pid"),
                    "title": body.get("title", ""),
                    "lastActive": body.get("lastActive", time.time()),
                }
            self._update_lighting_status()
        return {"accepted": True}

    def _update_lighting_status(self) -> None:
        self._prune_sessions()
        statuses = {str(session.get("status", "")).lower() for session in self._sessions.values()}
        if "error" in statuses:
            state = "error"
        elif "approval" in statuses:
            state = "approval"
        elif statuses & {"working", "busy"}:
            state = "working"
        else:
            state = "idle"
        self._status = state
        self.lighting.set_status(state)

    def shutdown(self) -> dict:
        threading.Thread(target=self.stop, daemon=True).start()
        return {"stopping": True}


__all__ = ["Bridge"]
