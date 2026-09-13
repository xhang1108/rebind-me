"""Logon launcher for Rebind Me.

Run with ``pythonw.exe`` so no console window appears. The first argument
selects the component: ``bridge`` (elevated scheduled task) or ``tray``
(normal-privilege HKCU ``...\\Run``). It prepends ``src/`` to ``sys.path`` so
the checkout runs without installation.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from rebind_me.__main__ import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
