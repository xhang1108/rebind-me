# DualSense USB HID Protocol

Wire reference for the Rebind Me protocol layer (`src/rebind_me/protocol.py`).
All offsets are into the **full report**, i.e. index `0` is the report ID.

Facts below were established from public community reverse-engineering; see
[References](#references).

- **USB only.** Bluetooth is out of scope.
- **Input report ID `0x01`** (handle reads 64 bytes on Windows).
- **Output report ID `0x02`**, 48 bytes including the report ID.
- Interface selection uses HID caps, not report IDs:
  `OutputReportByteLength == 48` and `InputReportByteLength >= 11`.

## 1. Input report `0x01`

| Offset | Bytes | Field | Notes |
|---|---|---|---|
| 0 | 1 | Report ID | Must be `0x01` |
| 1 | 1 | Left stick X | `0..255`, neutral `128` |
| 2 | 1 | Left stick Y | `0..255` |
| 3 | 1 | Right stick X | `0..255` |
| 4 | 1 | Right stick Y | `0..255` |
| 5 | 1 | L2 analog | `0..255` |
| 6 | 1 | R2 analog | `0..255` |
| 7 | 1 | Sequence | Increments per frame; not used |
| 8 | 1 | Face / D-pad | see §1.1 |
| 9 | 1 | Shoulders / sticks | see §1.2 |
| 10 | 1 | System buttons | see §1.3 |
| 11..15 | 5 | Reserved | |
| 16..21 | 6 | Accelerometer X/Y/Z | int16 LE (unused) |
| 22..27 | 6 | Gyro pitch/yaw/roll | int16 LE (unused) |
| 28..32 | 5 | Reserved | |
| 33..36 | 4 | Touch point 0 | see §1.4 |
| 37..40 | 4 | Touch point 1 | see §1.4 |
| 41..42 | 2 | Reserved | |
| 42 | 1 | Right trigger effect status | high nibble (read-only) |
| 43 | 1 | Left trigger effect status | high nibble (read-only) |
| 53 | 1 | Battery | high nibble state, low nibble level (unused) |

### 1.1 Byte 8 — face buttons and D-pad

- Bits `4..7`: `square`, `cross`, `circle`, `triangle` (`1` = pressed).
- Bits `0..3`: D-pad direction value.

| Value | Up | Right | Down | Left |
|---|---|---|---|---|
| 0 | x | | | |
| 1 | x | x | | |
| 2 | | x | | |
| 3 | | x | x | |
| 4 | | | x | |
| 5 | | | x | x |
| 6 | | | | x |
| 7 | x | | | x |
| 8 | | | | | (released) |

### 1.2 Byte 9 — shoulders, triggers and stick clicks

| Bit | Button |
|---|---|
| 0 | L1 |
| 1 | R1 |
| 2 | L2 (digital) |
| 3 | R2 (digital) |
| 4 | Create |
| 5 | Options |
| 6 | L3 (left stick click) |
| 7 | R3 (right stick click) |

### 1.3 Byte 10 — system buttons

| Bit | Button |
|---|---|
| 0 | PS |
| 1 | Touchpad click |
| 2 | Mute |

DualSense Edge adds L4/R4 (bits 4/5) and L5/R5 (bits 6/7) here. Edge is out of
scope.

### 1.4 Touch points (two identical 4-byte blocks at 33 and 37)

| Block offset | Field |
|---|---|
| +0 | bit 7: `1` = inactive; bits `0..6`: contact ID |
| +1 | X low 8 bits |
| +2 | low nibble: X high 4 bits; high nibble: Y low 4 bits |
| +3 | Y high 8 bits |

`X = ((block[2] & 0x0F) << 8) | block[1]` is 12-bit `0..1919`.
`Y = (block[3] << 4) | (block[2] >> 4)` is 12-bit `0..1079`.
Rebind Me reads only the first active point.

### Normalization used by the bridge

- Sticks: `(value - 127.5) / 127.5`, clamped to `-1.0..1.0` (neutral ≈ 0).
- Triggers: `value / 255`, `0.0..1.0`.

## 2. Output report `0x02` (48 bytes)

| Offset | Bytes | Field | Notes |
|---|---|---|---|
| 0 | 1 | Report ID | `0x02` |
| 1 | 1 | Valid flag 0 | see §2.1 |
| 2 | 1 | Valid flag 1 | see §2.2 |
| 3 | 1 | Right motor | `0..255` |
| 4 | 1 | Left motor | `0..255` |
| 5..8 | 4 | Audio | unused |
| 9 | 1 | Mic LED | `0x01` = LED on, `0x00` = off |
| 10 | 1 | Power save | bit `0x10` = hardware mic mute |
| 11..21 | 11 | Right trigger effect | see §2.3 |
| 22..32 | 11 | Left trigger effect | see §2.3 |
| 33..42 | 10 | Reserved | |
| 43 | 1 | LED brightness | `0`=off, `1`=low, `2`=medium, `3`=high |
| 44 | 1 | Player LEDs | 5 bits, `0x00..0x1F` |
| 45 | 1 | Lightbar red | `0..255` |
| 46 | 1 | Lightbar green | `0..255` |
| 47 | 1 | Lightbar blue | `0..255` |

### 2.1 Valid flag 0 (byte 1)

| Bit | Meaning |
|---|---|
| `0x01` | Compatible vibration (motors) |
| `0x02` | Haptics select |
| `0x04` | Right trigger effect |
| `0x08` | Left trigger effect |

Motor updates set `0x01 | 0x02`. Trigger updates set `0x04 | 0x08`.

### 2.2 Valid flag 1 (byte 2)

| Bit | Meaning |
|---|---|
| `0x01` | Mic mute LED |
| `0x02` | Power save (mic mute) |
| `0x04` | Lightbar |
| `0x10` | Player LEDs |

Steady state uses `0x01 | 0x02 | 0x04 | 0x10` = `0x17`.

Brightness bucket: `100` maps to `3`. `brightness == 0 → 0`,
`< 34 → 1`, `< 67 → 2`, otherwise `3`.

Mic LED: with `micLedInvert = true`, the LED is on while the mic is **live**
and off while muted (an "on air" light). With `false`, the stock convention
(on while muted) applies.

### 2.3 Adaptive trigger effect block (11 bytes)

| Offset | Field |
|---|---|
| 0 | Effect mode |
| 1 | Parameter byte 0 |
| 2 | Parameter byte 1 |
| 3 | Parameter byte 2 |
| 4 | Parameter byte 3 |
| 5 | Parameter byte 4 |
| 6 | Parameter byte 5 |
| 7 | `0` |
| 8 | `0` |
| 9 | Parameter byte 6 |
| 10 | `0` |

Rebind Me freezes three modes:

**Off — `0x00`.** All bytes zero.

**Weapon — `0x25`.** `start` (2..7) and `end` (start<end≤8) select two
breakpoints, `strength` (1..8):

```
param0..1 = little_endian((1 << start) | (1 << end))
param2    = strength - 1
```

**Feedback — `0x21`.** `start` (0..9) and `strength` (1..8). Travel is split
into ten 3-bit force zones. Zones `start..9` are active and share the same
3-bit force `strength - 1`:

```
active_zones = ((1 << (10 - start)) - 1) << start
force_zones  = sum((strength - 1) << (zone * 3) for zone in range(start, 10))
param0..1    = little_endian_16(active_zones)
param2..5    = little_endian_32(force_zones)
```

### Golden vectors

| Mode | start | end | strength | Bytes |
|---|---|---|---|---|
| off | 3 | 6 | 5 | `00 00 00 00 00 00 00 00 00 00 00` |
| weapon | 3 | 6 | 5 | `25 48 00 04 00 00 00 00 00 00 00` |
| weapon | 2 | 8 | 8 | `25 04 01 07 00 00 00 00 00 00 00` |
| feedback | 3 | – | 5 | `21 f8 03 00 48 92 24 00 00 00 00` |
| feedback | 0 | – | 8 | `21 ff 03 ff ff ff 3f 00 00 00 00` |

## References

The report layout, button bits and trigger effect encodings above are protocol
facts established from public community reverse-engineering of the DualSense.
These projects are cited as the sources of those facts:

| Project | Upstream |
|---|---|
| `LYiHub/pub-ai-inputs` (`PS5 DualSense`) | github.com/LYiHub/pub-ai-inputs |
| Linux kernel `hid-playstation.c` | torvalds/linux |
| `nondebug/dualsense` | github.com/nondebug/dualsense |
| `flok/pydualsense` | github.com/flok/pydualsense |
| `DS5W` | github.com/Ohjurot/DS5W |
| `dualsense-ts` | github.com/nsfm/dualsense-ts |
| SDL `SDL_hidapi_ps5.c` | libsdl-org/SDL |
