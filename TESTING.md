# Testing

Two layers: **automated** (no hardware, runs in CI) and **hardware/manual**
(needs a real DualSense on USB). Everything here runs on Windows with Python
3.10+.

---

## 1. Automated tests (no controller)

One-time setup:

```bat
python -m pip install -e .
```

Run everything CI runs:

```bat
python -m compileall -q src tests
python -m unittest discover -s tests -v
node --check plugin/index.js
node --test
```

Expected: `unittest` reports `OK` (the protocol golden vectors and the bundled
real-device fixtures pass), and Node reports `pass 2 / fail 0`. The fixture
set grows as you record more captures in §2.

To run just the protocol layer:

```bat
python -m unittest tests.test_protocol_encode tests.test_protocol_decode -v
```

---

## 2. Hardware test — record input fixtures

This is the one part that needs the real controller. The recorder reads raw
USB input reports and saves them as JSON; the fixture test then checks the
decoder against what you intended to press.

> Reading input does **not** need administrator rights.

### 2.1 Steps

1. Connect the DualSense to a USB port and wake it (press PS).
2. Make sure no tool is grabbing it exclusively (close Steam / DSX / DS4Windows
   if they cause trouble).
3. Confirm the bridge can see it:

   ```bat
   python tools/record_fixture.py --list
   ```

   This prints the checklist. If it says no device is found, see §5.

4. Start recording:

   ```bat
   python tools/record_fixture.py
   ```

5. For each entry the tool prints an instruction, for example:

   ```
   [cross] Hold cross (X); release the rest
     Hold it, then press Enter (keep holding during capture); s to skip:
   ```

   **Hold** the requested input, then press Enter and keep holding while the
   tool samples (~2 s). It picks the report that best matches the intended
   input and writes `tests/fixtures/dualsense_input/<id>.json`. It prints the
   captured buttons and warns if the expected value was not seen.
   Type `s` + Enter to skip an entry. `Ctrl+C` stops.

6. Repeat for all entries. Useful variants:

   ```bat
   python tools/record_fixture.py --only cross        :: record one entry
   python tools/record_fixture.py --force             :: re-record all
   python tools/record_fixture.py --outdir C:\tmp\fix :: write elsewhere
   ```

### 2.2 Run the fixture test

```bat
python -m unittest tests.test_protocol_fixtures -v
```

The fixture test runs against every recorded capture (it skips only when the
directory is empty). A failure means the decoder disagrees with the real
device — report which fixture failed.

### 2.3 What to record

The checklist covers: all 19 buttons, the four D-pad directions, left/right
stick extremes, L2/R2 fully pressed, and the touchpad left/right halves. That
matches the fixtures required by `plan.md` §17.1.

---

## 3. Later hardware acceptance

Once the bridge (stage 3+) exists, the remaining manual checks are tracked in
the manual-test section of the planning docs and `plan.md` §17.1. Highlights:

- USB read/write, unplug/replug, sleep/wake reconnect
- `SendInput` into an elevated window
- release-all-keys on stop / disconnect
- device-busy detection (Steam / DSX)
- tray icon / menu / scheduled task without UAC
- opencode + OpenChamber end to end

---

## 4. Adding a new automated test

- Python: put `test_*.py` under `tests/`, use stdlib `unittest`. Pure logic
  only; inject fakes for HID / `SendInput`.
- Node: `*.test.mjs` under `tests/`, run by `node --test`.

---

## 5. Troubleshooting

| Symptom | Fix |
|---|---|
| `No DualSense found over USB` | Reconnect over USB, press PS to wake. Bluetooth is not supported. |
| Device found but no reports | Another app (Steam / DSX) may hold it; close it and retry. Writing output needs admin, reading does not. |
| Fixture test still skipped | No `*.json` in `tests/fixtures/dualsense_input/`; run the recorder. |
| `pip install -e .` fails | Ensure Python 3.10+ and network access for the build backend. |
