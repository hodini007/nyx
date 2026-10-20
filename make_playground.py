"""Builds a messy fake Downloads folder inside ./playground. Safe to re-run: it resets that folder."""
import os
import shutil
import struct
import time
import zlib
from pathlib import Path

DEST = Path(__file__).resolve().parent / "playground" / "Downloads"
DAY = 86400


def png(r: int, g: int, b: int) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    raw = b"\x00" + bytes([r, g, b]) * 4
    ihdr = struct.pack(">IIBBBBB", 4, 1, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def put(name: str, data: bytes, days_old: float) -> None:
    p = DEST / name
    p.write_bytes(data)
    t = time.time() - days_old * DAY
    os.utime(p, (t, t))


def main() -> None:
    if DEST.exists():
        shutil.rmtree(DEST)
    DEST.mkdir(parents=True)

    put("report.docx", b"proposal draft one", 20)
    put("report_v2.docx", b"proposal draft two", 12)
    put("report_v3_final.docx", b"proposal draft three", 5)
    put("report_v2_final_FINAL.docx", b"proposal draft two polished", 8)

    put("setup-1.4.2.exe", b"installer 1.4.2" * 50, 40)
    put("setup-1.5.0.exe", b"installer 1.5.0" * 50, 10)
    put("vscode-1.88.0.zip", b"vscode old" * 50, 30)
    put("vscode-1.90.1.zip", b"vscode new" * 50, 3)

    put("photo.jpg", b"JPEGDATA-holiday", 15)
    put("photo (1).jpg", b"JPEGDATA-holiday", 14)
    put("photo - Copy.jpg", b"JPEGDATA-holiday", 13)

    for i, rgb in enumerate([(200, 30, 30), (30, 200, 30), (30, 30, 200), (200, 200, 30)]):
        put(f"Screenshot 2026-10-0{i + 1} at 10.00.00.png", png(*rgb), 6 + i)

    put("notes.txt", b"meeting notes", 9)
    put("budget.xlsx", b"budget sheet", 11)
    put("archive.zip", b"zipped stuff", 22)
    put("mystery.bin", b"\x00\x01\x02", 18)
    put("just-downloaded.pdf", b"fresh file, should be skipped", 0)

    print(f"Playground ready: {DEST} ({len(list(DEST.iterdir()))} files)")


if __name__ == "__main__":
    main()
