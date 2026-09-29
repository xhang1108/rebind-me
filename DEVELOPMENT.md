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

## Mapping store schema

`store.py` owns the persisted mapping/settings/preset documents and their
validators. Three things about it are easy to get wrong.

**`MAPPING_VERSION` is not a migration lever.** `validate_mapping_store()`
rejects any document whose `version` is not the current constant, and
`JsonStore.load()` responds to that rejection by writing `DEFAULT_MAPPING_STORE`
over the user's file. So bumping the constant does not migrate anyone's
mappings — it silently replaces them and is already on disk by the next start.
To add a field, make it an **optional key that is absent by default** and is
validated when present. That is why `random` and `latch` live inside `repeat`
as presence-based keys rather than as always-written booleans.

**Documents are canonical.** A validator drops optional keys that hold their
default (`latch: false` is never written), so a mapping that means the same
thing always has one representation. The editor marks the active preset by
comparing `mappingSignature()` over the working document against each stored
preset, so a working document that carried redundant keys would stop matching a
preset that had been through the validator, and the UI would fail to show it as
selected.

**Store constants are duplicated in `ui/model.js` on purpose.** The browser
cannot import Python, so the UI repeats `REPEAT_TIMINGS`, `REPEAT_MIN_MS`,
`REPEAT_MAX_MS` and the `DEFAULT_REPEAT_*` editor defaults. They drift silently
otherwise, so `tests/test_ui_contract.py` parses `model.js` and asserts each
one against `store.py`. If you change one side, change the other and let the
test tell you.

Repeat timing is drawn per fire through `MappingEngine(random_source=...)`, so
`tests/test_engine.py` can pin the random window instead of asserting against a
real `random.random()`. Tick times need margin: `tick()` tests
`deadline <= now` and a deadline is `now + interval`, and that sum is not always
exactly representable — `0.1 + 0.05` is `0.15000000000000002`, so a tick at the
nominal `0.15` does **not** fire. Assert a little past the boundary.

## Latched repeats and window focus

A repeat with `latch` keeps firing after the button is released and has no
timeout of its own. `MappingEngine.stop_latched()` is the single cancel path;
`bridge._stop_latched_on_focus_change()` decides when to call it. Three details
there are deliberate:

**Cancelling is a generation bump.** Clearing `latched` alone would not stop a
repeat whose button is still physically held, because the guard is
`pressed or latched`. Bumping the generation makes the pending `_repeat_fire`
callback drop itself, and nothing reschedules the chain, so a held button stays
quiet until it is released and pressed again.

**The foreground is only polled while something is latched.** `_on_report` runs
on every input report, so an unconditional `GetForegroundWindow` would be on the
hot path for the life of the process. The baseline window is recorded on the
first poll *after* a latch, not compared against a running last-seen value, so
the change that happened before the latch cannot be mistaken for one after it.

**A zero hwnd is ignored.** Focus is momentarily unowned while switching or
while a window is closing. Treating that as "the user left" would stop a repeat
that is still wanted. The same applies to the config UI taking focus — that is
itself leaving the app the repeat was driving, which is why the check sits
outside the `_ui_blocks_input` branch.

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

## Releasing

A release is one version bump. Edit **both** `pyproject.toml` and
`plugin/package.json` to the same `X.Y.Z` (two package managers, so the number
is written twice; `tests/test_release_contract.py` fails when they drift),
commit, and push to `main`. `.github/workflows/release.yml` then:

1. runs the Python and Node suites, and stops if either is red;
2. refuses to run when the two versions disagree, or when `v<version>` is
   already tagged (so an unrelated edit to `package.json` is a no-op);
3. publishes `rebind-me@<version>` to npm;
4. creates the tag `v<version>` and a GitHub Release with generated notes.

npm is published **before** the tag and the Release, because a tag advertises a
version; if the run dies in between, re-running detects the published version,
skips the publish and finishes the tag and Release. `workflow_dispatch` runs the
same job by hand.

Authentication is npm **Trusted Publishing** (OIDC): the job takes
`id-token: write` and `setup-node` is configured with `registry-url` but no
`NODE_AUTH_TOKEN`, so npm authenticates with the OIDC token. There is no npm
secret in the repository. This needs a one-time setup on npmjs.com: on the
package's *Trusted Publisher* page, add a GitHub Actions publisher for
repository `xhang1108/rebind-me` and workflow `release.yml` (leave the
environment blank). Until that is configured the publish step fails with an
authentication error; everything before it still runs.

