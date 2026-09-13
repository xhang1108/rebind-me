"""Tests for the lighting state machine."""

import json
import unittest

from rebind_me import lighting
from rebind_me.store import DEFAULT_SETTINGS


def lighting_settings() -> dict:
    return json.loads(json.dumps(DEFAULT_SETTINGS["lighting"]))


class EffectTest(unittest.TestCase):
    def test_static(self) -> None:
        self.assertEqual(lighting.effect_factor("static", 3, 123.0), 1.0)

    def test_blink_period(self) -> None:
        period = lighting.BLINK_PERIOD_SECONDS[2]
        self.assertEqual(lighting.effect_factor("blink", 3, 0.0), 1.0)
        self.assertEqual(lighting.effect_factor("blink", 3, period * 0.75), 0.0)

    def test_breathe_period(self) -> None:
        period = lighting.BREATHE_PERIOD_SECONDS[2]
        self.assertAlmostEqual(lighting.effect_factor("breathe", 3, 0.0), 0.0)
        self.assertAlmostEqual(lighting.effect_factor("breathe", 3, period / 2), 1.0)
        self.assertAlmostEqual(lighting.effect_factor("breathe", 3, period), 0.0)

    def test_speed_clamped(self) -> None:
        self.assertEqual(
            lighting.effect_factor("blink", 99, 0.0),
            lighting.effect_factor("blink", 5, 0.0),
        )

    def test_unknown_effect(self) -> None:
        with self.assertRaises(ValueError):
            lighting.effect_factor("sparkle", 3, 0.0)


class LightingControllerTest(unittest.TestCase):
    def test_idle_is_green_static(self) -> None:
        controller = lighting.LightingController(lighting_settings())
        frame = controller.frame(0.0)
        self.assertEqual((frame.red, frame.green, frame.blue), (0, 255, 0))
        self.assertEqual(frame.brightness, 100)

    def test_status_switch_changes_color(self) -> None:
        controller = lighting.LightingController(lighting_settings())
        controller.set_status("approval")
        frame = controller.frame(0.0)
        self.assertEqual((frame.red, frame.green, frame.blue), (255, 255, 0))

    def test_working_breathes(self) -> None:
        controller = lighting.LightingController(lighting_settings())
        controller.set_status("working")
        dark = controller.frame(0.0)
        bright = controller.frame(lighting.BREATHE_PERIOD_SECONDS[2] / 2)
        self.assertEqual((dark.red, dark.green, dark.blue), (0, 0, 0))
        self.assertEqual((bright.red, bright.green, bright.blue), (255, 0, 0))

    def test_manual_override(self) -> None:
        controller = lighting.LightingController(lighting_settings())
        controller.set_manual_override(True)
        frame = controller.frame(0.0)
        self.assertEqual((frame.red, frame.green, frame.blue), (0, 0, 255))

    def test_player_leds_carried(self) -> None:
        settings = lighting_settings()
        settings["playerLeds"] = 4
        controller = lighting.LightingController(settings)
        self.assertEqual(controller.frame(0.0).player_leds, 4)

    def test_unknown_status(self) -> None:
        controller = lighting.LightingController(lighting_settings())
        with self.assertRaises(ValueError):
            controller.set_status("sleepy")


if __name__ == "__main__":
    unittest.main()
