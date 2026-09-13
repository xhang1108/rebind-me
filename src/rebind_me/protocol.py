"""DualSense USB report decode / encode. See plan.md §6.

Input report ID ``0x01``; output report ID ``0x02`` (48 bytes incl. report ID).
Full offset / bit tables and golden tests land in stage 2. Skeleton for now.
"""

from __future__ import annotations

INPUT_REPORT_ID = 0x01
OUTPUT_REPORT_ID = 0x02
OUTPUT_REPORT_LENGTH = 48

__all__ = ["INPUT_REPORT_ID", "OUTPUT_REPORT_ID", "OUTPUT_REPORT_LENGTH"]
