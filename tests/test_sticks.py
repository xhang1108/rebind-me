"""Tests for stick direction resolution with hysteresis."""

import unittest

from rebind_me.engine import (
    STICK_ACTIVATION_THRESHOLD,
    STICK_RELEASE_THRESHOLD,
    resolve_stick_directions,
)


def resolve(lx=0.0, ly=0.0, rx=0.0, ry=0.0, active=frozenset()):
    return resolve_stick_directions(lx, ly, rx, ry, active)


class StickDirectionTest(unittest.TestCase):
    def test_centered(self) -> None:
        self.assertEqual(resolve(), set())

    def test_cardinal_directions(self) -> None:
        self.assertEqual(resolve(ly=-1.0), {"left_stick_up"})
        self.assertEqual(resolve(ly=1.0), {"left_stick_down"})
        self.assertEqual(resolve(lx=-1.0), {"left_stick_left"})
        self.assertEqual(resolve(lx=1.0), {"left_stick_right"})

    def test_right_stick_is_independent(self) -> None:
        self.assertEqual(resolve(rx=1.0), {"right_stick_right"})
        self.assertEqual(resolve(lx=1.0, ry=-1.0), {"left_stick_right", "right_stick_up"})

    def test_below_activation(self) -> None:
        self.assertEqual(resolve(lx=STICK_ACTIVATION_THRESHOLD - 0.01), set())

    def test_dominant_axis_wins(self) -> None:
        self.assertEqual(resolve(lx=0.9, ly=-0.7), {"left_stick_right"})

    def test_hysteresis_keeps_direction_between_thresholds(self) -> None:
        held = resolve(lx=1.0)
        self.assertIn("left_stick_right", held)
        kept = resolve(lx=(STICK_ACTIVATION_THRESHOLD + STICK_RELEASE_THRESHOLD) / 2, active=held)
        self.assertEqual(kept, {"left_stick_right"})

    def test_hysteresis_releases_below_threshold(self) -> None:
        held = {"left_stick_up"}
        released = resolve(ly=-0.1, active=held)
        self.assertEqual(released, set())

    def test_hysteresis_keeps_direction_under_small_perpendicular_tilt(self) -> None:
        kept = resolve(lx=0.6, ly=-0.3, active={"left_stick_right"})
        self.assertEqual(kept, {"left_stick_right"})

    def test_perpendicular_axis_takes_over_held_direction(self) -> None:
        taken = resolve(lx=0.5, ly=-0.9, active={"left_stick_right"})
        self.assertEqual(taken, {"left_stick_up"})

    def test_ignores_non_stick_active_inputs(self) -> None:
        self.assertEqual(resolve(active={"cross", "circle"}), set())


if __name__ == "__main__":
    unittest.main()
