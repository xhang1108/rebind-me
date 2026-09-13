"""Local HTTP API and same-origin static file serving. See plan.md §13.

Single port (default ``127.0.0.1:4173``). UI endpoints are guarded by an
Origin / Host allow-list; program endpoints require ``X-Bridge-Token``.
Skeleton until stage 3.
"""

from __future__ import annotations

DEFAULT_PORT = 4173

__all__ = ["DEFAULT_PORT"]
