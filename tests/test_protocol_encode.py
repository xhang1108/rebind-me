"""Golden encode vectors and output-report field tests."""

import unittest

from rebind_me import protocol as p


class TriggerEffectGoldenTest(unittest.TestCase):
    """Fixed config -> fixed bytes. Vectors are frozen in PROTOCOL.md §2.3."""

    def test_off(self) -> None:
        effect = p.encode_trigger_effect(
            {"mode": "off", "start": 3, "end": 6, "strength": 5}
        )
        self.assertEqual(effect.hex(" "), "00 00 00 00 00 00 00 00 00 00 00")

    def test_weapon(self) -> None:
        effect = p.encode_trigger_effect(
            {"mode": "weapon", "start": 3, "end": 6, "strength": 5}
        )
        self.assertEqual(effect.hex(" "), "25 48 00 04 00 00 00 00 00 00 00")

    def test_weapon_full_range(self) -> None:
        effect = p.encode_trigger_effect(
            {"mode": "weapon", "start": 2, "end": 8, "strength": 8}
        )
        self.assertEqual(effect.hex(" "), "25 04 01 07 00 00 00 00 00 00 00")

    def test_feedback(self) -> None:
        effect = p.encode_trigger_effect(
            {"mode": "feedback", "start": 3, "strength": 5}
        )
        self.assertEqual(effect.hex(" "), "21 f8 03 00 48 92 24 00 00 00 00")

    def test_feedback_all_zones_max_strength(self) -> None:
        effect = p.encode_trigger_effect(
            {"mode": "feedback", "start": 0, "strength": 8}
        )
        self.assertEqual(effect.hex(" "), "21 ff 03 ff ff ff 3f 00 00 00 00")

    def test_length(self) -> None:
        self.assertEqual(len(p.encode_trigger_effect({"mode": "off"})), 11)

    def test_unknown_mode_raises(self) -> None:
        with self.assertRaises(ValueError):
            p.encode_trigger_effect({"mode": "wobble"})


class OutputReportTest(unittest.TestCase):
    def test_full_golden(self) -> None:
        report = p.encode_output_report(
            lightbar=(10, 20, 30),
            brightness=100,
            player_leds=4,
            mic_muted=True,
            mic_led_inverted=True,
            triggers={
                "right": {"mode": "weapon", "start": 3, "end": 6, "strength": 5},
                "left": {"mode": "off", "start": 3, "end": 6, "strength": 5},
            },
        )
        self.assertEqual(
            report.hex(" "),
            "02 0c 17 00 00 00 00 00 00 00 10 25 48 00 04 00 00 00 00 00 00 "
            "00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 "
            "00 03 04 0a 14 1e",
        )

    def test_length_and_id(self) -> None:
        report = p.encode_output_report()
        self.assertEqual(len(report), p.OUTPUT_REPORT_LENGTH)
        self.assertEqual(report[0], p.OUTPUT_REPORT_ID)

    def test_no_triggers_leaves_flag0_clear(self) -> None:
        report = p.encode_output_report()
        self.assertEqual(report[p.OUT_VALID_FLAG0], 0x00)

    def test_triggers_set_flag0_and_blocks(self) -> None:
        report = p.encode_output_report(
            triggers={"right": {"mode": "off"}, "left": {"mode": "off"}}
        )
        self.assertEqual(
            report[p.OUT_VALID_FLAG0], p.FLAG0_RIGHT_TRIGGER | p.FLAG0_LEFT_TRIGGER
        )

    def test_steady_state_flag1(self) -> None:
        report = p.encode_output_report()
        self.assertEqual(report[p.OUT_VALID_FLAG1], 0x17)

    def test_brightness_buckets(self) -> None:
        for value, expected in ((0, 0), (1, 1), (33, 1), (34, 2), (66, 2), (67, 3), (100, 3)):
            report = p.encode_output_report(brightness=value)
            self.assertEqual(report[p.OUT_LED_BRIGHTNESS], expected, msg=str(value))

    def test_player_leds_clamped(self) -> None:
        self.assertEqual(p.encode_output_report(player_leds=99)[p.OUT_PLAYER_LEDS], 0x1F)
        self.assertEqual(p.encode_output_report(player_leds=-3)[p.OUT_PLAYER_LEDS], 0x00)

    def test_lightbar_clamped_and_encoded(self) -> None:
        report = p.encode_output_report(lightbar=(300, -5, 128))
        self.assertEqual(tuple(report[p.OUT_LIGHTBAR : p.OUT_LIGHTBAR + 3]), (255, 0, 128))

    def test_mic_led_inverted(self) -> None:
        live = p.encode_output_report(mic_muted=False, mic_led_inverted=True)
        muted = p.encode_output_report(mic_muted=True, mic_led_inverted=True)
        self.assertEqual(live[p.OUT_MIC_LED], p.MIC_LED_ON)
        self.assertEqual(muted[p.OUT_MIC_LED], 0x00)
        self.assertEqual(muted[p.OUT_POWER_SAVE] & p.POWER_SAVE_MIC_MUTE, p.POWER_SAVE_MIC_MUTE)

    def test_mic_led_stock(self) -> None:
        live = p.encode_output_report(mic_muted=False, mic_led_inverted=False)
        muted = p.encode_output_report(mic_muted=True, mic_led_inverted=False)
        self.assertEqual(live[p.OUT_MIC_LED], 0x00)
        self.assertEqual(muted[p.OUT_MIC_LED], p.MIC_LED_ON)

    def test_zero_motors_sets_vibration_flags(self) -> None:
        report = p.encode_output_report(zero_motors=True)
        flags = report[p.OUT_VALID_FLAG0]
        self.assertTrue(flags & p.FLAG0_COMPATIBLE_VIBRATION)
        self.assertTrue(flags & p.FLAG0_HAPTICS_SELECT)
        self.assertEqual(report[p.OUT_MOTOR_RIGHT], 0)
        self.assertEqual(report[p.OUT_MOTOR_LEFT], 0)


if __name__ == "__main__":
    unittest.main()
