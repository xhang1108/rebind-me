"""Package entry point.

``python -m rebind_me`` launches the bridge. ``python -m rebind_me tray``
launches the tray. The tray normally starts at logon from the HKCU ``...\\Run``
key; the bridge starts from an elevated scheduled task. Real wiring lands in
later stages.
"""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    """Dispatch to the bridge or the tray.

    ``argv[0]`` may be ``"bridge"`` (default) or ``"tray"``.
    """
    args = list(sys.argv[1:] if argv is None else argv)

    if args and args[0] == "tray":
        from rebind_me.tray import main as tray_main

        return tray_main(args[1:])

    print("rebind-me: skeleton (bridge core not implemented yet)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
