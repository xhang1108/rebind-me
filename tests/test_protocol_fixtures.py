"""Decode recorded DualSense input fixtures.

Real captures live in ``tests/fixtures/dualsense_input/*.json`` (see the README
in that directory for the format and how to record them). Until at least one
fixture exists the whole case is skipped, so CI stays green on a machine with
no controller.
"""

import json
import unittest
from pathlib import Path

from rebind_me import protocol as p

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "dualsense_input"

_AXIS_FIELDS = {
    "leftX": "left_x",
    "leftY": "left_y",
    "rightX": "right_x",
    "rightY": "right_y",
    "leftTrigger": "left_trigger",
    "rightTrigger": "right_trigger",
    "sequence": "sequence",
}


def _load_fixtures() -> list[tuple[str, dict]]:
    if not FIXTURE_DIR.is_dir():
        return []
    cases: list[tuple[str, dict]] = []
    for path in sorted(FIXTURE_DIR.glob("*.json")):
        cases.append((path.name, json.loads(path.read_text(encoding="utf-8"))))
    return cases


FIXTURES = _load_fixtures()


@unittest.skipUnless(FIXTURES, f"no recorded input fixtures in {FIXTURE_DIR}")
class RecordedInputFixtureTest(unittest.TestCase):
    def test_recorded_reports(self) -> None:
        for name, case in FIXTURES:
            with self.subTest(fixture=name):
                report = bytes.fromhex(case["hex"])
                state = p.decode_input_report(report)
                expect = case["expect"]
                tolerance = float(case.get("tolerance", 0.02))

                if "buttons" in expect:
                    self.assertEqual(set(state.buttons), set(expect["buttons"]))
                for fixture_key, field in _AXIS_FIELDS.items():
                    if fixture_key not in expect:
                        continue
                    actual = getattr(state, field)
                    if fixture_key == "sequence":
                        self.assertEqual(actual, expect[fixture_key], msg=fixture_key)
                    else:
                        self.assertAlmostEqual(
                            actual, expect[fixture_key], delta=tolerance, msg=fixture_key
                        )

                self._assert_touch(state, expect)

    def _assert_touch(self, state: p.InputState, expect: dict) -> None:
        if "touchActive" in expect:
            self.assertEqual(state.touch is not None, expect["touchActive"])
        if "touchHalf" in expect:
            assert state.touch is not None
            if expect["touchHalf"] == "left":
                self.assertLess(state.touch.x, 960)
            else:
                self.assertGreaterEqual(state.touch.x, 960)
        if "touch" in expect:
            expected_touch = expect["touch"]
            if expected_touch is None:
                self.assertIsNone(state.touch)
            else:
                assert state.touch is not None
                self.assertEqual(state.touch.id, expected_touch["id"])
                self.assertEqual(state.touch.x, expected_touch["x"])
                self.assertEqual(state.touch.y, expected_touch["y"])


if __name__ == "__main__":
    unittest.main()
