"""Tests for the opencode plugin installer (no real config dir, no registry)."""

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from rebind_me.opencode_plugin import (
    BRIDGE_NAME,
    ENTRY_NAME,
    EVENTS_NAME,
    PLUGIN_PACKAGE,
    OpenCodePluginInstaller,
    config_dir,
    main,
    npm_published,
    repo_plugin_dir,
)


class FakeResponse:
    def __init__(self, status: int) -> None:
        self.status = status

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> bool:
        return False


def make_source(root: Path) -> Path:
    src = root / "src-plugin"
    src.mkdir(exist_ok=True)
    (src / "index.ts").write_text(
        'import { mapEvent } from "./events.mjs";\n'
        'import { reportSession } from "./bridge.mjs";\n'
        "export default async () => ({});\n",
        encoding="utf-8",
    )
    (src / "events.mjs").write_text("export const mapEvent = () => null;\n", encoding="utf-8")
    (src / "bridge.mjs").write_text("export const reportSession = async () => false;\n", encoding="utf-8")
    return src


def installer_for(root: Path, published: bool = False) -> OpenCodePluginInstaller:
    return OpenCodePluginInstaller(
        config_dir_path=root / "config",
        source_dir=make_source(root),
        published=lambda: published,
    )


class DiscoveryTest(unittest.TestCase):
    def test_config_dir_honours_xdg(self) -> None:
        self.assertEqual(config_dir({"XDG_CONFIG_HOME": "C:\\xdg"}), Path("C:\\xdg") / "opencode")

    def test_repo_plugin_dir_has_the_entry(self) -> None:
        self.assertTrue((repo_plugin_dir() / "index.ts").is_file())

    def test_repo_plugin_dir_override(self) -> None:
        self.assertEqual(repo_plugin_dir({"REBIND_ME_PLUGIN_DIR": "C:\\x"}), Path("C:\\x"))

    def test_npm_published_reads_the_registry(self) -> None:
        self.assertTrue(npm_published(urlopen_func=lambda *a, **k: FakeResponse(200)))
        self.assertFalse(npm_published(urlopen_func=lambda *a, **k: FakeResponse(404)))

    def test_npm_published_is_false_when_offline(self) -> None:
        def boom(*args: object, **kwargs: object) -> object:
            raise OSError("offline")

        self.assertFalse(npm_published(urlopen_func=boom))


class CliTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source = make_source(self.root)
        self.env = {
            "XDG_CONFIG_HOME": str(self.root / "config"),
            "REBIND_ME_PLUGIN_DIR": str(self.source),
        }

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_status_on_empty_config(self) -> None:
        out = io.StringIO()
        with mock.patch.dict(os.environ, self.env), contextlib.redirect_stdout(out):
            self.assertEqual(main(["status"]), 0)
        self.assertIn('"installed": false', out.getvalue())

    def test_install_local_then_uninstall(self) -> None:
        with mock.patch.dict(os.environ, self.env), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["install", "--local"]), 0)
            plugins = self.root / "config" / "opencode" / "plugins"
            self.assertTrue((plugins / ENTRY_NAME).is_file())
            self.assertEqual(main(["uninstall"]), 0)
            self.assertFalse((plugins / ENTRY_NAME).exists())

    def test_unknown_action_exits_two(self) -> None:
        err = io.StringIO()
        with mock.patch.dict(os.environ, self.env), contextlib.redirect_stderr(err):
            self.assertEqual(main(["frobnicate"]), 2)
        self.assertIn("unknown plugin action", err.getvalue())


class LocalInstallTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.installer = installer_for(self.root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_status_before_install(self) -> None:
        status = self.installer.status()
        self.assertFalse(status["installed"])
        self.assertIsNone(status["mode"])
        self.assertEqual(status["package"], PLUGIN_PACKAGE)

    def test_install_local_copies_and_rewrites_imports(self) -> None:
        result = self.installer.install(mode="local")
        self.assertEqual(result["mode"], "local")
        self.assertTrue(result["changed"])
        self.assertTrue(self.installer.local_installed())

        plugins = self.installer.plugins_dir
        entry = (plugins / ENTRY_NAME).read_text(encoding="utf-8")
        self.assertIn("./rebind-me-events.mjs", entry)
        self.assertIn("./rebind-me-bridge.mjs", entry)
        self.assertNotIn("./events.mjs", entry)
        self.assertNotIn("./bridge.mjs", entry)
        self.assertTrue((plugins / EVENTS_NAME).is_file())
        self.assertTrue((plugins / BRIDGE_NAME).is_file())

    def test_install_local_is_idempotent(self) -> None:
        self.installer.install(mode="local")
        second = self.installer.install(mode="local")
        self.assertFalse(second["changed"])

    def test_uninstall_local_removes_files(self) -> None:
        self.installer.install(mode="local")
        result = self.installer.uninstall()
        self.assertTrue(result["changed"])
        self.assertFalse(self.installer.local_installed())

    def test_uninstall_when_nothing_is_installed(self) -> None:
        result = self.installer.uninstall()
        self.assertFalse(result["changed"])
        self.assertFalse(self.installer.installed())

    def test_installed_reflects_either_route(self) -> None:
        self.assertFalse(self.installer.installed())
        self.installer.install(mode="local")
        self.assertTrue(self.installer.installed())


class NpmInstallTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.installer = installer_for(self.root, published=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_auto_mode_prefers_npm_when_published(self) -> None:
        result = self.installer.install()
        self.assertEqual(result["mode"], "npm")
        self.assertTrue(self.installer.npm_installed())
        self.assertFalse(self.installer.local_installed())

    def test_auto_mode_falls_back_to_local(self) -> None:
        installer = installer_for(self.root, published=False)
        result = installer.install()
        self.assertEqual(result["mode"], "local")

    def test_creates_config_when_missing(self) -> None:
        self.installer.install(mode="npm")
        config = self.installer.config_file()
        self.assertEqual(config.name, "opencode.json")
        document = json.loads(config.read_text(encoding="utf-8"))
        self.assertIn(PLUGIN_PACKAGE, document["plugin"])

    def test_preserves_other_keys_and_plugins(self) -> None:
        config = self.installer.config_file()
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(
            json.dumps({"model": "x", "plugin": ["other-plugin"]}), encoding="utf-8"
        )
        self.installer.install(mode="npm")
        document = json.loads(config.read_text(encoding="utf-8"))
        self.assertEqual(document["model"], "x")
        self.assertEqual(document["plugin"], [PLUGIN_PACKAGE, "other-plugin"])

    def test_adds_plugin_key_when_absent(self) -> None:
        config = self.installer.config_file()
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(json.dumps({"model": "x"}), encoding="utf-8")
        self.installer.install(mode="npm")
        document = json.loads(config.read_text(encoding="utf-8"))
        self.assertEqual(document["model"], "x")
        self.assertEqual(document["plugin"], [PLUGIN_PACKAGE])

    def test_edits_existing_jsonc(self) -> None:
        config = self.installer.config_dir / "opencode.jsonc"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text('{\n  "plugin": []\n}\n', encoding="utf-8")
        self.installer.install(mode="npm")
        document = json.loads(config.read_text(encoding="utf-8"))
        self.assertEqual(document["plugin"], [PLUGIN_PACKAGE])

    def test_install_is_idempotent(self) -> None:
        self.installer.install(mode="npm")
        second = self.installer.install(mode="npm")
        self.assertFalse(second["changed"])
        document = json.loads(self.installer.config_file().read_text(encoding="utf-8"))
        self.assertEqual(document["plugin"].count(PLUGIN_PACKAGE), 1)

    def test_uninstall_leaves_valid_json(self) -> None:
        config = self.installer.config_file()
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(
            json.dumps({"plugin": [PLUGIN_PACKAGE, "other-plugin"]}), encoding="utf-8"
        )
        self.installer.uninstall()
        document = json.loads(config.read_text(encoding="utf-8"))
        self.assertEqual(document["plugin"], ["other-plugin"])

    def test_uninstall_removes_trailing_entry(self) -> None:
        config = self.installer.config_file()
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(
            json.dumps({"plugin": ["other-plugin", PLUGIN_PACKAGE]}), encoding="utf-8"
        )
        self.installer.uninstall()
        document = json.loads(config.read_text(encoding="utf-8"))
        self.assertEqual(document["plugin"], ["other-plugin"])

    def test_npm_install_removes_a_previous_local_copy(self) -> None:
        local = installer_for(self.root, published=False)
        local.install(mode="local")
        self.assertTrue(local.local_installed())
        local._published = lambda: True
        result = local.install()
        self.assertEqual(result["mode"], "npm")
        self.assertFalse(local.local_installed())
        self.assertTrue(local.npm_installed())

    def test_local_install_removes_a_previous_npm_entry(self) -> None:
        config = self.installer.config_file()
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(json.dumps({"plugin": [PLUGIN_PACKAGE]}), encoding="utf-8")
        self.installer.install(mode="local")
        self.assertFalse(self.installer.npm_installed())
        self.assertTrue(self.installer.local_installed())

    def test_unknown_mode_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.installer.install(mode="carrier-pigeon")


if __name__ == "__main__":
    unittest.main()
