"""Integration tests for the bridge controller with fakes (no hardware)."""

import json
import tempfile
import unittest
from pathlib import Path

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

    def test_status_defaults(self) -> None:
        status = self.bridge.status()
        self.assertTrue(status["running"])
        self.assertEqual(status["device"], "disconnected")
        self.assertEqual(status["inputs"], [])

    def test_status_reports_pressed_inputs(self) -> None:
        self.bridge._on_report(input_report(face=0x28), None)  # cross held
        self.assertIn("cross", self.bridge.status()["inputs"])
        self.bridge._on_report(input_report(face=0x08), None)
        self.assertEqual(self.bridge.status()["inputs"], [])

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

    def test_lighting_round_trip(self) -> None:
        lighting = json.loads(json.dumps(DEFAULT_SETTINGS["lighting"]))
        lighting["brightness"] = 50
        result = self.bridge.put_lighting(lighting, 1)
        self.assertEqual(result["brightness"], 50)
        self.assertEqual(self.bridge.get_lighting()["brightness"], 50)

    def test_triggers_round_trip(self) -> None:
        triggers = {"left": {"mode": "weapon", "start": 3, "end": 6, "strength": 5},
                    "right": {"mode": "off", "start": 3, "end": 6, "strength": 5}}
        result = self.bridge.put_triggers(triggers, 1)
        self.assertEqual(result["left"]["mode"], "weapon")

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

    def test_key_capture_with_injected_reader(self) -> None:
        class Reader:
            def read(self):
                return [VK_CODES["KeyK"]]

        self.bridge._key_capture = KeyCapture(reader_factory=Reader)
        self.assertEqual(self.bridge.key_capture(), {"keys": ["KeyK"]})


if __name__ == "__main__":
    unittest.main()
