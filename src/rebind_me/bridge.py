"""Bridge runtime: owns the device loop, engine, lighting, triggers and API.

Ties the pieces together. See plan.md §5. Run through ``python -m rebind_me``
or the elevated scheduled task; the tray controls it through the API.
"""

from __future__ import annotations

import ctypes
import threading
import time
from pathlib import Path

from .actions import ActionRunner
from .api import ApiApp, ApiServer
from .engine import MappingEngine, resolve_stick_directions
from .errors import RebindError
from .hid import HidLoop, open_first_device
from .keycapture import KeyCapture
from .lighting import LightingController
from .logsetup import setup_logging
from .protocol import INPUT_REPORT_ID, decode_input_report, encode_output_report
from .store import (
    DEFAULT_MAPPING_STORE,
    DEFAULT_SETTINGS,
    MAPPING_STORE_FILENAME,
    SETTINGS_FILENAME,
    TOKEN_FILENAME,
    JsonStore,
    load_or_create_token,
    runtime_dir,
    validate_mapping_store,
    validate_settings,
)
from .touchpad import TouchpadController
from .winapi.input import SendInputOutput
from .winapi.mutex import BRIDGE_MUTEX, SingleInstance
from .winapi.windows import Windows

OUTPUT_INTERVAL_SECONDS = 1 / 60
PS_IDLE_AUTO_MUTE_SECONDS = 60.0


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
        self._mic_muted = False
        self._mic_led_inverted = False
        self._last_activity_at = 0.0
        self._sessions: dict[str, dict] = {}
        self._status = "idle"
        self._server: ApiServer | None = None

        self._mapping = JsonStore(
            self.root / MAPPING_STORE_FILENAME,
            validate_mapping_store,
            DEFAULT_MAPPING_STORE,
        )
        self._settings = JsonStore(
            self.root / SETTINGS_FILENAME, validate_settings, DEFAULT_SETTINGS
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
            self._start_server()
            self._timer = threading.Thread(target=self._output_loop, name="rebind-output", daemon=True)
            self._timer.start()
            self.hid.start()
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
        if self._log:
            self._log.info("bridge stopped")

    def _load_stores(self) -> None:
        mapping = self._mapping.load()
        self.engine.load(mapping)
        self.touchpad.apply(mapping["touchpad"])
        settings = self._settings.load()
        self.lighting.apply(settings["lighting"])
        self._mic_led_inverted = bool(settings["lighting"]["muteLedInvert"])

    def _start_server(self) -> None:
        settings = self._settings.snapshot()
        port = int(settings.get("port", 4173))
        app = ApiApp(self, self.token, port, Path(__file__).resolve().parent / "ui")
        self._server = ApiServer(app, "127.0.0.1", port)
        threading.Thread(target=self._server.serve_forever, name="rebind-api", daemon=True).start()

    def _port(self) -> int:
        return int(self._settings.snapshot().get("port", 4173))

    # -- device -----------------------------------------------------------
    def _on_device_status(self, state: str, detail: object = None) -> None:
        with self._lock:
            self._device_state = state
        if self._log:
            self._log.info("device %s: %s", state, detail or "")

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
            previous = self._active_inputs
            directions = resolve_stick_directions(
                state.left_x, state.left_y, state.right_x, state.right_y, self._stick_directions
            )
            self._stick_directions = directions
            inputs = set(state.buttons) | directions
            newly_pressed = inputs - previous
            for name in newly_pressed:
                self.engine.press(name, now)
            for name in previous - inputs:
                self.engine.release(name, now)
            self._active_inputs = inputs
            self.engine.tick(now)

            if "mute" in newly_pressed:
                self._mic_muted = not self._mic_muted
                self._last_activity_at = now
            if "ps" in newly_pressed:
                self._mic_muted = False
                self._last_activity_at = now
            if (
                not self._mic_muted
                and PS_IDLE_AUTO_MUTE_SECONDS > 0
                and self._last_activity_at
                and now - self._last_activity_at > PS_IDLE_AUTO_MUTE_SECONDS
            ):
                self._mic_muted = True

        self.touchpad.update(state.touch, "touchpad" in inputs, now, self.output)

    # -- output -----------------------------------------------------------
    def _current_mapping(self) -> dict:
        with self._lock:
            return self._mapping.snapshot()

    def _write_output(self, zero_motors: bool = False) -> None:
        settings = self._settings.snapshot()
        frame = self.lighting.frame(time.monotonic())
        triggers = settings["triggers"]
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
            return list(self._sessions.values())

    def _toggle_mouse_mode(self) -> None:
        with self._lock:
            document = self._mapping.snapshot()
            touchpad = dict(document["touchpad"])
            touchpad["mouseControl"] = not touchpad["mouseControl"]
            document["touchpad"] = touchpad
            result = self._mapping.replace(document, document["baseVersion"])
            self.touchpad.apply(result["touchpad"])

    def _open_ui(self) -> None:
        import webbrowser

        webbrowser.open(f"http://127.0.0.1:{self._port()}/")

    # -- API backend ------------------------------------------------------
    def status(self) -> dict:
        with self._lock:
            return {
                "running": True,
                "device": self._device_state,
                "enabled": self._mapping.snapshot()["enabled"],
                "status": self._status,
                "mouseControl": self._mapping.snapshot()["touchpad"]["mouseControl"],
                "port": self._port(),
            }

    def get_mapping(self) -> dict:
        return self._mapping.snapshot()

    def put_mapping(self, document: dict, base_version: int) -> dict:
        with self._lock:
            result = self._mapping.replace(document, base_version)
            self.engine.load(result)
            self.touchpad.apply(result["touchpad"])
            return result

    def get_lighting(self) -> dict:
        settings = self._settings.snapshot()
        return dict(settings["lighting"], baseVersion=settings["baseVersion"])

    def put_lighting(self, document: dict, base_version: int) -> dict:
        settings = self._settings.snapshot()
        settings["lighting"] = document
        result = self._settings.replace(settings, base_version)
        self.lighting.apply(result["lighting"])
        self._mic_led_inverted = bool(result["lighting"]["muteLedInvert"])
        return dict(result["lighting"], baseVersion=result["baseVersion"])

    def get_triggers(self) -> dict:
        settings = self._settings.snapshot()
        return dict(settings["triggers"], baseVersion=settings["baseVersion"])

    def put_triggers(self, document: dict, base_version: int) -> dict:
        settings = self._settings.snapshot()
        settings["triggers"] = document
        result = self._settings.replace(settings, base_version)
        return dict(result["triggers"], baseVersion=result["baseVersion"])

    def get_settings(self) -> dict:
        return self._settings.snapshot()

    def put_settings(self, document: dict, base_version: int) -> dict:
        result = self._settings.replace(document, base_version)
        self.lighting.apply(result["lighting"])
        self._mic_led_inverted = bool(result["lighting"]["muteLedInvert"])
        return result

    def autostart(self, body: dict) -> dict:
        settings = self._settings.snapshot()
        desired = {
            "bridge": bool(body.get("bridge", settings["autostart"]["bridge"])),
            "tray": bool(body.get("tray", settings["autostart"]["tray"])),
        }
        settings["autostart"] = desired
        self._settings.replace(settings, settings["baseVersion"])
        # TODO(stage 5): create/delete the scheduled task and HKCU Run entry.
        return desired

    def key_capture(self) -> dict:
        with self._lock:
            if getattr(self, "_capturing", False):
                raise RebindError("CAPTURE_IN_PROGRESS", "another capture is running", 409)
            self._capturing = True
        try:
            return self._key_capture.capture()
        finally:
            self._capturing = False

    def focus_terminal(self, body: dict) -> dict:
        return self.actions.run("api", "focus-terminal", body)

    def scan_windows(self) -> list:
        return self.windows.list_windows()

    def sessions(self, body: dict) -> dict:
        session_id = str(body.get("id", ""))
        if not session_id:
            raise RebindError("SCHEMA_ERROR", "session id is required")
        with self._lock:
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
