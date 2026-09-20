"""Install the Rebind Me plugin into the user's opencode configuration.

opencode has two ways to load a plugin, and this covers both:

* **npm** (preferred, once published): put ``rebind-me`` in the
  ``plugin`` array of the global ``opencode.json`` / ``opencode.jsonc``. opencode
  downloads it with Bun on the next start.
* **local** (fallback, and the only option while the package is unpublished):
  copy the plugin into ``~/.config/opencode/plugins/``. opencode auto-loads every
  ``*.ts`` / ``*.js`` file directly inside that directory, so the entry is
  written as ``rebind-me.ts``; its ``.mjs`` helpers are imported, and are never
  scanned as plugins themselves.

Nothing here touches the filesystem or the network at import time: every path,
the registry check and the "is it published" decision are injectable, so the
whole flow is unit-tested without a config directory or a live registry.
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

# Name written into the opencode plugins directory (auto-discovered) and the
# namespaced helpers it imports. The helpers keep the generic repo filenames out
# of the shared directory and are `.mjs`, so opencode never loads them directly.
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
RESTART_HINT = "Restart opencode for the plugin to load."


def repo_plugin_dir(env: Mapping[str, str] | None = None) -> Path:
    """The checkout's ``plugin/`` directory, or ``REBIND_ME_PLUGIN_DIR``."""
    env = os.environ if env is None else env
    override = (env.get("REBIND_ME_PLUGIN_DIR") or "").strip()
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2] / "plugin"


def config_dir(env: Mapping[str, str] | None = None) -> Path:
    """opencode's global config directory (``~/.config/opencode``)."""
    env = os.environ if env is None else env
    base = (env.get("XDG_CONFIG_HOME") or "").strip()
    root = Path(base) if base else Path.home() / ".config"
    return root / "opencode"


def npm_published(
    timeout: float = 1.5, urlopen_func: Callable[..., object] | None = None
) -> bool:
    """Best-effort check that ``PLUGIN_PACKAGE`` exists on the npm registry."""
    opener = urlopen_func or urllib.request.urlopen
    try:
        with opener(REGISTRY_URL, timeout=timeout) as response:
            return int(getattr(response, "status", 200)) == 200
    except Exception:  # noqa: BLE001 - offline, missing, or blocked all mean "no"
        return False


def _plugin_array_pattern() -> re.Pattern[str]:
    return re.compile(r'"plugin"\s*:\s*\[(.*?)\]', re.DOTALL)


class OpenCodePluginInstaller:
    """Install, remove or inspect the plugin in the global opencode config."""

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
        text = self._read_config()
        match = _plugin_array_pattern().search(text)
        if match:
            return PLUGIN_PACKAGE in match.group(1)
        return False

    def installed(self) -> bool:
        return self.npm_installed() or self.local_installed()

    def status(self) -> dict:
        mode = None
        if self.npm_installed():
            mode = "npm"
        elif self.local_installed():
            mode = "local"
        return {
            "installed": mode is not None,
            "mode": mode,
            "package": PLUGIN_PACKAGE,
            "config": str(self.config_file()),
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
        # Exactly one route at a time: opencode would load a local copy and the
        # npm package as two separate plugins and fire every hook twice.
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
        """Remove both the npm entry and any local files (both are idempotent)."""
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
        if self.npm_installed():
            return False
        if not text.strip():
            text = f'{{\n  "plugin": ["{PLUGIN_PACKAGE}"]\n}}\n'
        else:
            array = _plugin_array_pattern().search(text)
            entry = f'"{PLUGIN_PACKAGE}"'
            if array:
                existing = array.group(1)
                if existing.strip():
                    separator = "" if existing[:1].isspace() else "\n    "
                    inserted = f"\n    {entry},{separator}"
                else:
                    inserted = f"\n    {entry}"
                text = text[: array.start(1)] + inserted + text[array.start(1) :]
            else:
                brace = text.find("{")
                insertion = f'\n  "plugin": [{entry}],'
                text = text[: brace + 1] + insertion + text[brace + 1 :]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return True

    def _remove_npm_entry(self) -> bool:
        path = self.config_file()
        text = self._read_config()
        if PLUGIN_PACKAGE not in text:
            return False
        quoted = re.escape(f'"{PLUGIN_PACKAGE}"')
        for pattern in (rf"\s*,\s*{quoted}", rf"{quoted}\s*,", quoted):
            removed, count = re.subn(pattern, "", text, count=1)
            if count:
                text = removed
                break
        path.write_text(text, encoding="utf-8")
        return True

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
    "OpenCodePluginInstaller",
    "PLUGIN_PACKAGE",
    "RESTART_HINT",
    "config_dir",
    "main",
    "npm_published",
    "repo_plugin_dir",
]
