"""Cross-language contract tests: the UI/plugin constants must match Python.

The UI keeps its own copies of the input names, mapping modes, action names,
lighting effects and status states (they run in the browser, so they cannot
import Python). These tests parse the JavaScript sources and compare them to
``store``/``keys``, so a rename on either side fails here instead of drifting
silently.
"""

import re
import unittest
from pathlib import Path

from rebind_me import keys, store

ROOT = Path(__file__).resolve().parents[1]
MODEL_JS = ROOT / "src" / "rebind_me" / "ui" / "model.js"
BRIDGE_MJS = ROOT / "plugin" / "bridge.mjs"


def _array(text: str, name: str) -> list[str]:
    match = re.search(rf"export const {name} = \[(.*?)\];", text, re.DOTALL)
    assert match is not None, f"{name} array not found"
    return re.findall(r'"([^"]*)"', match.group(1))


def _string(text: str, name: str) -> str:
    match = re.search(rf'export const {name} = "([^"]*)";', text)
    assert match is not None, f"{name} string not found"
    return match.group(1)


def _number(text: str, name: str) -> int:
    match = re.search(rf"export const {name} = (\d+);", text)
    assert match is not None, f"{name} number not found"
    return int(match.group(1))


class ModelContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.model = MODEL_JS.read_text(encoding="utf-8")

    def test_input_names_match_store(self) -> None:
        self.assertEqual(_array(self.model, "INPUT_NAMES"), list(store.INPUT_NAMES))

    def test_touchpad_zone_inputs_match_store(self) -> None:
        self.assertEqual(
            _array(self.model, "TOUCHPAD_ZONE_INPUTS"), list(store.TOUCHPAD_ZONE_INPUTS)
        )

    def test_mapping_modes_match_store(self) -> None:
        self.assertEqual(_array(self.model, "MODES"), list(store.MAPPING_MODES))

    def test_actions_match_store(self) -> None:
        self.assertEqual(_array(self.model, "ACTIONS"), list(store.ACTIONS))

    def test_lighting_effects_match_store(self) -> None:
        self.assertEqual(_array(self.model, "EFFECTS"), list(store._EFFECTS))

    def test_status_states_match_store(self) -> None:
        self.assertEqual(_array(self.model, "STATUS_STATES"), list(store._STATUS_STATES))

    def test_mouse_and_scroll_codes_match_keys(self) -> None:
        self.assertEqual(set(_array(self.model, "MOUSE_CODES")), set(keys.MOUSE_BUTTON_CODES))
        self.assertEqual(set(_array(self.model, "SCROLL_CODES")), set(keys.SCROLL_CODES))

    def test_preset_name_limit_matches_store(self) -> None:
        self.assertEqual(_number(self.model, "MAX_PRESET_NAME"), store.MAX_PRESET_NAME)


class PluginContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.bridge = BRIDGE_MJS.read_text(encoding="utf-8")

    def test_bridge_discovery_matches_store(self) -> None:
        self.assertEqual(_string(self.bridge, "DEFAULT_URL"), f"http://127.0.0.1:{store.DEFAULT_PORT}")
        self.assertEqual(_string(self.bridge, "RUNTIME_DIRNAME"), store.runtime_dir().name)
        self.assertEqual(_string(self.bridge, "TOKEN_FILENAME"), store.TOKEN_FILENAME)


if __name__ == "__main__":
    unittest.main()
