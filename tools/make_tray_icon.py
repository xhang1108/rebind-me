"""Generate the static tray icon (``ui/assets/tray.ico``).

Standard library only. Draws a simplified gamepad silhouette as a union of
circles and a capsule, supersampled for smooth edges, then packs it into a
multi-size 32-bpp ICO (one DIB per size, with an all-zero AND mask and real
alpha). Run from the repo root:

    python tools/make_tray_icon.py
"""

from __future__ import annotations

import struct
from pathlib import Path

SIZES = (16, 20, 24, 32, 48)
SAMPLES = 4  # per axis
OUTPUT = Path(__file__).resolve().parents[1] / "src" / "rebind_me" / "ui" / "assets" / "tray.ico"

WHITE = (255, 255, 255)

# Gamepad silhouette in normalised coordinates.
CAPSULE_A = (0.30, 0.60)
CAPSULE_B = (0.70, 0.60)
CAPSULE_R = 0.22
NUBS = ((0.34, 0.32, 0.11), (0.66, 0.32, 0.11))


def _distance_to_segment(x, y, ax, ay, bx, by) -> float:
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq == 0:
        return ((x - ax) ** 2 + (y - ay) ** 2) ** 0.5
    t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / length_sq))
    px, py = ax + t * dx, ay + t * dy
    return ((x - px) ** 2 + (y - py) ** 2) ** 0.5


def _inside(x: float, y: float) -> bool:
    if _distance_to_segment(x, y, *CAPSULE_A, *CAPSULE_B) <= CAPSULE_R:
        return True
    return any((x - cx) ** 2 + (y - cy) ** 2 <= radius ** 2 for cx, cy, radius in NUBS)


def _render(size: int) -> bytes:
    """Return one 32-bpp BGRA DIB (bottom-up) with an all-zero AND mask."""
    row_stride = size * 4
    pixels = bytearray()
    step = 1.0 / (size * SAMPLES)
    for row in range(size):
        for col in range(size):
            hits = 0
            for sy in range(SAMPLES):
                for sx in range(SAMPLES):
                    x = (col * SAMPLES + sx + 0.5) * step
                    y = (row * SAMPLES + sy + 0.5) * step
                    if _inside(x, y):
                        hits += 1
            alpha = round(255 * hits / (SAMPLES * SAMPLES))
            red, green, blue = WHITE
            pixels += bytes((blue, green, red, alpha))

    header = struct.pack(
        "<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0, row_stride * size, 0, 0, 0, 0
    )
    mask_stride = ((size + 31) // 32) * 4
    mask = bytes(mask_stride * size)
    image = header + bytes(pixels) + mask
    return image


def build() -> bytes:
    images = [_render(size) for size in SIZES]
    directory = struct.pack("<HHH", 0, 1, len(images))
    offset = len(directory) + 16 * len(images)
    entries = bytearray()
    for size, image in zip(SIZES, images):
        width = size if size < 256 else 0
        entries += struct.pack(
            "<BBBBHHII", width, width, 0, 0, 1, 32, len(image), offset
        )
        offset += len(image)
    return directory + bytes(entries) + b"".join(images)


def main() -> int:
    data = build()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(data)
    print(f"wrote {OUTPUT} ({len(data)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
