"""Release contract: the project and the npm package share one version.

``.github/workflows/release.yml`` reads the version from
``plugin/package.json``, refuses to run when ``pyproject.toml`` disagrees, and
tags it as ``v<version>``. Two package managers cannot read one number, so the
number is written twice; these tests fail on the commit that lets the two drift
instead of at publish time, when the result is a broken release rather than a
red build.
"""

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
PLUGIN_PACKAGE = ROOT / "plugin" / "package.json"

SEMVER = re.compile(r"\d+\.\d+\.\d+$")


def project_version() -> str:
    text = PYPROJECT.read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    assert match is not None, "pyproject.toml has no top-level version"
    return match.group(1)


def plugin_version() -> str:
    return json.loads(PLUGIN_PACKAGE.read_text(encoding="utf-8"))["version"]


class ReleaseVersionTest(unittest.TestCase):
    def test_versions_match(self) -> None:
        self.assertEqual(project_version(), plugin_version())

    def test_plugin_version_is_semver(self) -> None:
        # The workflow tags ``v<version>`` and rejects anything that is not a
        # bare X.Y.Z, so a suffix here would silently block every release.
        self.assertRegex(plugin_version(), SEMVER)


if __name__ == "__main__":
    unittest.main()
