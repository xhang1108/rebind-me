"""Mapping engine: trigger modes, chords and actions.

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

import random
from dataclasses import dataclass, field
from typing import Callable, Iterable

from .keys import SCROLL_CODES
from .store import DEFAULT_CHORD_DELAY_MS, DEFAULT_REPEAT, STICK_DIRECTIONS

_TimerCallback = Callable[[float], None]
# Returns a float in [0, 1). Injected so tests can drive a repeat mapping's
# random cadence without touching the global random module.
_RandomCallback = Callable[[], float]

STICK_ACTIVATION_THRESHOLD = 0.68
STICK_RELEASE_THRESHOLD = 0.42
# A perpendicular axis this much stronger than the held one takes over.
STICK_PERPENDICULAR_RATIO = 0.8


def _clamp_unit(value: object) -> float:
    return max(-1.0, min(1.0, float(value)))


def _directions(side: str) -> tuple[str, ...]:
    """Cardinal input names for one stick, in ``STICK_DIRECTIONS`` order."""
    prefix = f"{side}_stick_"
    return tuple(name for name in STICK_DIRECTIONS if name.startswith(prefix))


def _resolve_stick(
    x: float,
    y: float,
    directions: tuple[str, ...],
    held: str | None,
) -> str | None:
    """Resolve one stick to at most one cardinal direction, with hysteresis.

    A ``held`` direction survives while its component stays at or above
    ``STICK_RELEASE_THRESHOLD`` and the perpendicular axis has not overrun it by
    ``STICK_PERPENDICULAR_RATIO``. Otherwise the strongest axis wins, but only
    once it reaches ``STICK_ACTIVATION_THRESHOLD``.
    """
    up, right, down, left = directions
    strength = {up: -y, right: x, down: y, left: -x}

    if held is not None:
        perpendicular = abs(x) if held in (up, down) else abs(y)
        floor = max(STICK_RELEASE_THRESHOLD, perpendicular * STICK_PERPENDICULAR_RATIO)
        if strength[held] >= floor:
            return held

    candidate = max(directions, key=lambda direction: strength[direction])
    return candidate if strength[candidate] >= STICK_ACTIVATION_THRESHOLD else None


def resolve_stick_directions(
    left_x: float,
    left_y: float,
    right_x: float,
    right_y: float,
    active: Iterable[str] = frozenset(),
) -> set[str]:
    """Map both sticks to one hysteretic cardinal direction each."""
    held = set(active) & set(STICK_DIRECTIONS)
    resolved: set[str] = set()
    for side, x, y in (("left", left_x, left_y), ("right", right_x, right_y)):
        directions = _directions(side)
        previous = next((name for name in directions if name in held), None)
        chosen = _resolve_stick(_clamp_unit(x), _clamp_unit(y), directions, previous)
        if chosen is not None:
            resolved.add(chosen)
    return resolved


@dataclass
class _Binding:
    entry: dict
    pressed: bool = False
    active: bool = False
    toggle_on: bool = False
    latched: bool = False
    held_codes: list[str] = field(default_factory=list)
    generation: int = 0


class MappingEngine:
    """State machine for the four trigger modes and sequence chords."""

    def __init__(
        self,
        output: object,
        action_handler: Callable[[str, str, dict, bool], None] | None = None,
        chord_delay_ms: int = DEFAULT_CHORD_DELAY_MS,
        random_source: _RandomCallback = random.random,
    ):
        self.output = output
        self.action_handler = action_handler
        self.chord_delay = max(0, chord_delay_ms) / 1000.0
        self._random_source = random_source
        self._bindings: dict[str, _Binding] = {}
        self._actions: dict[str, dict] = {}
        self._active_actions: set[str] = set()
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
        self._active_actions = set()
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
                self.action_handler(name, action["action"], action.get("params", {}), True)
            self._active_actions.add(name)
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
            if binding.latched:
                # A second press stops a latched repeat. The generation bump
                # above already invalidated the pending timer, so the pending
                # queue needs no separate cancel path.
                binding.latched = False
                return
            # Fire once on press (a quick tap still does something), then keep
            # repeating after delayMs -- while the button is held, or, for a
            # latched repeat, until the next press.
            self._emit_once(binding, now)
            self._schedule_repeat(binding, now)
            binding.latched = self._latches(binding)

    def release(self, name: str, now: float) -> None:
        # Actions are released independently of the binding state machine so a
        # push-to-talk action can stop on button-up exactly when it started on
        # button-down. The handler gets ``pressed=False``; this mirrors press.
        if name in self._active_actions:
            self._active_actions.discard(name)
            action = self._actions.get(name)
            if action is not None and self.action_handler is not None:
                self.action_handler(
                    name, action["action"], action.get("params", {}), False
                )
        binding = self._bindings.get(name)
        if binding is None or not binding.pressed:
            return
        binding.pressed = False
        if binding.entry["mode"] == "hold":
            self._deactivate(binding)
        # Repeat stops via the pressed check; a pending chord step for `single`
        # must survive the release so a quick tap still plays every segment.

    def release_all(self) -> None:
        # A held push-to-talk action must be stopped (button-up) too, so a
        # disconnect mid-hold does not leave a push-to-talk webhook stuck on.
        for name in list(self._active_actions):
            self._active_actions.discard(name)
            action = self._actions.get(name)
            if action is not None and self.action_handler is not None:
                self.action_handler(
                    name, action["action"], action.get("params", {}), False
                )
        for binding in self._bindings.values():
            if binding.active or binding.held_codes:
                self._deactivate(binding)
            binding.pressed = False
            # A latched repeat has to be un-latched here as well: leaving the
            # flag set would survive the disable / re-enable cycle with no
            # pending timer behind it, and the next press would only stop it.
            binding.latched = False
        self._pending.clear()

    def latched_inputs(self) -> list[str]:
        """Names of the repeat mappings that are still firing after release."""
        return [name for name, b in self._bindings.items() if b.latched]

    def stop_latched(self) -> list[str]:
        """Cancel every latched repeat, returning the names that were running.

        Bumping the generation is enough to kill the chain: the pending
        callback still carries the old generation and drops itself in
        :meth:`_repeat_fire`. A button that is still physically held does not
        pick the repeat back up on its own, because nothing reschedules the
        chain -- only a fresh press relatches.
        """
        stopped = self.latched_inputs()
        for name in stopped:
            binding = self._bindings[name]
            binding.latched = False
            binding.generation += 1
        return stopped

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

    def _latches(self, binding: _Binding) -> bool:
        """True when this repeat keeps firing after the button is released."""
        return bool(binding.entry.get("repeat", {}).get("latch"))

    def _next_interval(self, binding: _Binding) -> float:
        """Seconds to wait before the next repeat fire.

        A mapping with a ``random`` window gets a fresh gap on every fire, so
        the cadence varies; otherwise the gap is the fixed ``intervalMs``.
        """
        repeat = binding.entry.get("repeat", {})
        window = repeat.get("random")
        if window:
            low = window["minMs"]
            high = window["maxMs"]
            interval = low + (high - low) * self._random_source()
        else:
            interval = repeat.get("intervalMs", DEFAULT_REPEAT["intervalMs"])
        return interval / 1000.0

    def _schedule_repeat(self, binding: _Binding, now: float) -> None:
        repeat = binding.entry.get("repeat", {})
        delay = repeat.get("delayMs", DEFAULT_REPEAT["delayMs"]) / 1000.0
        generation = binding.generation
        self._schedule(
            now + delay,
            lambda fired: self._repeat_fire(binding, generation, fired),
        )

    def _repeat_fire(self, binding: _Binding, generation: int, now: float) -> None:
        # A repeat keeps going while the button is held, and keeps going after
        # release only when it is latched. The generation check is what lets a
        # second press cancel a latched repeat: the pending callback still
        # carries the old generation and drops itself here.
        if not self.enabled or generation != binding.generation:
            return
        if not (binding.pressed or binding.latched):
            return
        self._emit_once(binding, now)
        self._schedule(
            now + self._next_interval(binding),
            lambda fired: self._repeat_fire(binding, generation, fired),
        )


__all__ = [
    "MappingEngine",
    "STICK_ACTIVATION_THRESHOLD",
    "STICK_PERPENDICULAR_RATIO",
    "STICK_RELEASE_THRESHOLD",
    "resolve_stick_directions",
]
