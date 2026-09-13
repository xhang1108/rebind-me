"""Tray application (separate process, normal privileges). See plan.md §12.

Started at logon via the HKCU ``...\\Run`` key; controls the bridge through
``schtasks`` and the local API. Skeleton until stage 5.
"""

from __future__ import annotations


def main(argv: list[str] | None = None) -> int:
    _ = list(argv or [])
    print("rebind-me: tray placeholder (not implemented yet)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
