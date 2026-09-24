"""Package entry point.

``python -m rebind_me`` launches the bridge. ``python -m rebind_me tray``
launches the tray. The tray normally starts at startup from the HKCU ``...\\Run``
key; the bridge starts from an elevated scheduled task. ``autostart`` manages
that wiring and ``plugin`` installs the OpenCode 2 integration.
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

    if args and args[0] == "autostart":
        from rebind_me.autostart import main as autostart_main

        return autostart_main(args[1:])

    if args and args[0] == "plugin":
        from rebind_me.opencode_plugin import main as plugin_main

        return plugin_main(args[1:])

    from rebind_me.bridge import Bridge

    return Bridge().run()


if __name__ == "__main__":
    raise SystemExit(main())
