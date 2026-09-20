"""Tests for touchpad movement, tap and click zones."""

import unittest

from rebind_me.protocol import TouchPoint
from rebind_me.touchpad import TouchpadController


class FakeOutput:
    def __init__(self) -> None:
        self.events: list[tuple] = []

    def mouse_move(self, dx: int, dy: int) -> None:
        self.events.append(("move", dx, dy))


def config(**overrides) -> dict:
    base = {"mouseControl": True, "sensitivity": 1.5}
    base.update(overrides)
    return base


def touch(x: int, y: int, active: bool = True) -> TouchPoint:
    return TouchPoint(active=active, id=1, x=x, y=y)


class ZoneTest(unittest.TestCase):
    def test_zone_split(self) -> None:
        controller = TouchpadController(config())
        self.assertEqual(controller.zone(0), "left")
        self.assertEqual(controller.zone(959), "left")
        self.assertEqual(controller.zone(960), "right")
        self.assertEqual(controller.zone(1919), "right")


class MovementTest(unittest.TestCase):
    def setUp(self) -> None:
        self.output = FakeOutput()
        self.controller = TouchpadController(config())

    def test_first_sample_does_not_move(self) -> None:
        events = self.controller.update(touch(100, 100), False, 0.0, self.output)
        self.assertEqual(self.output.events, [])
        self.assertEqual(events, [])

    def test_movement_scaled_by_sensitivity(self) -> None:
        self.controller.update(touch(100, 100), False, 0.0, self.output)
        self.controller.update(touch(110, 90), False, 0.016, self.output)
        self.assertEqual(self.output.events, [("move", 15, -15)])

    def test_mouse_control_off(self) -> None:
        self.controller.apply(config(mouseControl=False))
        self.controller.update(touch(100, 100), False, 0.0, self.output)
        self.controller.update(touch(140, 100), False, 0.016, self.output)
        self.assertEqual(self.output.events, [])


class TapTest(unittest.TestCase):
    def setUp(self) -> None:
        self.output = FakeOutput()
        self.controller = TouchpadController(config())

    def test_left_tap(self) -> None:
        self.controller.update(touch(200, 300), False, 0.0, self.output)
        events = self.controller.update(None, False, 0.1, self.output)
        self.assertEqual(events, [("tap", "left")])

    def test_right_tap(self) -> None:
        self.controller.update(touch(1500, 300), False, 0.0, self.output)
        events = self.controller.update(None, False, 0.1, self.output)
        self.assertEqual(events, [("tap", "right")])

    def test_slow_touch_is_not_a_tap(self) -> None:
        self.controller.update(touch(200, 300), False, 0.0, self.output)
        events = self.controller.update(None, False, 0.5, self.output)
        self.assertEqual(events, [])

    def test_large_movement_is_not_a_tap(self) -> None:
        self.controller.update(touch(200, 300), False, 0.0, self.output)
        self.controller.update(touch(260, 300), False, 0.05, self.output)
        events = self.controller.update(None, False, 0.1, self.output)
        self.assertEqual(events, [])

    def test_tap_ignores_mouse_control(self) -> None:
        self.controller.apply(config(mouseControl=False))
        self.controller.update(touch(200, 300), False, 0.0, self.output)
        events = self.controller.update(None, False, 0.1, self.output)
        self.assertEqual(events, [("tap", "left")])

    def test_click_suppresses_the_tap(self) -> None:
        self.controller.update(touch(200, 300), False, 0.0, self.output)
        self.controller.update(touch(200, 300), True, 0.05, self.output)
        events = self.controller.update(None, True, 0.1, self.output)
        self.assertEqual(events, [])


class ClickTest(unittest.TestCase):
    def setUp(self) -> None:
        self.output = FakeOutput()
        self.controller = TouchpadController(config())

    def test_click_uses_touch_zone(self) -> None:
        events = self.controller.update(touch(1500, 300), True, 0.0, self.output)
        self.assertEqual(events, [("click-down", "right")])

    def test_click_release_reports_the_other_edge(self) -> None:
        self.controller.update(touch(1500, 300), True, 0.0, self.output)
        events = self.controller.update(touch(1500, 300), False, 0.1, self.output)
        self.assertEqual(events, [("click-up", "right")])

    def test_click_edges_only(self) -> None:
        self.controller.update(touch(200, 300), True, 0.0, self.output)
        events = self.controller.update(touch(200, 300), True, 0.1, self.output)
        self.assertEqual(events, [])


if __name__ == "__main__":
    unittest.main()
