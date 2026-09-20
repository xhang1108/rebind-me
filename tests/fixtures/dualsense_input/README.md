# Recorded DualSense input fixtures

`tests/test_protocol_fixtures.py` loads every `*.json` in this directory and
checks that decoding the stored bytes yields the expected events. The test is
**skipped** while this directory contains no JSON files.

These fixtures must be recorded from a **real controller over USB** — they are
the ground truth that the synthetic decode tests cannot provide. Record at
least one report for each of:

- every face / shoulder / system button (19 buttons)
- each D-pad direction
- left and right stick at centre, each extreme (8 directions)
- L2 / R2 at a few analog positions
- touchpad: no touch, one finger left half, one finger right half
- the mute button

## How to record

Use the built-in recorder (no admin required), with the controller on USB:

```bat
python tools/record_fixture.py
```

It walks the checklist, reads one live report per entry, and writes the JSON
files here. Pass `--list` to see the checklist, `--only cross` to record one
entry, `--force` to overwrite. The expected values come from the checklist
(what you intend to press), so a decoder bug shows up as a failing fixture.

## Format

```json
{
  "description": "cross pressed, sticks centred",
  "hex": "01 80 80 80 80 00 00 13 20 00 00 ...",
  "expect": {
    "buttons": ["cross"],
    "leftX": 0.004,
    "leftY": 0.004,
    "rightX": 0.004,
    "rightY": 0.004,
    "leftTrigger": 0.0,
    "rightTrigger": 0.0,
    "sequence": 19,
    "touch": null
  }
}
```

- `hex` is the full report including the report ID; spaces are optional.
- `buttons` is any subset of the 19 names in `rebind_me.protocol.BUTTON_NAMES`.
- Axis keys are optional; omit any you do not want to assert. Floats are
  compared with `tolerance` (default `0.02`); `sequence` is exact.
- `touch` is `null` or `{ "id": 1, "x": 123, "y": 456 }`.
- `touchActive` (bool) asserts whether any point is active; `touchHalf` is
  `"left"` or `"right"` and checks the X position against the midpoint (960).
- `tolerance` (optional float) overrides the axis comparison tolerance.
