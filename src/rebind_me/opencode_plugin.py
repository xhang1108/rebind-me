"""Install the Rebind Me plugin into an OpenCode 2 configuration.

OpenCode 2 loads local plugins from ``~/.config/opencode/plugins/`` and reads
published packages from the ``plugins`` array in the global configuration.
The installer supports both routes while keeping them mutually exclusive:

* **npm** (preferred, once a V2-compatible release is published): put
  ``rebind-me`` in ``plugins``.
* **local** (the current development route): copy the plugin entry and its
  helpers into ``~/.config/opencode/plugins/``.

A legacy OpenCode 1 ``plugin`` entry is migrated or removed when the installer
runs. Nothing here touches the filesystem or network at import time: paths,
the registry probe, and the publication decision are injectable for tests.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from pathlib import Path
from typing import Callable, Mapping, Sequence

PLUGIN_PACKAGE = "rebind-me"
PLUGIN_CONFIG_KEY = "plugins"
LEGACY_PLUGIN_CONFIG_KEY = "plugin"
MIN_OPENCODE_VERSION = "2.0.15"

# Name written into the opencode plugins directory (auto-discovered) and the
# namespaced helpers it imports. The helpers keep the generic repo filenames out
# of the shared directory and are ``.mjs``, so opencode never loads them.
ENTRY_NAME = "rebind-me.ts"
EVENTS_NAME = "rebind-me-events.mjs"
BRIDGE_NAME = "rebind-me-bridge.mjs"

# Source files inside the repo's ``plugin/`` directory.
SOURCE_ENTRY = "index.ts"
SOURCE_EVENTS = "events.mjs"
SOURCE_BRIDGE = "bridge.mjs"

# Rewrite the entry's relative imports to the namespaced copies.
IMPORT_REWRITES = {
    "./events.mjs": f"./{EVENTS_NAME}",
    "./bridge.mjs": f"./{BRIDGE_NAME}",
}

REGISTRY_URL = "https://registry.npmjs.org/rebind-me"
# Do not select an older published package that still contains the V1 plugin
# shape. The local checkout remains the safe development route until a matching
# OpenCode 2 release is published.
MIN_PUBLISHED_PLUGIN_VERSION = "0.2.0"
RESTART_HINT = "Reload OpenCode 2 / OpenChamber 2 to load the plugin."


def repo_plugin_dir(env: Mapping[str, str] | None = None) -> Path:
    """The checkout's ``plugin/`` directory, or ``REBIND_ME_PLUGIN_DIR``."""
    env = os.environ if env is None else env
    override = (env.get("REBIND_ME_PLUGIN_DIR") or "").strip()
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2] / "plugin"


def config_dir(env: Mapping[str, str] | None = None) -> Path:
    """OpenCode's global config directory.

    OpenCode 2 accepts an explicit ``OPENCODE_CONFIG_DIR``; honor it before
    falling back to the platform's XDG-style location.
    """
    env = os.environ if env is None else env
    override = (env.get("OPENCODE_CONFIG_DIR") or "").strip()
    if override:
        return Path(override)
    base = (env.get("XDG_CONFIG_HOME") or "").strip()
    root = Path(base) if base else Path.home() / ".config"
    return root / "opencode"


def _version_at_least(version: object, minimum: str) -> bool:
    """Compare the simple numeric SemVer form used by npm package releases."""
    if not isinstance(version, str):
        return False
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$", version.strip())
    required = re.match(r"^(\d+)\.(\d+)\.(\d+)$", minimum)
    if not match or not required:
        return False
    current = tuple(int(part) for part in match.groups())
    floor = tuple(int(part) for part in required.groups())
    return current >= floor


def npm_published(
    timeout: float = 1.5, urlopen_func: Callable[..., object] | None = None
) -> bool:
    """Return whether npm has a release new enough for the V2 installer.

    A package can exist under the same name while its latest release still be
    the old V1 plugin. Treat that as unpublished for this installer and fall
    back to the local copy. Small injected response objects used by callers that
    predate the metadata check remain supported; a real HTTP response is parsed.
    """
    opener = urlopen_func or urllib.request.urlopen
    try:
        with opener(REGISTRY_URL, timeout=timeout) as response:
            if int(getattr(response, "status", 200)) != 200:
                return False
            read = getattr(response, "read", None)
            if not callable(read):
                return True
            payload = read()
            if isinstance(payload, bytes):
                payload = payload.decode("utf-8")
            metadata = json.loads(payload)
            latest = metadata.get("dist-tags", {}).get("latest")
            if latest is None:
                latest = metadata.get("version")
            return _version_at_least(latest, MIN_PUBLISHED_PLUGIN_VERSION)
    except Exception:  # noqa: BLE001 - offline, missing, or blocked all mean "no"
        return False


def _array_pattern(key: str) -> re.Pattern[str]:
    return re.compile(rf'"{re.escape(key)}"\s*:\s*\[(.*?)\]', re.DOTALL)


def _plugin_array_pattern() -> re.Pattern[str]:
    """Return the active OpenCode 2 plugin-array matcher."""
    return _array_pattern(PLUGIN_CONFIG_KEY)


def _array_entry_count(text: str, key: str, package: str) -> int:
    match = _array_pattern(key).search(text)
    if not match:
        return 0
    return len(
        re.findall(
            rf'"{re.escape(package)}"(?=\s*(?:,|$))',
            match.group(1),
        )
    )


def _array_contains(text: str, key: str, package: str) -> bool:
    return _array_entry_count(text, key, package) > 0


def _remove_array_entry(text: str, key: str, package: str) -> tuple[str, bool]:
    match = _array_pattern(key).search(text)
    if not match:
        return text, False

    content = match.group(1)
    quoted = re.escape(f'"{package}"')
    removed = False
    while True:
        for pattern in (
            rf"\s*,\s*{quoted}",
            rf"{quoted}\s*,",
            quoted,
        ):
            updated, count = re.subn(pattern, "", content, count=1)
            if count:
                content = updated
                removed = True
                break
        else:
            break

    if not removed:
        return text, False

    return text[: match.start(1)] + content + text[match.end(1) :], True


def _insert_array_entry(text: str, key: str, package: str) -> str:
    match = _array_pattern(key).search(text)
    entry = f'"{package}"'
    if not match:
        brace = text.find("{")
        if brace < 0:
            raise ValueError("OpenCode config does not contain a JSON object")
        return text[: brace + 1] + f'\n  "{key}": [{entry}],' + text[brace + 1 :]

    content = match.group(1)
    if not content.strip():
        insertion = f"\n    {entry}"
    elif content[:1].isspace():
        insertion = f"\n    {entry},"
    else:
        insertion = f"\n    {entry},\n    "
    return text[: match.start(1)] + insertion + text[match.start(1) :]


class OpenCodePluginInstaller:
    """Install, remove or inspect the plugin in the global OpenCode config."""

    def __init__(
        self,
        config_dir_path: str | os.PathLike[str] | None = None,
        source_dir: str | os.PathLike[str] | None = None,
        published: Callable[[], bool] | None = None,
    ):
        self.config_dir = Path(config_dir_path) if config_dir_path else config_dir()
        self.plugins_dir = self.config_dir / "plugins"
        self.source_dir = Path(source_dir) if source_dir else repo_plugin_dir()
        self._published = published or npm_published

    # -- discovery --------------------------------------------------------
    def config_file(self) -> Path:
        """The config to edit: an existing JSON/JSONC file, else ``opencode.json``."""
        for name in ("opencode.json", "opencode.jsonc"):
            candidate = self.config_dir / name
            if candidate.is_file():
                return candidate
        return self.config_dir / "opencode.json"

    def local_files(self) -> dict[str, Path]:
        return {
            ENTRY_NAME: self.plugins_dir / ENTRY_NAME,
            EVENTS_NAME: self.plugins_dir / EVENTS_NAME,
            BRIDGE_NAME: self.plugins_dir / BRIDGE_NAME,
        }

    def local_installed(self) -> bool:
        return all(path.is_file() for path in self.local_files().values())

    def npm_installed(self) -> bool:
        return _array_contains(self._read_config(), PLUGIN_CONFIG_KEY, PLUGIN_PACKAGE)

    def legacy_npm_installed(self) -> bool:
        return _array_contains(
            self._read_config(), LEGACY_PLUGIN_CONFIG_KEY, PLUGIN_PACKAGE
        )

    def installed(self) -> bool:
        return self.npm_installed() or self.legacy_npm_installed() or self.local_installed()

    def status(self) -> dict:
        legacy = self.legacy_npm_installed()
        if self.npm_installed():
            mode = "npm"
        elif self.local_installed():
            mode = "local"
        elif legacy:
            mode = "legacy"
        else:
            mode = None
        return {
            "installed": mode is not None,
            "mode": mode,
            "package": PLUGIN_PACKAGE,
            "config": str(self.config_file()),
            "configKey": PLUGIN_CONFIG_KEY,
            "minimumOpenCodeVersion": MIN_OPENCODE_VERSION,
            "legacyEntry": legacy,
            "pluginsDir": str(self.plugins_dir),
            "source": str(self.source_dir),
            "restartHint": RESTART_HINT,
        }

    # -- install / remove -------------------------------------------------
    def install(self, mode: str | None = None) -> dict:
        """Install via npm when published, otherwise from the local checkout.

        ``mode`` may be ``"npm"`` or ``"local"`` to force one route.
        """
        if mode is None:
            mode = "npm" if self._published() else "local"
        # Exactly one route at a time: OpenCode would load a local copy and
        # the npm package as two separate plugins and report every event twice.
        if mode == "npm":
            changed = self._write_npm_entry()
            changed = self._delete_local_files() or changed
        elif mode == "local":
            changed = self._write_local_files()
            changed = self._remove_npm_entry() or changed
        else:
            raise ValueError(f"unknown install mode: {mode}")
        return dict(self.status(), action="install", changed=changed, restartHint=RESTART_HINT)

    def uninstall(self) -> dict:
        """Remove both npm entries and any local files (both are idempotent)."""
        changed = self._remove_npm_entry()
        changed = self._delete_local_files() or changed
        return dict(self.status(), action="uninstall", changed=changed, restartHint=RESTART_HINT)

    # -- npm route --------------------------------------------------------
    def _read_config(self) -> str:
        path = self.config_file()
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return ""

    def _write_npm_entry(self) -> bool:
        path = self.config_file()
        text = self._read_config()
        text, legacy_removed = _remove_array_entry(
            text, LEGACY_PLUGIN_CONFIG_KEY, PLUGIN_PACKAGE
        )

        active_count = _array_entry_count(text, PLUGIN_CONFIG_KEY, PLUGIN_PACKAGE)
        if active_count > 1:
            text, _ = _remove_array_entry(text, PLUGIN_CONFIG_KEY, PLUGIN_PACKAGE)
            text = _insert_array_entry(text, PLUGIN_CONFIG_KEY, PLUGIN_PACKAGE)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            return True

        if active_count == 1:
            if not legacy_removed:
                return False
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            return True

        if not text.strip():
            text = f'{{\n  "{PLUGIN_CONFIG_KEY}": ["{PLUGIN_PACKAGE}"]\n}}\n'
        else:
            text = _insert_array_entry(text, PLUGIN_CONFIG_KEY, PLUGIN_PACKAGE)

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return True

    def _remove_npm_entry(self) -> bool:
        path = self.config_file()
        text = self._read_config()
        text, active_removed = _remove_array_entry(
            text, PLUGIN_CONFIG_KEY, PLUGIN_PACKAGE
        )
        text, legacy_removed = _remove_array_entry(
            text, LEGACY_PLUGIN_CONFIG_KEY, PLUGIN_PACKAGE
        )
        changed = active_removed or legacy_removed
        if changed:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        return changed

    # -- local route ------------------------------------------------------
    def _entry_source(self) -> str:
        text = (self.source_dir / SOURCE_ENTRY).read_text(encoding="utf-8")
        for old, new in IMPORT_REWRITES.items():
            text = text.replace(old, new)
        return text

    def _write_local_files(self) -> bool:
        target = self.local_files()
        contents = {
            ENTRY_NAME: self._entry_source().encode("utf-8"),
            EVENTS_NAME: (self.source_dir / SOURCE_EVENTS).read_bytes(),
            BRIDGE_NAME: (self.source_dir / SOURCE_BRIDGE).read_bytes(),
        }
        changed = False
        self.plugins_dir.mkdir(parents=True, exist_ok=True)
        for name, blob in contents.items():
            path = target[name]
            if not path.is_file() or path.read_bytes() != blob:
                path.write_bytes(blob)
                changed = True
        return changed

    def _delete_local_files(self) -> bool:
        changed = False
        for path in self.local_files().values():
            if path.is_file():
                path.unlink()
                changed = True
        return changed


def main(argv: Sequence[str] | None = None) -> int:
    """CLI used by ``install.cmd`` / the UI: ``install``, ``uninstall``, ``status``."""
    args = list(sys.argv[1:] if argv is None else argv)
    action = args[0] if args else "status"
    if "--local" in args or "-l" in args:
        mode = "local"
    elif "--npm" in args:
        mode = "npm"
    else:
        mode = None
    installer = OpenCodePluginInstaller()

    if action == "install":
        result = installer.install(mode)
    elif action == "uninstall":
        result = installer.uninstall()
    elif action == "status":
        result = installer.status()
    else:
        print(f"unknown plugin action: {action}", file=sys.stderr)
        return 2

    print(json.dumps(result, indent=2))
    return 0


__all__ = [
    "BRIDGE_NAME",
    "ENTRY_NAME",
    "EVENTS_NAME",
    "IMPORT_REWRITES",
    "LEGACY_PLUGIN_CONFIG_KEY",
    "MIN_OPENCODE_VERSION",
    "MIN_PUBLISHED_PLUGIN_VERSION",
    "OpenCodePluginInstaller",
    "PLUGIN_CONFIG_KEY",
    "PLUGIN_PACKAGE",
    "RESTART_HINT",
    "config_dir",
    "main",
    "npm_published",
    "repo_plugin_dir",
]
