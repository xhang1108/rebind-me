"""Documentation consistency contracts.

Pins three invariants that otherwise drift silently:

* every route in ``api.ROUTES`` is documented in ``docs/api/README.md``;
* prose never refers to the plugin as "the opencode plugin" (it is
  "OpenCode 2"), though identifiers and paths may stay lowercase;
* text files use LF line endings (``.editorconfig``), except ``*.cmd`` and
  ``*.bat`` which are CRLF by convention.
"""

import re
import unittest
from pathlib import Path

from rebind_me.api import ROUTES

ROOT = Path(__file__).resolve().parent.parent
DOCS_API = ROOT / "docs" / "api" / "README.md"

TEXT_SUFFIXES = {
    ".py", ".md", ".js", ".mjs", ".ts", ".json", ".html", ".css",
    ".toml", ".yml", ".yaml", ".svg", ".xml", ".gitignore", ".editorconfig",
}
CRLF_SUFFIXES = {".cmd", ".bat"}
SKIP_DIRS = {"node_modules", ".git", "__pycache__", ".pytest_cache", ".idea"}
SKIP_NAMES = {"package-lock.json"}


def _documented_paths() -> set[str]:
    text = DOCS_API.read_text(encoding="utf-8")
    return set(re.findall(r"`(/api/[^`]+)`", text))


class TestApiDocsCoverage(unittest.TestCase):
    def test_every_route_is_documented(self) -> None:
        missing = set(ROUTES) - _documented_paths()
        self.assertEqual(set(), missing, f"routes missing from {DOCS_API}")

    def test_no_undocumented_routes(self) -> None:
        extra = _documented_paths() - set(ROUTES)
        self.assertEqual(set(), extra, f"documented routes not in api.ROUTES")


class TestTerminology(unittest.TestCase):
    def test_no_lowercase_opencode_plugin_phrase(self) -> None:
        offenders = []
        for path in self._docs():
            for lineno, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1
            ):
                if "the opencode plugin" in line:
                    offenders.append(f"{path}:{lineno}")
        self.assertEqual([], offenders)

    def _docs(self):
        for path in ROOT.rglob("*"):
            if path.is_dir() or path.suffix not in {".md"}:
                continue
            if any(part in SKIP_DIRS or part.endswith(".egg-info") for part in path.parts):
                continue
            yield path


class TestLineEndings(unittest.TestCase):
    def test_text_files_use_lf(self) -> None:
        bad = []
        for path in ROOT.rglob("*"):
            if path.is_dir() or path.name in SKIP_NAMES:
                continue
            if any(part in SKIP_DIRS or part.endswith(".egg-info") for part in path.parts):
                continue
            if path.suffix in CRLF_SUFFIXES:
                continue
            if path.suffix not in TEXT_SUFFIXES and path.name not in {
                "LICENSE", ".gitignore", ".gitattributes",
            }:
                continue
            data = path.read_bytes()
            if b"\r\n" in data or b"\r" in data:
                bad.append(str(path.relative_to(ROOT)))
        self.assertEqual([], bad)


if __name__ == "__main__":
    unittest.main()
