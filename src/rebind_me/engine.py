"""Mapping engine: trigger modes, chords and actions. See plan.md §7.

The engine is pure logic. It reads decoded inputs through :meth:`MappingEngine.press`
and :meth:`MappingEngine.release` and writes output through an injected object:

    class Output:
        def key_down(self, code: str) -> None: ...
        def key_up(self, code: str) -> None: ...
        def scroll(self, code: str) -> None: ...

Timing is driven by :meth:`MappingEngine.tick` with a caller-supplied ``now``
(monotonic seconds), so tests can control the clock. Actions are dispatched to
an injected callback.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .keys import SCROLL_CODES
from .store import DEFAULT_CHORD_DELAY_MS, STICK_DIRECTIONS

_TimerCallback = Callable[[float], None]

STICK_ACTIVATION_THRESHOLD = 0.68
STICK_RELEASE_THRESHOLD = 0.42


def resolve_stick_directions(
    left_x: float,
    left_y: float,
    right_x: float,
    right_y: float,
    active: object = frozenset(),
) -> set[str]:
    """Map both sticks to one hysteretic cardinal direction each (plan.md §4)."""
    previous = set(active) & set(STICK_DIRECTIONS)
    resolved: set[str] = set()
    sticks = (
        (("left_stick_up", "left_stick_right", "left_stick_down", "left_stick_left"), left_x, left_y),
        (("right_stick_up", "right_stick_right", "right_stick_down", "right_stick_left"), right_x, right_y),
    )
    for directions, x, y in sticks:
        x = max(-1.0, min(1.0, float(x)))
        y = max(-1.0, min(1.0, float(y)))
        up, right, down, left = directions
        components = {up: -y, right: x, down: y, left: -x}
        current = next((direction for direction in directions if direction in previous), None)
        if current is not None:
            perpendicular = abs(x) if current in (up, down) else abs(y)
            if (
                components[current] >= STICK_RELEASE_THRESHOLD
                and components[current] >= perpendicular * 0.8
            ):
                resolved.add(current)
                continue
        candidate = max(directions, key=components.__getitem__)
        if components[candidate] >= STICK_ACTIVATION_THRESHOLD:
            resolved.add(candidate)
    return resolved


@dataclass
class _Binding:
    entry: dict
    pressed: bool = False
    active: bool = False
    toggle_on: bool = False
    held_codes: list[str] = field(default_factory=list)
    generation: int = 0


class MappingEngine:
    """State machine for the four trigger modes and sequence chords."""

    def __init__(
        self,
        output: object,
        action_handler: Callable[[str, str, dict], None] | None = None,
        chord_delay_ms: int = DEFAULT_CHORD_DELAY_MS,
    ):
        self.output = output
        self.action_handler = action_handler
        self.chord_delay = max(0, chord_delay_ms) / 1000.0
        self._bindings: dict[str, _Binding] = {}
        self._actions: dict[str, dict] = {}
        self._pending: list[tuple[float, int, _TimerCallback]] = []
        self._counter = 0
        self.enabled = True

    # -- configuration ----------------------------------------------------
    def load(self, document: dict) -> None:
        """Apply a validated mapping store document, releasing anything held."""
        self.release_all()
        self._pending.clear()
        self._bindings = {}
        self._actions = document.get("actions", {})
        for name, entry in document.get("mappings", {}).items():
            binding = _Binding(entry=entry)
            if entry.get("mode") == "toggle" and entry.get("toggleInitial") == "on":
                binding.toggle_on = True
                self._activate(binding)
            self._bindings[name] = binding
        self.enabled = bool(document.get("enabled", True))
        if not self.enabled:
            self.release_all()

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)
        if not self.enabled:
            self.release_all()

    # -- input ------------------------------------------------------------
    def press(self, name: str, now: float) -> None:
        if not self.enabled:
            return
        if name in self._actions:
            action = self._actions[name]
            if self.action_handler is not None:
                self.action_handler(name, action["action"], action.get("params", {}))
            return
        binding = self._bindings.get(name)
        if binding is None or binding.pressed:
            return
        binding.pressed = True
        binding.generation += 1
        mode = binding.entry["mode"]
        if mode == "single":
            self._emit_once(binding, now)
        elif mode == "hold":
            self._activate(binding)
        elif mode == "toggle":
            if binding.toggle_on:
                self._deactivate(binding)
                binding.toggle_on = False
            else:
                self._activate(binding)
                binding.toggle_on = True
        elif mode == "repeat":
            # Fire once on press (a quick tap still does something), then keep
            # repeating while held after delayMs.
            self._emit_once(binding, now)
            self._schedule_repeat(binding, now)

    def release(self, name: str, now: float) -> None:
        binding = self._bindings.get(name)
        if binding is None or not binding.pressed:
            return
        binding.pressed = False
        binding.generation += 1
        if binding.entry["mode"] == "hold":
            self._deactivate(binding)
        # repeat stops via the generation check; single/toggle keep their state.

    def release_all(self) -> None:
        for binding in self._bindings.values():
            if binding.active or binding.held_codes:
                self._deactivate(binding)
            binding.pressed = False
        self._pending.clear()

    def tick(self, now: float) -> None:
        due = [item for item in self._pending if item[0] <= now]
        if not due:
            return
        self._pending = [item for item in self._pending if item[0] > now]
        for _deadline, _order, callback in sorted(due, key=lambda item: (item[0], item[1])):
            callback(now)

    # -- internals --------------------------------------------------------
    def _schedule(self, deadline: float, callback: _TimerCallback) -> None:
        self._counter += 1
        self._pending.append((deadline, self._counter, callback))

    def _emit_once(self, binding: _Binding, now: float) -> None:
        entry = binding.entry
        if "sequence" in entry:
            segments = entry["sequence"]
            self._tap(segments[0])
            if len(segments) > 1:
                generation = binding.generation
                self._schedule(
                    now + self.chord_delay,
                    lambda fired: self._chord_step(binding, generation, 1),
                )
        elif "mouse" in entry:
            code = entry["mouse"]
            self.output.key_down(code)
            self.output.key_up(code)
        else:
            self.output.scroll(entry["scroll"])

    def _chord_step(self, binding: _Binding, generation: int, index: int) -> None:
        if not self.enabled or generation != binding.generation:
            return
        segments = binding.entry.get("sequence", [])
        if index < len(segments):
            self._tap(segments[index])

    def _tap(self, codes: list[str]) -> None:
        for code in codes:
            if code in SCROLL_CODES:
                self.output.scroll(code)
        keys = [code for code in codes if code not in SCROLL_CODES]
        for code in keys:
            self.output.key_down(code)
        for code in keys:
            self.output.key_up(code)

    def _hold_target(self, binding: _Binding) -> list[str]:
        entry = binding.entry
        if "sequence" in entry:
            return list(entry["sequence"][0])
        if "mouse" in entry:
            return [entry["mouse"]]
        return []

    def _activate(self, binding: _Binding) -> None:
        codes = self._hold_target(binding)
        binding.held_codes = [code for code in codes if code not in SCROLL_CODES]
        for code in binding.held_codes:
            self.output.key_down(code)
        scroll = binding.entry.get("scroll")
        if scroll:
            self.output.scroll(scroll)
        binding.active = True

    def _deactivate(self, binding: _Binding) -> None:
        for code in reversed(binding.held_codes):
            self.output.key_up(code)
        binding.held_codes = []
        binding.active = False

    def _schedule_repeat(self, binding: _Binding, now: float) -> None:
        delay = binding.entry.get("repeat", {}).get("delayMs", 300) / 1000.0
        generation = binding.generation
        self._schedule(
            now + delay,
            lambda fired: self._repeat_fire(binding, generation, fired),
        )

    def _repeat_fire(self, binding: _Binding, generation: int, now: float) -> None:
        if not self.enabled or not binding.pressed or generation != binding.generation:
            return
        self._emit_once(binding, now)
        interval = binding.entry.get("repeat", {}).get("intervalMs", 50) / 1000.0
        self._schedule(
            now + interval,
            lambda fired: self._repeat_fire(binding, generation, fired),
        )


__all__ = [
    "MappingEngine",
    "STICK_ACTIVATION_THRESHOLD",
    "STICK_RELEASE_THRESHOLD",
    "resolve_stick_directions",
]
