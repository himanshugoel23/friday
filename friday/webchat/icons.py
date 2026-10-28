"""The app icon as PNG bytes, drawn in pure Python (no image library): a green square with a white F."""

from __future__ import annotations

import functools
import struct
import zlib

GREEN = (0, 128, 105)
WHITE = (255, 255, 255)
# 5 x 7 pixel F
_F = ("11111", "10000", "10000", "11110", "10000", "10000", "10000")


def _chunk(kind: bytes, data: bytes) -> bytes:
    body = kind + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)


@functools.lru_cache(maxsize=8)
def png(size: int) -> bytes:
    cell = max(1, size // 12)  # the F is 5 cells wide, 7 tall, centred (inside the maskable safe zone)
    w, h = 5 * cell, 7 * cell
    x0, y0 = (size - w) // 2, (size - h) // 2
    rows = bytearray()
    for y in range(size):
        rows.append(0)  # filter: none
        gy = (y - y0) // cell if y0 <= y < y0 + h else -1
        for x in range(size):
            gx = (x - x0) // cell if x0 <= x < x0 + w else -1
            on = gy >= 0 and gx >= 0 and _F[gy][gx] == "1"
            rows.extend(WHITE if on else GREEN)
    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(bytes(rows), 9))
        + _chunk(b"IEND", b"")
    )
