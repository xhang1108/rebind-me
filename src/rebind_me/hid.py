"""HID device enumeration, overlapped I/O and reconnection. See plan.md §4.

Interface is selected by caps (``OutputReportByteLength == 48`` and
``InputReportByteLength >= 11``), never by report ID. Skeleton until stage 3.
"""

from __future__ import annotations

__all__: list[str] = []
