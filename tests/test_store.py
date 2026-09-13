"""Tests for the data model, validation and atomic store."""

import json
import tempfile
import unittest
from pathlib import Path

from rebind_me import store
from rebind_me.errors import RebindError
from rebind_me.store import (
    DEFAULT_MAPPING_STORE,
    DEFAULT_SETTINGS,
    JsonStore,
    load_or_create_token,
    validate_mapping_store,
    validate_settings,
)


def mapping_doc_with(**overrides) -> dict:
    document = json.loads(json.dumps(DEFAULT_MAPPING_STORE))
    document.update(overrides)
    return document


class MappingValidationTest(unittest.TestCase):
    def test_preset_is_valid(self) -> None:
        result = validate_mapping_store(DEFAULT_MAPPING_STORE)
        self.assertTrue(result["enabled"])
        self.assertIn("cross", result["mappings"])
        self.assertEqual(result["touchpad"]["splitX"], 960)

    def test_unknown_button(self) -> None:
        document = mapping_doc_with(mappings={"nope": {"mode": "single", "mouse": "MouseLeft"}})
        with self.assertRaises(RebindError) as ctx:
            validate_mapping_store(document)
        self.assertEqual(ctx.exception.code, "UNKNOWN_BUTTON")

    def test_invalid_mode(self) -> None:
        document = mapping_doc_with(
            mappings={"cross": {"mode": "wobble", "sequence": [["KeyK"]]}}
        )
        with self.assertRaises(RebindError) as ctx:
            validate_mapping_store(document)
        self.assertEqual(ctx.exception.code, "INVALID_MODE")

    def test_chord_requires_single(self) -> None:
        document = mapping_doc_with(
            mappings={
                "cross": {
                    "mode": "repeat",
                    "sequence": [["KeyK"], ["KeyL"]],
                    "repeat": {"delayMs": 300, "intervalMs": 50},
                }
            }
        )
        with self.assertRaises(RebindError) as ctx:
            validate_mapping_store(document)
        self.assertEqual(ctx.exception.code, "INVALID_MODE")

    def test_too_many_segments(self) -> None:
        document = mapping_doc_with(
            mappings={"cross": {"mode": "single", "sequence": [["KeyA"], ["KeyB"], ["KeyC"]]}}
        )
        with self.assertRaises(RebindError) as ctx:
            validate_mapping_store(document)
        self.assertEqual(ctx.exception.code, "MAPPING_LIMIT")

    def test_too_many_keys_in_segment(self) -> None:
        document = mapping_doc_with(
            mappings={
                "cross": {
                    "mode": "single",
                    "sequence": [["KeyA", "KeyB", "KeyC", "KeyD", "KeyE", "KeyF"]],
                }
            }
        )
        with self.assertRaises(RebindError) as ctx:
            validate_mapping_store(document)
        self.assertEqual(ctx.exception.code, "MAPPING_LIMIT")

    def test_invalid_key_code(self) -> None:
        document = mapping_doc_with(
            mappings={"cross": {"mode": "single", "sequence": [["NotAKey"]]}}
        )
        with self.assertRaises(RebindError) as ctx:
            validate_mapping_store(document)
        self.assertEqual(ctx.exception.code, "INVALID_KEY_CODE")

    def test_mouse_not_a_keyboard_code(self) -> None:
        document = mapping_doc_with(
            mappings={"cross": {"mode": "single", "sequence": [["MouseLeft"]]}}
        )
        with self.assertRaises(RebindError) as ctx:
            validate_mapping_store(document)
        self.assertEqual(ctx.exception.code, "INVALID_KEY_CODE")

    def test_sequence_and_mouse_are_exclusive(self) -> None:
        document = mapping_doc_with(
            mappings={
                "cross": {"mode": "single", "sequence": [["KeyK"]], "mouse": "MouseLeft"}
            }
        )
        with self.assertRaises(RebindError) as ctx:
            validate_mapping_store(document)
        self.assertEqual(ctx.exception.code, "SCHEMA_ERROR")

    def test_repeat_only_for_repeat_mode(self) -> None:
        document = mapping_doc_with(
            mappings={
                "cross": {
                    "mode": "single",
                    "sequence": [["KeyK"]],
                    "repeat": {"delayMs": 300, "intervalMs": 50},
                }
            }
        )
        with self.assertRaises(RebindError):
            validate_mapping_store(document)

    def test_repeat_range(self) -> None:
        document = mapping_doc_with(
            mappings={
                "circle": {
                    "mode": "repeat",
                    "sequence": [["Delete"]],
                    "repeat": {"delayMs": 5, "intervalMs": 50},
                }
            }
        )
        with self.assertRaises(RebindError):
            validate_mapping_store(document)

    def test_toggle_initial(self) -> None:
        document = mapping_doc_with(
            mappings={
                "cross": {"mode": "toggle", "sequence": [["KeyK"]], "toggleInitial": "on"}
            }
        )
        self.assertEqual(
            validate_mapping_store(document)["mappings"]["cross"]["toggleInitial"], "on"
        )

    def test_mapping_and_action_are_exclusive(self) -> None:
        document = mapping_doc_with(
            mappings={"l1": {"mode": "single", "sequence": [["KeyK"]]}},
            actions={"l1": {"action": "focus-terminal"}},
        )
        with self.assertRaises(RebindError) as ctx:
            validate_mapping_store(document)
        self.assertEqual(ctx.exception.code, "SCHEMA_ERROR")

    def test_unknown_action(self) -> None:
        document = mapping_doc_with(actions={"l1": {"action": "explode"}})
        with self.assertRaises(RebindError):
            validate_mapping_store(document)

    def test_switch_to_app_requires_process(self) -> None:
        document = mapping_doc_with(actions={"triangle": {"action": "switch-to-app"}})
        with self.assertRaises(RebindError):
            validate_mapping_store(document)

    def test_split_x_range(self) -> None:
        document = mapping_doc_with(
            touchpad=dict(DEFAULT_MAPPING_STORE["touchpad"], splitX=5000)
        )
        with self.assertRaises(RebindError) as ctx:
            validate_mapping_store(document)
        self.assertEqual(ctx.exception.code, "INVALID_SPLIT_X")

    def test_sensitivity_range(self) -> None:
        document = mapping_doc_with(
            touchpad=dict(DEFAULT_MAPPING_STORE["touchpad"], sensitivity=99.0)
        )
        with self.assertRaises(RebindError):
            validate_mapping_store(document)


class SettingsValidationTest(unittest.TestCase):
    def test_preset_is_valid(self) -> None:
        result = validate_settings(DEFAULT_SETTINGS)
        self.assertEqual(result["ui"]["language"], "zh-Hant")
        self.assertEqual(result["lighting"]["status"]["idle"]["effect"], "static")
        self.assertEqual(result["triggers"]["left"]["mode"], "off")

    def test_bad_language(self) -> None:
        document = json.loads(json.dumps(DEFAULT_SETTINGS))
        document["ui"]["language"] = "fr"
        with self.assertRaises(RebindError):
            validate_settings(document)

    def test_bad_effect(self) -> None:
        document = json.loads(json.dumps(DEFAULT_SETTINGS))
        document["lighting"]["status"]["idle"]["effect"] = "sparkle"
        with self.assertRaises(RebindError):
            validate_settings(document)

    def test_speed_clamped(self) -> None:
        document = json.loads(json.dumps(DEFAULT_SETTINGS))
        document["lighting"]["status"]["idle"]["speed"] = 99
        result = validate_settings(document)
        self.assertEqual(result["lighting"]["status"]["idle"]["speed"], 5)

    def test_bad_trigger_mode(self) -> None:
        document = json.loads(json.dumps(DEFAULT_SETTINGS))
        document["triggers"]["left"]["mode"] = "boom"
        with self.assertRaises(RebindError) as ctx:
            validate_settings(document)
        self.assertEqual(ctx.exception.code, "INVALID_TRIGGER_MODE")

    def test_port_range(self) -> None:
        document = json.loads(json.dumps(DEFAULT_SETTINGS))
        document["port"] = 70000
        with self.assertRaises(RebindError):
            validate_settings(document)


class JsonStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.path = self.dir / "mapping-store.json"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _store(self) -> JsonStore:
        return JsonStore(self.path, validate_mapping_store, DEFAULT_MAPPING_STORE)

    def test_load_creates_preset_file(self) -> None:
        snapshot = self._store().load()
        self.assertTrue(self.path.exists())
        self.assertEqual(snapshot["baseVersion"], 1)
        on_disk = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(on_disk["baseVersion"], 1)

    def test_replace_increments_version(self) -> None:
        store_obj = self._store()
        store_obj.load()
        document = mapping_doc_with(enabled=False)
        result = store_obj.replace(document, base_version=1)
        self.assertEqual(result["baseVersion"], 2)
        self.assertFalse(result["enabled"])

    def test_stale_base_version(self) -> None:
        store_obj = self._store()
        store_obj.load()
        with self.assertRaises(RebindError) as ctx:
            store_obj.replace(mapping_doc_with(), base_version=99)
        self.assertEqual(ctx.exception.code, "STALE_STORE")

    def test_legacy_file_is_replaced_by_preset(self) -> None:
        self.path.write_text(json.dumps({"version": 0, "legacy": True}), encoding="utf-8")
        snapshot = self._store().load()
        self.assertIn("mappings", snapshot)
        self.assertNotIn("legacy", snapshot)

    def test_invalid_document_rejected(self) -> None:
        store_obj = self._store()
        store_obj.load()
        with self.assertRaises(RebindError):
            store_obj.replace(mapping_doc_with(mappings={"x": {"mode": "single"}}), 1)

    def test_reset(self) -> None:
        store_obj = self._store()
        store_obj.load()
        store_obj.replace(mapping_doc_with(enabled=False), 1)
        snapshot = store_obj.reset()
        self.assertEqual(snapshot["baseVersion"], 1)
        self.assertTrue(snapshot["enabled"])

    def test_atomic_no_temp_files_left(self) -> None:
        store_obj = self._store()
        store_obj.load()
        store_obj.replace(mapping_doc_with(), 1)
        leftovers = [p.name for p in self.dir.iterdir() if p.name.startswith(".")]
        self.assertEqual(leftovers, [])


class TokenTest(unittest.TestCase):
    def test_token_created_and_stable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bridge.token"
            first = load_or_create_token(path)
            self.assertTrue(first)
            self.assertEqual(load_or_create_token(path), first)


if __name__ == "__main__":
    unittest.main()
