"""Decode tests for the DualSense USB input report.

Reports are built from raw bytes here so the tests do not depend on the
encoder. Real recorded fixtures are exercised separately by
``test_protocol_fixtures.py``.
"""

import unittest

from rebind_me import protocol as p

REPORT_LENGTH = 64


def make_report() -> bytearray:
    report = bytearray(REPORT_LENGTH)
    report[0] = p.INPUT_REPORT_ID
    report[p.IN_LEFT_X] = 128
    report[p.IN_LEFT_Y] = 128
    report[p.IN_RIGHT_X] = 128
    report[p.IN_RIGHT_Y] = 128
    report[p.IN_FACE_DPAD] = 0x08
    return report


def touch_block(x: int, y: int, *, id: int = 1, active: bool = True) -> bytes:
    flag = 0 if active else 0x80
    return bytes(
        (
            (id & 0x7F) | flag,
            x & 0xFF,
            ((x >> 8) & 0x0F) | ((y & 0x0F) << 4),
            (y >> 4) & 0xFF,
        )
    )


class DecodeValidationTest(unittest.TestCase):
    def test_wrong_report_id_raises(self) -> None:
        report = make_report()
        report[0] = 0x02
        with self.assertRaises(ValueError):
            p.decode_input_report(bytes(report))

    def test_too_short_raises(self) -> None:
        with self.assertRaises(ValueError):
            p.decode_input_report(b"\x01\x80\x80")


class DecodeButtonsTest(unittest.TestCase):
    def test_face_buttons(self) -> None:
        for bit, name in enumerate(("square", "cross", "circle", "triangle"), start=4):
            report = make_report()
            report[p.IN_FACE_DPAD] = 0x08 | (1 << bit)
            self.assertEqual(p.decode_input_report(bytes(report)).buttons, {name})

    def test_no_buttons(self) -> None:
        report = make_report()
        report[p.IN_FACE_DPAD] = 0x08
        self.assertEqual(p.decode_input_report(bytes(report)).buttons, frozenset())

    def test_shoulder_buttons(self) -> None:
        names = ("l1", "r1", "l2", "r2", "create", "options", "l3", "r3")
        for bit, name in enumerate(names):
            report = make_report()
            report[p.IN_MISC] = 1 << bit
            self.assertEqual(p.decode_input_report(bytes(report)).buttons, {name})

    def test_system_buttons(self) -> None:
        for bit, name in enumerate(("ps", "touchpad", "mute")):
            report = make_report()
            report[p.IN_SYSTEM] = 1 << bit
            self.assertEqual(p.decode_input_report(bytes(report)).buttons, {name})

    def test_multiple_buttons(self) -> None:
        report = make_report()
        report[p.IN_FACE_DPAD] = 0x08 | 0x20
        report[p.IN_SYSTEM] = 0x01
        self.assertEqual(
            p.decode_input_report(bytes(report)).buttons, {"cross", "ps"}
        )

    def test_dpad_directions(self) -> None:
        expected = {
            0: {"dpad_up"},
            1: {"dpad_up", "dpad_right"},
            2: {"dpad_right"},
            3: {"dpad_right", "dpad_down"},
            4: {"dpad_down"},
            5: {"dpad_down", "dpad_left"},
            6: {"dpad_left"},
            7: {"dpad_up", "dpad_left"},
            8: set(),
        }
        for value, buttons in expected.items():
            report = make_report()
            report[p.IN_FACE_DPAD] = value
            self.assertEqual(p.decode_input_report(bytes(report)).buttons, buttons)

    def test_all_nineteen_button_names_are_unique_and_known(self) -> None:
        self.assertEqual(len(p.BUTTON_NAMES), 19)
        self.assertEqual(len(set(p.BUTTON_NAMES)), 19)


class DecodeAxesTest(unittest.TestCase):
    def test_stick_extremes(self) -> None:
        report = make_report()
        report[p.IN_LEFT_X] = 0
        report[p.IN_LEFT_Y] = 255
        state = p.decode_input_report(bytes(report))
        self.assertEqual(state.left_x, -1.0)
        self.assertEqual(state.left_y, 1.0)

    def test_stick_center(self) -> None:
        report = make_report()
        state = p.decode_input_report(bytes(report))
        self.assertEqual(state.left_x, 0.004)
        self.assertEqual(state.right_y, 0.004)

    def test_trigger_values(self) -> None:
        report = make_report()
        report[p.IN_L2] = 0
        report[p.IN_R2] = 255
        state = p.decode_input_report(bytes(report))
        self.assertEqual(state.left_trigger, 0.0)
        self.assertEqual(state.right_trigger, 1.0)

    def test_trigger_midpoint(self) -> None:
        report = make_report()
        report[p.IN_L2] = 128
        self.assertEqual(p.decode_input_report(bytes(report)).left_trigger, 0.502)

    def test_sequence(self) -> None:
        report = make_report()
        report[p.IN_SEQUENCE] = 42
        self.assertEqual(p.decode_input_report(bytes(report)).sequence, 42)


class DecodeTouchTest(unittest.TestCase):
    def test_first_active_point(self) -> None:
        report = make_report()
        report[p.IN_TOUCH_FIRST : p.IN_TOUCH_FIRST + 4] = touch_block(100, 200, id=1)
        state = p.decode_input_report(bytes(report))
        assert state.touch is not None
        self.assertEqual((state.touch.id, state.touch.x, state.touch.y), (1, 100, 200))

    def test_twelve_bit_bounds(self) -> None:
        report = make_report()
        report[p.IN_TOUCH_FIRST : p.IN_TOUCH_FIRST + 4] = touch_block(1919, 1079, id=5)
        state = p.decode_input_report(bytes(report))
        assert state.touch is not None
        self.assertEqual((state.touch.x, state.touch.y), (1919, 1079))

    def test_inactive_first_falls_through_to_second(self) -> None:
        report = make_report()
        report[p.IN_TOUCH_FIRST : p.IN_TOUCH_FIRST + 4] = touch_block(
            10, 10, id=1, active=False
        )
        report[p.IN_TOUCH_SECOND : p.IN_TOUCH_SECOND + 4] = touch_block(300, 400, id=2)
        state = p.decode_input_report(bytes(report))
        assert state.touch is not None
        self.assertEqual((state.touch.id, state.touch.x, state.touch.y), (2, 300, 400))

    def test_no_active_point(self) -> None:
        report = make_report()
        report[p.IN_TOUCH_FIRST : p.IN_TOUCH_FIRST + 4] = touch_block(
            10, 10, id=1, active=False
        )
        report[p.IN_TOUCH_SECOND : p.IN_TOUCH_SECOND + 4] = touch_block(
            20, 20, id=2, active=False
        )
        self.assertIsNone(p.decode_input_report(bytes(report)).touch)


if __name__ == "__main__":
    unittest.main()
