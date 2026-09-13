# Rebind Me

Use a **DualSense** controller as a local input remapper on Windows 11. Read
buttons, sticks and the touchpad, map them to global keyboard / mouse input,
drive the light bar and adaptive triggers, and integrate with opencode status
lighting and OpenChamber window focus.

- **Standard library only** — no third-party runtime dependencies.
- **USB only**, single controller.
- **Portable** — a source checkout plus `.cmd` launchers; no installer.

> DualSense is a trademark of Sony Interactive Entertainment. This project is
> not affiliated with or endorsed by Sony.

## Requirements

- Windows 11 (x64)
- Python 3.10 or newer
- A DualSense controller connected over USB

## Layout

```
rebind-me/
├─ pyproject.toml
├─ run.cmd                    # manual normal-privilege start (tray)
├─ install.cmd                # one-time elevated install
├─ uninstall.cmd              # remove scheduled task + HKCU Run
├─ rebind-me.pyw              # logon launcher (no console window)
├─ src/rebind_me/
│  ├─ __main__.py  tray.py
│  ├─ protocol.py             # input decode / output encode
│  ├─ hid.py                  # device enumeration / I/O / reconnect
│  ├─ winapi/                 # ctypes Win32 bindings
│  ├─ engine.py               # mapping engine
│  ├─ actions.py              # action handlers
│  ├─ lighting.py  triggers.py
│  ├─ api.py                  # HTTP + static
│  └─ ui/                     # index.html / app.js / styles.css
├─ plugin/                    # opencode npm package
├─ tests/                     # unittest + node --test
└─ .github/workflows/ci.yml
```

## Install

1. Get the source and make sure Python 3.10+ is on `PATH`.
2. Right-click `install.cmd` and choose **Run as administrator** (one time).
   It registers the elevated bridge scheduled task, writes the tray `HKCU\Run`
   entry, and starts the bridge.
3. After that, use the tray icon to start / stop / restart.

`install.cmd` and `uninstall.cmd` are the only steps that need elevation.

## Run manually

```bat
run.cmd
```

or, without the launcher:

```bat
python -m rebind_me
```

The UI is served at <http://127.0.0.1:4173/>.

## Development

```bat
python -m pip install -e .
python -m unittest discover -s tests -v
node --test
```

The DualSense USB HID wire format (input/output offsets, bit fields, trigger
encoding) is documented in [PROTOCOL.md](PROTOCOL.md). Recorded input
fixtures live in `tests/fixtures/dualsense_input/`; see its README for the
format and how to capture them from a real controller.

## Status

Early rewrite in progress. See `plan.md` for the full design and `TODO.md` for
the implementation checklist.

## License

MIT — see [LICENSE](LICENSE). Third-party acknowledgements are in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
