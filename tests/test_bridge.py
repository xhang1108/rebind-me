"""Integration tests for the bridge controller with fakes (no hardware)."""

import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from rebind_me.bridge import Bridge
from rebind_me.errors import RebindError
from rebind_me.keycapture import KeyCapture
from rebind_me.keys import VK_CODES
from rebind_me.store import DEFAULT_MAPPING_STORE, DEFAULT_SETTINGS


class FakeOutput:
    def __init__(self) -> None:
        self.events: list[tuple] = []

    def key_down(self, code):
        self.events.append(("down", code))

    def key_up(self, code):
        self.events.append(("up", code))

    def scroll(self, code):
        self.events.append(("scroll", code))

    def mouse_move(self, dx, dy):
        self.events.append(("move", dx, dy))


class FakeHid:
    def __init__(self) -> None:
        self.writes: list[bytes] = []

    def write(self, data):
        self.writes.append(bytes(data))

    def start(self):
        pass

    def stop(self, timeout=2.0):
        pass


def input_report(face=0x08, system=0x00, misc=0x00) -> bytes:
    report = bytearray(64)
    report[0] = 0x01
    for offset in (1, 2, 3, 4):
        report[offset] = 128
    report[8] = face
    report[9] = misc
    report[10] = system
    return bytes(report)


def mapping_doc(mappings, actions=None, enabled=True) -> dict:
    document = json.loads(json.dumps(DEFAULT_MAPPING_STORE))
    document["mappings"] = mappings
    document["actions"] = actions or {}
    document["enabled"] = enabled
    return document


class BridgeTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.bridge = Bridge(root=Path(self._tmp.name))
        self.output = FakeOutput()
        self.hid = FakeHid()
        self.bridge.output = self.output
        self.bridge.engine.output = self.output
        self.bridge.hid = self.hid
        self.bridge._load_stores()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def put_section(self, section: str, value) -> dict:
        """Update one settings section through the whole-document route."""
        current = self.bridge.get_settings()
        document = {key: item for key, item in current.items() if key != "baseVersion"}
        document[section] = value
        return self.bridge.put_settings(document, current["baseVersion"])

    def test_status_defaults(self) -> None:
        status = self.bridge.status()
        self.assertTrue(status["running"])
        self.assertEqual(status["device"], "disconnected")
        self.assertEqual(status["inputs"], [])
        self.assertEqual(status["pid"], os.getpid())
        self.assertGreaterEqual(status["uptime"], 0.0)

    def test_status_reports_pressed_inputs(self) -> None:
        self.bridge._on_report(input_report(face=0x28), None)  # cross held
        self.assertIn("cross", self.bridge.status()["inputs"])
        self.bridge._on_report(input_report(face=0x08), None)
        self.assertEqual(self.bridge.status()["inputs"], [])

    def test_status_reports_touchpad_zone(self) -> None:
        left = bytearray(input_report(system=0x02))
        left[33] = 0x00  # active contact
        left[34] = 0x00  # x low
        left[35] = 0x00  # x high nibble 0 -> x < 960 (left)
        left[36] = 0x00
        self.bridge._on_report(bytes(left), None)
        self.assertEqual(self.bridge.status()["touchpadZone"], "left")
        self.assertTrue(self.bridge.status()["touchpadClick"])

        # Touch without the button pressed reports a zone but no click.
        touched = bytearray(input_report(system=0x00))
        touched[33] = 0x00
        touched[34] = 0x00
        touched[35] = 0x0F  # right side
        touched[36] = 0x00
        self.bridge._on_report(bytes(touched), None)
        self.assertEqual(self.bridge.status()["touchpadZone"], "right")
        self.assertFalse(self.bridge.status()["touchpadClick"])

        # Releasing the contact (inactive touch bits) with the button up clears.
        released = bytearray(input_report())
        released[33] = 0x80  # first slot inactive
        released[37] = 0x80  # second slot inactive
        self.bridge._on_report(bytes(released), None)
        self.assertIsNone(self.bridge.status()["touchpadZone"])
        self.assertFalse(self.bridge.status()["touchpadClick"])

    def test_touchpad_tap_drives_the_zone_mapping(self) -> None:
        touch_down = bytearray(input_report())
        touch_down[33] = 0x00  # active contact
        touch_down[35] = 0x00  # left half
        self.bridge._on_report(bytes(touch_down), None)
        released = bytearray(input_report())
        released[33] = 0x80  # contact gone
        released[37] = 0x80
        self.bridge._on_report(bytes(released), None)
        self.assertIn(("down", "MouseLeft"), self.output.events)
        self.assertIn(("up", "MouseLeft"), self.output.events)

    def test_touchpad_click_drives_the_zone_mapping(self) -> None:
        press = bytearray(input_report(system=0x02))
        press[33] = 0x00
        press[35] = 0x0F  # right half
        self.bridge._on_report(bytes(press), None)
        self.assertIn(("down", "MouseRight"), self.output.events)
        self.assertIn(("up", "MouseRight"), self.output.events)

    def test_status_reports_axes_and_trigger_level(self) -> None:
        report = bytearray(input_report())
        report[1] = 255  # left stick fully right -> ~+1.0
        report[5] = 255  # left trigger fully pressed
        report[6] = 128  # right trigger half pressed
        self.bridge._on_report(bytes(report), None)
        status = self.bridge.status()
        self.assertAlmostEqual(status["axes"]["leftX"], 1.0, places=2)
        self.assertAlmostEqual(status["triggerLevel"]["left"], 1.0, places=2)
        self.assertAlmostEqual(status["triggerLevel"]["right"], 0.5, places=2)

        # Idle clears the trigger levels.
        idle = bytearray(input_report())
        idle[33] = 0x80
        idle[37] = 0x80
        self.bridge._on_report(bytes(idle), None)
        self.assertEqual(self.bridge.status()["triggerLevel"], {"left": 0.0, "right": 0.0})

    def test_mute_button_toggles_mic(self) -> None:
        self.assertFalse(self.bridge.status()["micMuted"])
        self.bridge._on_report(input_report(system=0x04), None)
        self.assertTrue(self.bridge.status()["micMuted"])
        self.bridge._on_report(input_report(system=0x00), None)
        self.bridge._on_report(input_report(system=0x04), None)
        self.assertFalse(self.bridge.status()["micMuted"])

    def test_mute_works_while_the_ui_blocks_mappings(self) -> None:
        document = mapping_doc({"cross": {"mode": "single", "sequence": [["KeyK"]]}})
        self.bridge.put_mapping(document, 1)
        self.bridge.ui_active({"active": True})
        self.bridge._on_report(input_report(system=0x04), None)
        self.assertTrue(self.bridge.status()["micMuted"])
        cross = input_report(face=0x28, system=0x00)
        self.bridge._on_report(cross, None)
        self.assertEqual([event for event in self.output.events if event[1] == "KeyK"], [])

    def test_mic_auto_mutes_when_idle(self) -> None:
        self.bridge._auto_mute_seconds = 10
        self.bridge._mic_muted = False
        self.bridge._last_activity_at = time.monotonic() - 20
        self.bridge._on_report(input_report(), None)
        self.assertTrue(self.bridge.status()["micMuted"])

    def test_mic_endpoint_reports_and_toggles(self) -> None:
        self.assertEqual(
            self.bridge.get_mic(),
            {"muted": False, "autoMuteSeconds": 60, "micButton": "", "micButtonMode": "push"},
        )
        self.assertEqual(self.bridge.put_mic({}), {"muted": True})
        self.assertEqual(self.bridge.put_mic({}), {"muted": False})
        self.assertEqual(self.bridge.put_mic({"muted": True}), {"muted": True})
        self.assertEqual(self.bridge.status()["micMuted"], True)

    def test_mic_auto_mute_disabled(self) -> None:
        self.bridge._auto_mute_seconds = 0
        self.bridge._mic_muted = False
        self.bridge._last_activity_at = time.monotonic() - 20
        self.bridge._on_report(input_report(), None)
        self.assertFalse(self.bridge.status()["micMuted"])

    def test_mic_button_pushes_to_talk(self) -> None:
        lighting = json.loads(json.dumps(DEFAULT_SETTINGS["lighting"]))
        lighting["micButton"] = "ps"
        self.put_section("lighting", lighting)
        self.assertTrue(self.bridge.status()["micMuted"])  # starts muted
        self.bridge._on_report(input_report(system=0x00), None)  # ps up
        self.assertTrue(self.bridge.status()["micMuted"])
        self.bridge._on_report(input_report(system=0x01), None)  # ps held
        self.assertFalse(self.bridge.status()["micMuted"])
        self.bridge._on_report(input_report(system=0x00), None)  # ps released
        self.assertTrue(self.bridge.status()["micMuted"])

    def test_mic_button_tap_to_toggle(self) -> None:
        lighting = json.loads(json.dumps(DEFAULT_SETTINGS["lighting"]))
        lighting["micButton"] = "ps"
        lighting["micButtonMode"] = "toggle"
        self.put_section("lighting", lighting)
        self.bridge._on_report(input_report(system=0x00), None)
        self.assertTrue(self.bridge.status()["micMuted"])
        self.bridge._on_report(input_report(system=0x01), None)  # tap -> live
        self.assertFalse(self.bridge.status()["micMuted"])
        self.bridge._on_report(input_report(system=0x00), None)  # release -> stays live
        self.assertFalse(self.bridge.status()["micMuted"])
        self.bridge._on_report(input_report(system=0x01), None)  # tap -> muted
        self.assertTrue(self.bridge.status()["micMuted"])
        self.bridge._on_report(input_report(system=0x00), None)  # release -> stays muted
        self.assertTrue(self.bridge.status()["micMuted"])

    def test_mic_button_overrides_auto_mute(self) -> None:
        lighting = json.loads(json.dumps(DEFAULT_SETTINGS["lighting"]))
        lighting["micButton"] = "ps"
        self.put_section("lighting", lighting)
        self.bridge._auto_mute_seconds = 10
        self.bridge._last_activity_at = time.monotonic() - 20
        self.bridge._on_report(input_report(system=0x01), None)
        self.bridge._maybe_auto_mute(time.monotonic())
        self.assertFalse(self.bridge.status()["micMuted"])

    def test_input_activity_defers_auto_mute(self) -> None:
        self.bridge._auto_mute_seconds = 10
        self.bridge._mic_muted = False
        self.bridge._last_activity_at = time.monotonic() - 20
        self.bridge._on_report(input_report(face=0x28), None)  # cross press
        self.assertFalse(self.bridge.status()["micMuted"])

    def test_put_mapping_round_trip(self) -> None:
        document = mapping_doc({"cross": {"mode": "single", "sequence": [["KeyK"]]}})
        result = self.bridge.put_mapping(document, 1)
        self.assertEqual(result["baseVersion"], 2)
        self.assertEqual(self.bridge.get_mapping()["mappings"]["cross"]["mode"], "single")

    def test_stale_mapping_version(self) -> None:
        document = mapping_doc({"cross": {"mode": "single", "sequence": [["KeyK"]]}})
        with self.assertRaises(RebindError) as ctx:
            self.bridge.put_mapping(document, 99)
        self.assertEqual(ctx.exception.code, "STALE_STORE")

    def test_presets_save_apply_delete(self) -> None:
        self.bridge.put_mapping(
            mapping_doc({"cross": {"mode": "single", "sequence": [["KeyK"]]}}), 1
        )
        saved = self.bridge.put_preset({"action": "save", "name": "openchamber"})
        self.assertEqual(saved["action"], "save")
        self.assertIn("openchamber", saved["presets"]["presets"])

        current = self.bridge.get_mapping()
        self.bridge.put_mapping(
            mapping_doc({"cross": {"mode": "single", "sequence": [["KeyL"]]}}),
            current["baseVersion"],
        )
        applied = self.bridge.put_preset({"action": "apply", "name": "openchamber"})
        self.assertEqual(applied["mapping"]["mappings"]["cross"]["sequence"], [["KeyK"]])

        deleted = self.bridge.put_preset({"action": "delete", "name": "openchamber"})
        self.assertNotIn("openchamber", deleted["presets"]["presets"])

    def test_preset_apply_drives_the_engine(self) -> None:
        self.bridge.put_mapping(
            mapping_doc({"cross": {"mode": "single", "sequence": [["KeyK"]]}}), 1
        )
        self.bridge.put_preset({"action": "save", "name": "openchamber"})
        self.bridge.put_mapping(
            mapping_doc({"cross": {"mode": "single", "sequence": [["KeyL"]]}}),
            self.bridge.get_mapping()["baseVersion"],
        )
        self.bridge.put_preset({"action": "apply", "name": "openchamber"})
        self.bridge._on_report(input_report(face=0x28), None)
        self.assertIn(("down", "KeyK"), self.output.events)
        self.assertNotIn(("down", "KeyL"), self.output.events)

    def test_preset_save_requires_a_name(self) -> None:
        with self.assertRaises(RebindError) as ctx:
            self.bridge.put_preset({"action": "save", "name": "   "})
        self.assertEqual(ctx.exception.code, "SCHEMA_ERROR")

    def test_preset_unknown_action_and_name(self) -> None:
        with self.assertRaises(RebindError) as ctx:
            self.bridge.put_preset({"action": "explode"})
        self.assertEqual(ctx.exception.code, "SCHEMA_ERROR")
        with self.assertRaises(RebindError) as ctx:
            self.bridge.put_preset({"action": "apply", "name": "missing"})
        self.assertEqual(ctx.exception.code, "UNKNOWN_PRESET")

    def test_report_drives_hold_mapping(self) -> None:
        document = mapping_doc({"cross": {"mode": "hold", "sequence": [["ShiftLeft"]]}})
        self.bridge.put_mapping(document, 1)
        self.bridge._on_report(input_report(face=0x28), None)
        self.assertIn(("down", "ShiftLeft"), self.output.events)
        self.bridge._on_report(input_report(face=0x08), None)
        self.assertIn(("up", "ShiftLeft"), self.output.events)

    def test_report_drives_single_mapping(self) -> None:
        document = mapping_doc({"cross": {"mode": "single", "sequence": [["KeyK"]]}})
        self.bridge.put_mapping(document, 1)
        self.bridge._on_report(input_report(face=0x28), None)
        self.assertEqual(
            [event for event in self.output.events if event[1] == "KeyK"],
            [("down", "KeyK"), ("up", "KeyK")],
        )

    def test_ui_focus_suppresses_mappings(self) -> None:
        document = mapping_doc({"cross": {"mode": "single", "sequence": [["KeyK"]]}})
        self.bridge.put_mapping(document, 1)
        self.bridge.ui_active({"active": True})
        self.bridge._on_report(input_report(face=0x28), None)
        self.assertEqual([event for event in self.output.events if event[1] == "KeyK"], [])
        self.assertIn("cross", self.bridge.status()["inputs"])

    def test_ui_focus_releases_held_keys(self) -> None:
        document = mapping_doc({"cross": {"mode": "hold", "sequence": [["ShiftLeft"]]}})
        self.bridge.put_mapping(document, 1)
        self.bridge._on_report(input_report(face=0x28), None)
        self.assertIn(("down", "ShiftLeft"), self.output.events)
        self.bridge.ui_active({"active": True})
        self.assertIn(("up", "ShiftLeft"), self.output.events)

    def test_ui_focus_resumes_when_the_page_reports_blur(self) -> None:
        document = mapping_doc({"cross": {"mode": "single", "sequence": [["KeyK"]]}})
        self.bridge.put_mapping(document, 1)
        self.bridge.ui_active({"active": True})
        self.bridge._on_report(input_report(face=0x28), None)
        self.bridge._on_report(input_report(face=0x08), None)
        self.bridge.ui_active({"active": False})
        self.bridge._on_report(input_report(face=0x28), None)
        self.assertEqual(
            [event for event in self.output.events if event[1] == "KeyK"],
            [("down", "KeyK"), ("up", "KeyK")],
        )

    def test_ui_focus_expires_without_a_heartbeat(self) -> None:
        document = mapping_doc({"cross": {"mode": "single", "sequence": [["KeyK"]]}})
        self.bridge.put_mapping(document, 1)
        self.bridge.ui_active({"active": True})
        self.bridge._ui_last_seen -= 10.0
        self.bridge._on_report(input_report(face=0x28), None)
        self.assertIn(("down", "KeyK"), self.output.events)

    def test_ui_active_is_reported_in_status(self) -> None:
        self.bridge.ui_active({"active": True})
        self.assertTrue(self.bridge.status()["uiActive"])
        self.bridge.ui_active({"active": False})
        self.assertFalse(self.bridge.status()["uiActive"])

    def test_lighting_round_trip(self) -> None:
        lighting = json.loads(json.dumps(DEFAULT_SETTINGS["lighting"]))
        lighting["brightness"] = 50
        self.put_section("lighting", lighting)
        self.assertEqual(self.bridge.get_settings()["lighting"]["brightness"], 50)

    def test_triggers_round_trip(self) -> None:
        triggers = {"left": {"mode": "weapon", "start": 3, "end": 6, "strength": 5},
                    "right": {"mode": "off", "start": 3, "end": 6, "strength": 5}}
        self.put_section("triggers", triggers)
        self.assertEqual(self.bridge.get_settings()["triggers"]["left"]["mode"], "weapon")

    def test_triggers_cache_follows_updates(self) -> None:
        triggers = {"left": {"mode": "weapon", "start": 3, "end": 6, "strength": 5},
                    "right": {"mode": "off", "start": 3, "end": 6, "strength": 5}}
        self.put_section("triggers", triggers)
        self.assertEqual(self.bridge._triggers["left"]["mode"], "weapon")

    def test_triggers_persist_in_settings(self) -> None:
        triggers = {"left": {"mode": "weapon", "start": 3, "end": 6, "strength": 5},
                    "right": {"mode": "off", "start": 3, "end": 6, "strength": 5}}
        self.put_section("triggers", triggers)
        self.assertEqual(self.bridge.get_settings()["triggers"]["left"]["mode"], "weapon")

    def test_put_settings_restarts_only_when_the_port_changes(self) -> None:
        current = self.bridge.get_settings()
        document = {key: value for key, value in current.items() if key != "baseVersion"}
        document["port"] = current["port"]
        with mock.patch.object(self.bridge, "_restart_server") as restart:
            self.bridge.put_settings(document, current["baseVersion"])
            restart.assert_not_called()

        changed = dict(document)
        changed["port"] = 4999
        called = threading.Event()
        ports: list[int] = []

        def record(port: int) -> None:
            ports.append(port)
            called.set()

        with mock.patch.object(self.bridge, "_restart_server", side_effect=record):
            self.bridge.put_settings(changed, self.bridge.get_settings()["baseVersion"])
            self.assertTrue(called.wait(1.0))
        self.assertEqual(ports, [4999])

    def test_put_settings_applies_autostart_only_when_changed(self) -> None:
        class FakeAutostart:
            def __init__(self) -> None:
                self.calls: list[tuple] = []

            def apply(self, bridge: bool, tray: bool) -> dict:
                self.calls.append((bridge, tray))
                return {"bridge": bridge, "tray": tray}

        fake = FakeAutostart()
        self.bridge._autostart = fake
        current = self.bridge.get_settings()
        document = {key: value for key, value in current.items() if key != "baseVersion"}

        self.bridge.put_settings(document, current["baseVersion"])
        self.assertEqual(fake.calls, [])

        changed = dict(document)
        changed["autostart"] = {"bridge": True, "tray": True}
        self.bridge.put_settings(changed, self.bridge.get_settings()["baseVersion"])
        self.assertEqual(fake.calls, [(True, True)])
        self.assertTrue(self.bridge.get_settings()["autostart"]["bridge"])

    def test_put_settings_autostart_failure_keeps_settings(self) -> None:
        class FailingAutostart:
            def apply(self, bridge: bool, tray: bool) -> dict:
                raise OSError("not elevated")

        self.bridge._autostart = FailingAutostart()
        current = self.bridge.get_settings()
        document = {key: value for key, value in current.items() if key != "baseVersion"}
        document["autostart"] = {"bridge": True, "tray": False}

        self.bridge.put_settings(document, current["baseVersion"])
        self.assertTrue(self.bridge.get_settings()["autostart"]["bridge"])

    def test_output_write_swallows_hid_errors(self) -> None:
        class BoomHid:
            def write(self, data: bytes) -> None:
                raise RebindError("DEVICE_NOT_CONNECTED", "gone")

        self.bridge.hid = BoomHid()
        self.bridge._write_output()

    def test_action_errors_are_logged_not_raised(self) -> None:
        class BoomActions:
            def run(self, *args: object) -> dict:
                raise RebindError("INJECTION_FAILED", "nope")

        class FakeLog:
            def __init__(self) -> None:
                self.warnings: list[tuple] = []

            def warning(self, *args: object) -> None:
                self.warnings.append(args)

        self.bridge.actions = BoomActions()
        self.bridge._log = FakeLog()
        self.bridge._run_action("api", "focus-terminal", {})
        self.assertEqual(len(self.bridge._log.warnings), 1)

    def test_sessions_update_lighting_status(self) -> None:
        self.bridge.sessions({"id": "a", "status": "approval", "pid": 1})
        self.assertEqual(self.bridge.lighting.status, "approval")
        self.assertEqual(self.bridge.status()["status"], "approval")
        self.bridge.sessions({"id": "b", "status": "working", "pid": 2})
        self.assertEqual(self.bridge.lighting.status, "approval")
        self.bridge.sessions({"id": "a", "status": "idle", "pid": 1})
        self.assertEqual(self.bridge.lighting.status, "working")

    def test_output_write_produces_report(self) -> None:
        self.bridge._write_output()
        self.assertEqual(len(self.hid.writes), 1)
        self.assertEqual(len(self.hid.writes[0]), 48)
        self.assertEqual(self.hid.writes[0][0], 0x02)

    def test_output_write_does_not_snapshot_settings(self) -> None:
        def boom() -> dict:
            raise AssertionError("snapshot must not run on the output thread")

        self.bridge._settings.snapshot = boom
        self.bridge._write_output()
        self.assertEqual(len(self.hid.writes), 1)

    def test_restart_server_closes_then_rebinds(self) -> None:
        events: list[str] = []

        class FakeServer:
            def shutdown(self) -> None:
                events.append("shutdown")

            def server_close(self) -> None:
                events.append("close")

        started: list[int | None] = []

        def fake_start(port=None) -> None:
            started.append(port)
            self.bridge._server = None

        self.bridge._server = FakeServer()
        self.bridge._port_number = 4173
        self.bridge._start_server = fake_start
        self.bridge._restart_server(5000)
        self.assertEqual(events, ["shutdown", "close"])
        self.assertEqual(started, [5000])

    def test_restart_server_restores_old_port_on_failure(self) -> None:
        class FakeServer:
            def shutdown(self) -> None:
                pass

            def server_close(self) -> None:
                pass

        started: list[int | None] = []

        def fake_start(port=None) -> None:
            started.append(port)
            if port == 5000:
                raise OSError("in use")
            self.bridge._server = None

        self.bridge._server = FakeServer()
        self.bridge._port_number = 4173
        self.bridge._start_server = fake_start
        self.bridge._restart_server(5000)
        self.assertEqual(started, [5000, 4173])

    def test_key_capture_with_injected_reader(self) -> None:
        class Reader:
            def read(self):
                return [VK_CODES["KeyK"]]

        self.bridge._key_capture = KeyCapture(reader_factory=Reader)
        self.assertEqual(self.bridge.key_capture(), {"keys": ["KeyK"]})

    def test_cancel_key_capture_delegates(self) -> None:
        class FakeCapture:
            def cancel(self):
                return {"cancelled": True}

        self.bridge._key_capture = FakeCapture()
        self.assertEqual(self.bridge.cancel_key_capture(), {"cancelled": True})

    def test_autostart_applies_and_persists(self) -> None:
        class FakeAutostart:
            def __init__(self) -> None:
                self.calls: list[tuple] = []

            def apply(self, bridge: bool, tray: bool) -> dict:
                self.calls.append((bridge, tray))
                return {"bridge": bridge, "tray": tray}

        fake = FakeAutostart()
        self.bridge._autostart = fake
        result = self.bridge.autostart({"bridge": True, "tray": True})
        self.assertEqual(result, {"bridge": True, "tray": True, "applied": True})
        self.assertEqual(fake.calls, [(True, True)])
        self.assertTrue(self.bridge.get_settings()["autostart"]["bridge"])

    def test_autostart_failure_keeps_settings(self) -> None:
        class FailingAutostart:
            def apply(self, bridge: bool, tray: bool) -> dict:
                raise OSError("not elevated")

        self.bridge._autostart = FailingAutostart()
        result = self.bridge.autostart({"bridge": True, "tray": False})
        self.assertEqual(result, {"bridge": True, "tray": False, "applied": False})
        self.assertTrue(self.bridge.get_settings()["autostart"]["bridge"])

    def test_plugin_dispatches_status_install_and_remove(self) -> None:
        class FakeInstaller:
            def __init__(self) -> None:
                self.calls: list[object] = []

            def status(self) -> dict:
                self.calls.append("status")
                return {"installed": False}

            def install(self, mode) -> dict:
                self.calls.append(("install", mode))
                return {"installed": True, "mode": mode or "local"}

            def uninstall(self) -> dict:
                self.calls.append("uninstall")
                return {"installed": False}

        fake = FakeInstaller()
        self.bridge._plugin = fake
        self.assertEqual(self.bridge.plugin({}), {"installed": False})
        self.assertEqual(self.bridge.plugin({"action": "install", "mode": "npm"}), {"installed": True, "mode": "npm"})
        self.assertEqual(self.bridge.plugin({"action": "install"})["mode"], "local")
        self.assertEqual(self.bridge.plugin({"action": "uninstall"}), {"installed": False})
        self.assertEqual(fake.calls, ["status", ("install", "npm"), ("install", None), "uninstall"])

    def test_plugin_rejects_unknown_action(self) -> None:
        with self.assertRaises(RebindError) as caught:
            self.bridge.plugin({"action": "reboot"})
        self.assertEqual(caught.exception.code, "SCHEMA_ERROR")

    def test_device_disconnect_releases_held_keys(self) -> None:
        document = mapping_doc({"cross": {"mode": "hold", "sequence": [["ShiftLeft"]]}})
        self.bridge.put_mapping(document, 1)
        self.bridge._on_report(input_report(face=0x28), None)
        self.assertIn(("down", "ShiftLeft"), self.output.events)
        self.bridge._on_device_status("disconnected")
        self.assertIn(("up", "ShiftLeft"), self.output.events)
        self.assertEqual(self.bridge.status()["inputs"], [])

    def test_sessions_deleted_removes_session(self) -> None:
        self.bridge.sessions({"id": "a", "status": "approval", "pid": 1})
        self.assertEqual(self.bridge.status()["status"], "approval")
        self.bridge.sessions({"id": "a", "deleted": True})
        self.assertEqual(self.bridge.status()["status"], "idle")
        self.assertEqual(self.bridge._session_list(), [])

    def test_sessions_expire_after_ttl(self) -> None:
        self.bridge.sessions({"id": "a", "status": "working", "pid": 1, "lastActive": 0})
        self.assertEqual(self.bridge.status()["status"], "idle")
        self.assertEqual(self.bridge._session_list(), [])


if __name__ == "__main__":
    unittest.main()
