"""The Kaggle mirror's cover image, drawn by code (standard library only).

560 by 280 pixels, the size Kaggle asks for. The name sits in the top left, in a small
built-in pixel font. Below it, one bar per day from 28 days before an event to 28 days after
stands for what the dataset measures: a flat baseline, the jump on the event's day, and the
fall back. The numbers are invented for the drawing; no count from the data is drawn.

``python -m newsattention.cover OUT.png`` writes it; the tracked copy is ``kaggle_cover.png``
next to this file, and a test checks that this code draws exactly its bytes.
"""

from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

WIDTH, HEIGHT = 560, 280
TRACKED = Path(__file__).with_name("kaggle_cover.png")

PAPER = (247, 245, 240)
INK = (31, 41, 55)
RULE = (214, 209, 200)
BEFORE = (148, 156, 168)
AFTER = (180, 83, 9)
MARK = (120, 53, 15)

#: 5 by 7 glyphs for the letters of the name.
GLYPHS = {
    "N": ("10001", "11001", "10101", "10011", "10001", "10001", "10001"),
    "e": ("00000", "00000", "01110", "10001", "11111", "10000", "01110"),
    "w": ("00000", "00000", "10001", "10001", "10101", "10101", "01010"),
    "s": ("00000", "00000", "01111", "10000", "01110", "00001", "11110"),
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "t": ("01000", "01000", "11100", "01000", "01000", "01001", "00110"),
    "i": ("00100", "00000", "01100", "00100", "00100", "00100", "01110"),
    "o": ("00000", "00000", "01110", "10001", "10001", "10001", "01110"),
    "n": ("00000", "00000", "10110", "11001", "10001", "10001", "10001"),
}
NAME = "NewsAttention"
SCALE = 4
LEFT, TOP = 24, 24


def views(day: int) -> float:
    """Invented daily views around an event on day 0: a flat baseline, a jump, a fall."""
    if day < 0:
        return 20 + (day * 7) % 5
    return 20 + 120 * 0.62**day


def canvas() -> list[bytearray]:
    rows = [bytearray(PAPER * WIDTH) for _ in range(HEIGHT)]

    def fill(x0: int, y0: int, x1: int, y1: int, color: tuple[int, int, int]) -> None:
        for y in range(max(0, y0), min(HEIGHT, y1)):
            row = rows[y]
            for x in range(max(0, x0), min(WIDTH, x1)):
                row[3 * x : 3 * x + 3] = bytes(color)

    x = LEFT
    for ch in NAME:
        for gy, line in enumerate(GLYPHS[ch]):
            for gx, bit in enumerate(line):
                if bit == "1":
                    px, py = x + gx * SCALE, TOP + gy * SCALE
                    fill(px, py, px + SCALE, py + SCALE, INK)
        x += 6 * SCALE
    fill(
        LEFT, TOP + 8 * SCALE + 10, LEFT + 6 * SCALE * len(NAME) - SCALE, TOP + 8 * SCALE + 12, RULE
    )

    days = list(range(-28, 29))
    base_y, top_y = HEIGHT - 24, 110
    peak = max(views(d) for d in days)
    step = (WIDTH - 2 * LEFT) // len(days)
    x0 = LEFT + ((WIDTH - 2 * LEFT) - step * len(days)) // 2
    for k, d in enumerate(days):
        h = round((base_y - top_y) * views(d) / peak)
        fill(
            x0 + k * step, base_y - h, x0 + k * step + step - 2, base_y, BEFORE if d < 0 else AFTER
        )
    zero = x0 + 28 * step
    fill(zero - 1, top_y - 12, zero + 1, base_y + 8, MARK)
    fill(LEFT, base_y, WIDTH - LEFT, base_y + 1, RULE)
    return rows


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def render() -> bytes:
    """The PNG file's bytes."""
    raw = b"".join(b"\x00" + bytes(row) for row in canvas())
    ihdr = struct.pack(">IIBBBBB", WIDTH, HEIGHT, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(raw, 9))
        + _chunk(b"IEND", b"")
    )


def write_png(path: Path | str) -> Path:
    path = Path(path)
    path.write_bytes(render())
    return path


def png_size(path: Path | str) -> tuple[int, int]:
    """Width and height from a PNG file's header."""
    data = Path(path).read_bytes()[:24]
    if data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise ValueError(f"{path} is not a PNG file")
    return struct.unpack(">II", data[16:24])


if __name__ == "__main__":  # pragma: no cover
    write_png(sys.argv[1] if len(sys.argv) > 1 else TRACKED)
