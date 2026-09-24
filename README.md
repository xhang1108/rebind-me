# Rebind Me

A **DualSense** controller remapper for Windows 11. Map any button, stick or
touchpad input to whatever you want — global keyboard and mouse input, the
light bar, adaptive triggers. You decide the mapping.

The only thing we special-case is **OpenCode 2** and **OpenChamber 2**: their
shortcuts and a few special behaviours, above all the **status light** that
reflects your OpenCode session state on the controller.

- **Standard library only** — no third-party runtime dependencies.
- **USB only**, single controller.
- **Portable** — a source checkout plus `.cmd` launchers; no installer.

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
