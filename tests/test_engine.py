"""Tests for the mapping engine state machine (clock injected)."""

import unittest

from rebind_me.engine import MappingEngine


class FakeOutput:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    def key_down(self, code: str) -> None:
        self.events.append(("down", code))

    def key_up(self, code: str) -> None:
        self.events.append(("up", code))

    def scroll(self, code: str) -> None:
        self.events.append(("scroll", code))


def document(mappings: dict, actions: dict | None = None, enabled: bool = True) -> dict:
    return {
        "version": 1,
        "enabled": enabled,
        "mappings": mappings,
        "actions": actions or {},
        "touchpad": {
            "mouseControl": True,
            "sensitivity": 1.5,
            "tap": {"left": "MouseLeft", "right": "MouseRight"},
            "click": {"left": "MouseLeft", "right": "MouseRight"},
        },
    }


class EngineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.output = FakeOutput()
        self.engine = MappingEngine(self.output, chord_delay_ms=80)

    def test_single_sequence_taps_once(self) -> None:
        self.engine.load(document({"cross": {"mode": "single", "sequence": [["KeyK"]]}}))
        self.engine.press("cross", 0.0)
        self.engine.release("cross", 0.05)
        self.assertEqual(self.output.events, [("down", "KeyK"), ("up", "KeyK")])

    def test_single_chord_runs_two_segments(self) -> None:
        self.engine.load(
            document(
                {
                    "cross": {
                        "mode": "single",
                        "sequence": [["ControlLeft", "KeyK"], ["KeyL"]],
                    }
                }
            )
        )
        self.engine.press("cross", 0.0)
        self.assertEqual(
            self.output.events,
            [("down", "ControlLeft"), ("down", "KeyK"), ("up", "ControlLeft"), ("up", "KeyK")],
        )
        self.engine.tick(0.05)
        self.assertEqual(len(self.output.events), 4)
        self.engine.tick(0.09)
        self.assertEqual(self.output.events[-2:], [("down", "KeyL"), ("up", "KeyL")])

    def test_chord_completes_after_quick_release(self) -> None:
        self.engine.load(
            document(
                {
                    "cross": {
                        "mode": "single",
                        "sequence": [["KeyK"], ["KeyL"]],
                    }
                }
            )
        )
        self.engine.press("cross", 0.0)
        self.engine.release("cross", 0.01)
        self.engine.tick(0.2)
        self.assertIn(("down", "KeyL"), self.output.events)
        self.assertIn(("up", "KeyL"), self.output.events)

    def test_single_mouse_click(self) -> None:
        self.engine.load(document({"touchpad": {"mode": "single", "mouse": "MouseLeft"}}))
        self.engine.press("touchpad", 0.0)
        self.assertEqual(self.output.events, [("down", "MouseLeft"), ("up", "MouseLeft")])

    def test_single_scroll(self) -> None:
        self.engine.load(
            document({"right_stick_up": {"mode": "single", "scroll": "ScrollUp"}})
        )
        self.engine.press("right_stick_up", 0.0)
        self.assertEqual(self.output.events, [("scroll", "ScrollUp")])

    def test_hold_presses_and_releases(self) -> None:
        self.engine.load(document({"cross": {"mode": "hold", "sequence": [["ShiftLeft"]]}}))
        self.engine.press("cross", 0.0)
        self.assertEqual(self.output.events, [("down", "ShiftLeft")])
        self.engine.release("cross", 0.5)
        self.assertEqual(self.output.events, [("down", "ShiftLeft"), ("up", "ShiftLeft")])

    def test_hold_mouse(self) -> None:
        self.engine.load(document({"touchpad": {"mode": "hold", "mouse": "MouseLeft"}}))
        self.engine.press("touchpad", 0.0)
        self.engine.release("touchpad", 0.1)
        self.assertEqual(self.output.events, [("down", "MouseLeft"), ("up", "MouseLeft")])

    def test_toggle_latches(self) -> None:
        self.engine.load(
            document({"cross": {"mode": "toggle", "sequence": [["ControlLeft"]]}})
        )
        self.engine.press("cross", 0.0)
        self.engine.release("cross", 0.01)
        self.assertEqual(self.output.events, [("down", "ControlLeft")])
        self.engine.press("cross", 1.0)
        self.assertEqual(self.output.events, [("down", "ControlLeft"), ("up", "ControlLeft")])

    def test_toggle_initial_on_holds_at_load(self) -> None:
        self.engine.load(
            document(
                {
                    "cross": {
                        "mode": "toggle",
                        "sequence": [["ControlLeft"]],
                        "toggleInitial": "on",
                    }
                }
            )
        )
        self.assertEqual(self.output.events, [("down", "ControlLeft")])

    def test_repeat_fires_once_on_press_then_repeats(self) -> None:
        self.engine.load(
            document(
                {
                    "circle": {
                        "mode": "repeat",
                        "sequence": [["Delete"]],
                        "repeat": {"delayMs": 300, "intervalMs": 50},
                    }
                }
            )
        )
        self.engine.press("circle", 0.0)
        # Immediate single trigger so a quick tap still works.
        self.assertEqual(self.output.events, [("down", "Delete"), ("up", "Delete")])
        self.engine.tick(0.2)
        self.assertEqual(len(self.output.events), 2)
        self.engine.tick(0.3)
        self.assertEqual(len(self.output.events), 4)
        self.engine.tick(0.35)
        self.assertEqual(len(self.output.events), 6)
        self.engine.release("circle", 0.36)
        self.engine.tick(0.4)
        self.assertEqual(len(self.output.events), 6)

    def test_repeat_quick_tap_triggers_once(self) -> None:
        self.engine.load(
            document(
                {
                    "circle": {
                        "mode": "repeat",
                        "sequence": [["Delete"]],
                        "repeat": {"delayMs": 300, "intervalMs": 50},
                    }
                }
            )
        )
        self.engine.press("circle", 0.0)
        self.engine.release("circle", 0.05)
        self.engine.tick(1.0)
        self.assertEqual(self.output.events, [("down", "Delete"), ("up", "Delete")])

    def test_action_dispatch(self) -> None:
        calls: list[tuple] = []
        engine = MappingEngine(
            self.output,
            action_handler=lambda name, action, params: calls.append((name, action, params)),
        )
        engine.load(
            document(
                {},
                actions={
                    "triangle": {
                        "action": "switch-to-app",
                        "params": {"process": "OpenChamber"},
                    }
                },
            )
        )
        engine.press("triangle", 0.0)
        self.assertEqual(calls, [("triangle", "switch-to-app", {"process": "OpenChamber"})])
        self.assertEqual(self.output.events, [])

    def test_disabled_ignores_input(self) -> None:
        self.engine.load(
            document({"cross": {"mode": "single", "sequence": [["KeyK"]]}}, enabled=False)
        )
        self.engine.press("cross", 0.0)
        self.assertEqual(self.output.events, [])

    def test_release_all_unholds(self) -> None:
        self.engine.load(document({"cross": {"mode": "hold", "sequence": [["ShiftLeft"]]}}))
        self.engine.press("cross", 0.0)
        self.engine.release_all()
        self.assertEqual(self.output.events, [("down", "ShiftLeft"), ("up", "ShiftLeft")])


if __name__ == "__main__":
    unittest.main()
