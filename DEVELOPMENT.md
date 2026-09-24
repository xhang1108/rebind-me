# Development

```bat
python -m pip install -e .
python -m unittest discover -s tests -v
node --test
```

CI (`.github/workflows/ci.yml`) runs the same commands plus `compileall`,
`node --check` and the plugin typecheck.

## Module layout

```
src/rebind_me/
├─ __main__.py         # CLI: bridge (default) / tray / autostart / plugin
├─ bridge.py           # wires HID + engine + API together
├─ protocol.py         # input decode / output encode
├─ hid.py              # device enumeration / I/O / reconnect
├─ engine.py           # mapping engine
├─ actions.py          # action handlers (incl. focus-terminal)
├─ lighting.py         # status light / manual override
├─ triggers.py         # adaptive triggers
├─ touchpad.py         # touchpad zones
├─ keys.py  keycapture.py
├─ store.py            # persisted settings + schema
├─ autostart.py        # scheduled task + HKCU Run wiring
├─ opencode_plugin.py  # install / uninstall the OpenCode 2 plugin
├─ api.py              # HTTP + static
├─ tray.py             # notification-area icon
├─ winapi/             # ctypes Win32 bindings
└─ ui/                 # index.html / app.js / model.js / styles.css
plugin/                # OpenCode 2 npm package (index.ts / events.mjs / bridge.mjs)
tests/                 # unittest + node --test
tools/                 # helpers: bridge_api.py, record_fixture.py, ...
```

## Protocol and fixtures

The DualSense USB HID wire format (input/output offsets, bit fields, trigger
encoding) is documented in [PROTOCOL.md](PROTOCOL.md). Recorded input fixtures
live in `tests/fixtures/dualsense_input/`; see its README for the format and how
to capture them from a real controller (`tools/record_fixture.py`).

## OpenCode 2 / OpenChamber 2 plugin

The plugin lives in `plugin/` and is an OpenCode 2 definition with a stable
`id` and `setup(ctx)` lifecycle. It subscribes to the public event stream with
`ctx.event.subscribe()` and reports the bridge's `idle`, `working`, `approval`
or `error` state. The event mapper tracks execution phase plus namespaced
permission/form request IDs so multiple approval prompts remain visible until
all of them settle. OpenCode 1 plugin hooks are intentionally not supported.

The V2 event shapes are tested in `tests/plugin.test.mjs`; the installer
migration from the legacy `plugin` config key to `plugins` is tested in
`tests/test_opencode_plugin.py`. The local plugin uses a type-only
`@opencode/plugin` import so the copied source does not need a separate runtime
package installation. Run `npm ci` in `plugin/` before `npm run typecheck`.

## Console commands

The tray and the startup autostart can be driven from a console:

```bat
python -m rebind_me tray
python -m rebind_me autostart status
python -m rebind_me autostart enable
python -m rebind_me plugin status
```
