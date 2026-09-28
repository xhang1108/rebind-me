# Rebind Me

A **DualSense** controller remapper for Windows 11. Map any button, stick or
touchpad input to whatever you want — global keyboard and mouse input, the
light bar, adaptive triggers. You decide the mapping.

The only thing we special-case is **OpenCode 2** and **OpenChamber 2**: their
shortcuts and a few special behaviours, above all the **status light** that
reflects your OpenCode session state on the controller. The plugin is aligned
with the OpenCode 2 / OpenChamber 2 plugin API — `setup(ctx)` plus the public
event stream — and reports the four light states `error > approval > working >
idle` from `session.execution.*`, with `permission` / `form` requests holding
`approval` until they settle. OpenCode 1.x hooks are not supported.

- **Standard library only** — no third-party runtime dependencies.
- **USB only**, single controller.
- **Portable** — a source checkout plus `.cmd` launchers; no installer.
- **OpenCode 2 / OpenChamber 2 aligned** — V2 plugin API only.

> DualSense is a trademark of Sony Interactive Entertainment. This project is
> not affiliated with or endorsed by Sony.

## Requirements

- Windows 11 (x64)
- Python 3.10 or newer
- A DualSense controller connected over USB

## Quick start

### Install (recommended, once)

1. Right-click `install.cmd` and choose **Run as administrator** (one time).
   This registers the elevated bridge to start at startup, adds the tray to
   `HKCU\...\Run`, and starts the bridge immediately.
2. Use the tray icon (notification area): **Open UI**, or just visit
   <http://127.0.0.1:4173/> in a browser.

After that, start / stop / restart from the tray — no further UAC prompts.
To remove it later, right-click `uninstall.cmd` and run it as administrator.

### Install the OpenCode 2 / OpenChamber 2 plugin

The plugin reports OpenCode 2 session state to the bridge (controller light)
and powers the focus-terminal action. It supports OpenCode 2.0.15 or newer,
which is the runtime required by current OpenChamber 2.x. Double-click
`install-plugin.cmd`, or use the tray UI's **Integrations** tab, or run it
yourself:

```bat
python -m rebind_me plugin install
python -m rebind_me plugin status
python -m rebind_me plugin uninstall
```

When a V2-compatible package release (`0.2.0` or newer) is published on npm,
the installer adds `rebind-me` to the OpenCode 2 `plugins` array. Otherwise it
copies the plugin into `~/.config/opencode/plugins/`, where OpenCode 2 discovers
it automatically.
An old OpenCode 1 `plugin` entry is migrated or removed automatically. Reload
OpenCode 2 / OpenChamber 2 after installation. `uninstall-plugin.cmd` removes
the integration again.

### Run without installing (manual / development)

The bridge needs to write HID and inject input; an elevated terminal lets it
target elevated windows too.

```bat
rem terminal 1 (bridge) - open as administrator for full functionality
python -m rebind_me

rem terminal 2 (tray), or double-click run.cmd
run.cmd
```

Then open <http://127.0.0.1:4173/>. If the scheduled task already exists,
`run.cmd` starts the bridge for you instead of the manual command.

## Mappings

Any button, stick direction or touchpad zone can be bound to a target or to an
action. A target is a key sequence (up to two chords of up to five keys), a
mouse button, or a scroll direction. A mapping picks one of four modes:

| Mode | Behaviour |
|---|---|
| `single` | Fires once per press. |
| `hold` | Holds the target down while you hold the button, releases on let-go. |
| `toggle` | Holds the target down until you press the button again. |
| `repeat` | Fires repeatedly, either while held or until you stop it — see below. |

`hold` and `toggle` press the target and leave it pressed, so they are for keys
and mouse buttons. A scroll has no pressed state to hold down: in `hold` or
`toggle` it would fire once on activation and again on release, which is almost
never what you want. Scroll suits `single` or `repeat`.

### Repeat settings

| Setting | Meaning |
|---|---|
| **Delay ms** | How long after the first fire before the repeating begins. |
| **Timing** | `fixed` waits the same gap every time; `random` draws a fresh one on every fire. |
| **Every ms** | The gap between fires, shown when `Timing` is `fixed`. |
| **Random ms `X` to `Y`** | The window the gap is drawn from, shown when `Timing` is `random`. |
| **keep going after release** | Off: repeating stops when you let go. On: one press starts it and it keeps going until you stop it again. |

Random timing only jitters the gap *between* fires. **Delay ms** is always
exact, so "wait, then start" stays predictable.

The defaults are deliberately unhurried — 1000 ms delay, 1000 ms every, and a
random window of 800 to 1200 ms, which works out to roughly one fire per
second. A repeat mapping is usually driving something that counts requests, so
the defaults aim to stay inside a rate limit rather than risk tripping one.
Every setting is editable and accepts 10 to 2000 ms.

A latched repeat stops when you press the button again, when the master
**Enabled** toggle is switched off, when the controller disconnects, or when you
switch to a different window. That last one is the safety net for a repeat with
no timeout of its own: the app it was driving is no longer in front, so it is
stopped rather than left running behind you. It has to be started again with a
fresh press.

`repeat` does nothing on a touchpad *tap* — a tap is a press and release in the
same instant, so there is no hold to repeat. Use `touchpad_click_left` /
`touchpad_click_right` for a repeating touchpad input.

## Development

```bat
python -m pip install -e .
python -m unittest discover -s tests -v
node --test
```

See [DEVELOPMENT.md](DEVELOPMENT.md) for the module layout, the HID wire format
([PROTOCOL.md](PROTOCOL.md)), fixtures and the plugin internals.

## License

MIT — see [LICENSE](LICENSE). Third-party acknowledgements are in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
