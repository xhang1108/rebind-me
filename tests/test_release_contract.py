"""Release contract: one release version, held in two files.

``.github/workflows/release.yml`` reads the version from
``plugin/package.json`` (npm needs its own copy) and refuses to run when
``rebind_me.__version__`` disagrees. ``pyproject.toml`` derives its version
from that attribute rather than holding a third copy. These tests fail on the
commit that lets the copies drift instead of at publish time, when the result
is a broken release rather than a red build.
"""

import json
import re
import unittest
from pathlib import Path

import rebind_me

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
PLUGIN_PACKAGE = ROOT / "plugin" / "package.json"

SEMVER = re.compile(r"\d+\.\d+\.\d+$")
DYNAMIC_VERSION = re.compile(r'^dynamic\s*=\s*\[[^\]]*"version"', re.MULTILINE)


def plugin_version() -> str:
    return json.loads(PLUGIN_PACKAGE.read_text(encoding="utf-8"))["version"]


class ReleaseVersionTest(unittest.TestCase):
    def test_runtime_and_npm_versions_match(self) -> None:
        # A release reads plugin/package.json; __version__ must already agree.
        self.assertEqual(rebind_me.__version__, plugin_version())

    def test_pyproject_derives_its_version(self) -> None:
        # A static version here would be a third copy that nothing bumps.
        text = PYPROJECT.read_text(encoding="utf-8")
        self.assertRegex(text, DYNAMIC_VERSION)
        self.assertNotRegex(text, r'^version\s*=\s*"')

    def test_plugin_version_is_semver(self) -> None:
        # The workflow tags ``v<version>`` and rejects anything that is not a
        # bare X.Y.Z, so a suffix here would silently block every release.
        self.assertRegex(plugin_version(), SEMVER)


if __name__ == "__main__":
    unittest.main()
