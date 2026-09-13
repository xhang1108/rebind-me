"""Tests for adaptive trigger normalization and encoding."""

import unittest

from rebind_me import protocol
from rebind_me.errors import RebindError
from rebind_me.triggers import encode_trigger, normalize_trigger, normalize_triggers


class NormalizeTriggerTest(unittest.TestCase):
    def test_default_is_off(self) -> None:
        self.assertEqual(
            normalize_trigger(None),
            {"mode": "off", "start": 3, "end": 6, "strength": 5},
        )

    def test_clamps_ranges(self) -> None:
        result = normalize_trigger(
            {"mode": "feedback", "start": -5, "end": -5, "strength": 99}
        )
        self.assertEqual(result["start"], 0)
        self.assertEqual(result["strength"], 8)
        self.assertGreater(result["end"], result["start"])

    def test_unknown_mode(self) -> None:
        with self.assertRaises(RebindError) as ctx:
            normalize_trigger({"mode": "wobble"})
        self.assertEqual(ctx.exception.code, "INVALID_TRIGGER_MODE")

    def test_weapon_start_out_of_range(self) -> None:
        with self.assertRaises(RebindError) as ctx:
            normalize_trigger({"mode": "weapon", "start": 1, "end": 6})
        self.assertEqual(ctx.exception.code, "INVALID_TRIGGER_MODE")

    def test_weapon_end_past_limit(self) -> None:
        with self.assertRaises(RebindError):
            normalize_trigger({"mode": "weapon", "start": 7, "end": 9})

    def test_weapon_end_coerced_above_start(self) -> None:
        result = normalize_trigger({"mode": "weapon", "start": 6, "end": 6})
        self.assertEqual(result["end"], 7)

    def test_both_sides(self) -> None:
        result = normalize_triggers({"left": {"mode": "off"}})
        self.assertEqual(set(result), {"left", "right"})


class EncodeTriggerTest(unittest.TestCase):
    def test_weapon_matches_protocol_golden(self) -> None:
        block = encode_trigger({"mode": "weapon", "start": 3, "end": 6, "strength": 5})
        self.assertEqual(len(block), protocol.TRIGGER_EFFECT_LENGTH)
        self.assertEqual(block.hex(" "), "25 48 00 04 00 00 00 00 00 00 00")

    def test_off_is_zeroed(self) -> None:
        self.assertEqual(encode_trigger({"mode": "off"}), bytes(11))


if __name__ == "__main__":
    unittest.main()
