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

    def test_mouse_mapping_repeats(self) -> None:
        self.engine.load(
            document(
                {
                    "cross": {
                        "mode": "repeat",
                        "mouse": "MouseLeft",
                        "repeat": {"delayMs": 100, "intervalMs": 50},
                    }
                }
            )
        )
        self.engine.press("cross", 0.0)
        self.assertEqual(self.output.events, [("down", "MouseLeft"), ("up", "MouseLeft")])
        self.engine.tick(0.1)
        self.assertEqual(len(self.output.events), 4)
        self.engine.tick(0.151)
        self.assertEqual(len(self.output.events), 6)
        self.engine.release("cross", 0.16)
        self.engine.tick(0.5)
        self.assertEqual(len(self.output.events), 6)

    def test_latched_repeat_keeps_going_after_release(self) -> None:
        # A two-key segment, so every emit is two key_down plus two key_up.
        self.engine.load(
            document(
                {
                    "r2": {
                        "mode": "repeat",
                        "sequence": [["ShiftLeft", "Enter"]],
                        "repeat": {"delayMs": 100, "intervalMs": 50, "latch": True},
                    }
                }
            )
        )
        self.engine.press("r2", 0.0)
        self.engine.release("r2", 0.02)
        self.assertEqual(len(self.output.events), 4)
        # Long after a held repeat would have stopped, it is still going.
        self.engine.tick(0.1)
        self.assertEqual(len(self.output.events), 8)
        self.engine.tick(0.151)
        self.assertEqual(len(self.output.events), 12)
        self.engine.tick(0.201)
        self.assertEqual(len(self.output.events), 16)

    def test_latched_repeat_stops_on_the_second_press(self) -> None:
        self.engine.load(
            document(
                {
                    "r2": {
                        "mode": "repeat",
                        "sequence": [["Delete"]],
                        "repeat": {"delayMs": 100, "intervalMs": 50, "latch": True},
                    }
                }
            )
        )
        self.engine.press("r2", 0.0)
        self.engine.release("r2", 0.02)
        self.engine.tick(0.1)
        self.assertEqual(len(self.output.events), 4)
        # The second press cancels the pending timer: no new click is emitted.
        self.engine.press("r2", 0.12)
        self.engine.release("r2", 0.14)
        self.assertEqual(len(self.output.events), 4)
        self.engine.tick(1.0)
        self.assertEqual(len(self.output.events), 4)

    def test_latched_repeat_is_cleared_by_release_all(self) -> None:
        # Otherwise disabling and re-enabling would leave the flag on with no
        # pending timer, and the next press would only stop it.
        self.engine.load(
            document(
                {
                    "r2": {
                        "mode": "repeat",
                        "sequence": [["Delete"]],
                        "repeat": {"delayMs": 100, "intervalMs": 50, "latch": True},
                    }
                }
            )
        )
        self.engine.press("r2", 0.0)
        self.engine.release("r2", 0.02)
        self.engine.set_enabled(False)
        self.engine.set_enabled(True)
        self.engine.tick(1.0)
        self.assertEqual(len(self.output.events), 2)
        # The latch is off, so a fresh press starts a new repeat rather than
        # being swallowed as a stop.
        self.engine.press("r2", 2.0)
        self.assertEqual(len(self.output.events), 4)
        self.engine.release("r2", 2.02)
        self.engine.tick(2.1)
        self.assertEqual(len(self.output.events), 6)

    def test_latched_inputs_reports_only_latched_repeats(self) -> None:
        self.engine.load(
            document(
                {
                    "r2": {
                        "mode": "repeat",
                        "sequence": [["Delete"]],
                        "repeat": {"delayMs": 100, "intervalMs": 50, "latch": True},
                    },
                    "circle": {"mode": "single", "sequence": [["Delete"]]},
                }
            )
        )
        self.assertEqual(self.engine.latched_inputs(), [])
        self.engine.press("r2", 0.0)
        self.engine.release("r2", 0.02)
        self.assertEqual(self.engine.latched_inputs(), ["r2"])

    def test_stop_latched_cancels_the_pending_fire(self) -> None:
        self.engine.load(
            document(
                {
                    "r2": {
                        "mode": "repeat",
                        "sequence": [["Delete"]],
                        "repeat": {"delayMs": 100, "intervalMs": 50, "latch": True},
                    }
                }
            )
        )
        self.engine.press("r2", 0.0)
        self.engine.release("r2", 0.02)
        self.engine.tick(0.1)
        self.assertEqual(len(self.output.events), 4)
        self.assertEqual(self.engine.stop_latched(), ["r2"])
        self.assertEqual(self.engine.latched_inputs(), [])
        # The pending callback still carries the old generation and drops itself.
        self.engine.tick(0.151)
        self.engine.tick(1.0)
        self.assertEqual(len(self.output.events), 4)

    def test_stop_latched_does_not_resume_while_the_button_is_still_held(self) -> None:
        # Bumping the generation kills the chain and nothing reschedules it, so
        # a button the user is still physically holding stays quiet. Only a
        # fresh press may restart the repeat.
        self.engine.load(
            document(
                {
                    "r2": {
                        "mode": "repeat",
                        "sequence": [["Delete"]],
                        "repeat": {"delayMs": 100, "intervalMs": 50, "latch": True},
                    }
                }
            )
        )
        self.engine.press("r2", 0.0)
        self.engine.tick(0.1)
        self.assertEqual(len(self.output.events), 4)
        self.engine.stop_latched()
        self.engine.tick(0.151)
        self.engine.tick(1.0)
        self.assertEqual(len(self.output.events), 4)
        # Let go and press again: the repeat comes back.
        self.engine.release("r2", 1.1)
        self.engine.press("r2", 1.2)
        self.assertEqual(len(self.output.events), 6)
        self.engine.tick(1.3)
        self.assertEqual(len(self.output.events), 8)

    def test_stop_latched_is_a_noop_with_nothing_latched(self) -> None:
        self.engine.load(
            document(
                {
                    "r2": {
                        "mode": "repeat",
                        "sequence": [["Delete"]],
                        "repeat": {"delayMs": 100, "intervalMs": 50},
                    }
                }
            )
        )
        self.assertEqual(self.engine.stop_latched(), [])
        # A held (non-latched) repeat is not something stop_latched may touch.
        self.engine.press("r2", 0.0)
        self.engine.tick(0.1)
        self.assertEqual(len(self.output.events), 4)
        self.assertEqual(self.engine.stop_latched(), [])
        self.engine.tick(0.151)
        self.assertEqual(len(self.output.events), 6)

    def test_repeat_without_latch_still_stops_on_release(self) -> None:
        self.engine.load(
            document(
                {
                    "circle": {
                        "mode": "repeat",
                        "sequence": [["Delete"]],
                        "repeat": {"delayMs": 100, "intervalMs": 50},
                    }
                }
            )
        )
        self.engine.press("circle", 0.0)
        self.engine.release("circle", 0.02)
        self.engine.tick(0.1)
        self.assertEqual(len(self.output.events), 2)
        self.engine.tick(1.0)
        self.assertEqual(len(self.output.events), 2)

    def test_repeat_random_window_picks_a_fresh_gap_each_fire(self) -> None:
        # Drawn gaps: low bound (40ms), midpoint (60ms), near high (~79.6ms),
        # a quarter of the way back in (50ms), then the low bound again. Every
        # fire spends one draw on the gap that follows it.
        draws = iter([0.0, 0.5, 0.99, 0.25, 0.0])
        engine = MappingEngine(
            self.output, chord_delay_ms=80, random_source=lambda: next(draws)
        )
        engine.load(
            document(
                {
                    "cross": {
                        "mode": "repeat",
                        "mouse": "MouseLeft",
                        "repeat": {
                            "delayMs": 100,
                            "intervalMs": 50,
                            "random": {"minMs": 40, "maxMs": 80},
                        },
                    }
                }
            )
        )
        engine.press("cross", 0.0)
        # The press fires straight away; the first repeat waits out delayMs.
        self.assertEqual(len(self.output.events), 2)
        engine.tick(0.09)
        self.assertEqual(len(self.output.events), 2)
        engine.tick(0.1)
        self.assertEqual(len(self.output.events), 4)
        # First drawn gap is the low bound: 40ms, not the fixed 50ms.
        engine.tick(0.13)
        self.assertEqual(len(self.output.events), 4)
        engine.tick(0.15)
        self.assertEqual(len(self.output.events), 6)
        # Second drawn gap is the midpoint: 60ms.
        engine.tick(0.19)
        self.assertEqual(len(self.output.events), 6)
        engine.tick(0.21)
        self.assertEqual(len(self.output.events), 8)
        # Third drawn gap is near the high bound: ~79.6ms.
        engine.tick(0.27)
        self.assertEqual(len(self.output.events), 8)
        engine.tick(0.29)
        self.assertEqual(len(self.output.events), 10)
        # Fourth drawn gap is 50ms again, so nothing fires at 0.33.
        engine.tick(0.33)
        self.assertEqual(len(self.output.events), 10)
        engine.tick(0.35)
        self.assertEqual(len(self.output.events), 12)

    def test_repeat_random_window_never_exceeds_max(self) -> None:
        # A source that returns 1.0 must not push a gap past the window.
        engine = MappingEngine(self.output, random_source=lambda: 1.0)
        engine.load(
            document(
                {
                    "cross": {
                        "mode": "repeat",
                        "mouse": "MouseLeft",
                        "repeat": {
                            "delayMs": 100,
                            "intervalMs": 50,
                            "random": {"minMs": 40, "maxMs": 80},
                        },
                    }
                }
            )
        )
        engine.press("cross", 0.0)
        engine.tick(0.1)
        self.assertEqual(len(self.output.events), 4)
        engine.tick(0.179)
        self.assertEqual(len(self.output.events), 4)
        engine.tick(0.181)
        self.assertEqual(len(self.output.events), 6)

    def test_action_dispatch(self) -> None:
        calls: list[tuple] = []
        engine = MappingEngine(
            self.output,
            action_handler=lambda name, action, params, pressed: calls.append(
                (name, action, params, pressed)
            ),
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
        self.assertEqual(
            calls, [("triangle", "switch-to-app", {"process": "OpenChamber"}, True)]
        )
        self.assertEqual(self.output.events, [])

    def test_action_push_to_talk_starts_on_press_stops_on_release(self) -> None:
        calls: list[tuple] = []
        engine = MappingEngine(
            self.output,
            action_handler=lambda name, action, params, pressed: calls.append(
                (name, action, params, pressed)
            ),
        )
        engine.load(
            document(
                {},
                actions={"triangle": {"action": "webhook", "params": {"url": "http://127.0.0.1:8978/start"}}},
            )
        )
        engine.press("triangle", 0.0)
        engine.release("triangle", 0.5)
        self.assertEqual(
            calls,
            [
                ("triangle", "webhook", {"url": "http://127.0.0.1:8978/start"}, True),
                ("triangle", "webhook", {"url": "http://127.0.0.1:8978/start"}, False),
            ],
        )
        self.assertEqual(self.output.events, [])  # no synthetic key events

    def test_action_release_all_stops_a_held_push_to_talk(self) -> None:
        calls: list[tuple] = []
        engine = MappingEngine(
            self.output,
            action_handler=lambda name, action, params, pressed: calls.append(
                (name, action, params, pressed)
            ),
        )
        engine.load(
            document(
                {},
                actions={"triangle": {"action": "webhook", "params": {"url": "http://x/start"}}},
            )
        )
        engine.press("triangle", 0.0)
        engine.release_all()
        self.assertEqual(
            calls,
            [
                ("triangle", "webhook", {"url": "http://x/start"}, True),
                ("triangle", "webhook", {"url": "http://x/start"}, False),
            ],
        )

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
