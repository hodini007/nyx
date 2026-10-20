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


def render_screens() -> list[bytes] | None:
    try:
        from io import BytesIO
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return None
    font = ImageFont.load_default(size=22)
    big = ImageFont.load_default(size=30)

    def card(bg, fg, lines, title=None):
        img = Image.new("RGB", (900, 560), bg)
        d = ImageDraw.Draw(img)
        y = 30
        if title:
            d.text((40, y), title, fill=fg, font=big)
            y += 60
        for line in lines:
            d.text((40, y), line, fill=fg, font=font)
            y += 36
        out = BytesIO()
        img.save(out, "PNG")
        return out.getvalue()

    def chat():
        img = Image.new("RGB", (900, 560), (235, 238, 245))
        d = ImageDraw.Draw(img)
        for i, (mine, text) in enumerate([(False, "Hey, are we still on for dinner at 7?"), (True, "Yes! See you at Luigi's"), (False, "Great, I booked a table for two")]):
            x0 = 520 if mine else 40
            d.rounded_rectangle((x0, 40 + i * 110, x0 + 340, 120 + i * 110), 20, fill=(90, 130, 230) if mine else (255, 255, 255))
            d.text((x0 + 16, 66 + i * 110), text[:28], fill=(255, 255, 255) if mine else (20, 20, 20), font=font)
            if len(text) > 28:
                d.text((x0 + 16, 90 + i * 110), text[28:], fill=(255, 255, 255) if mine else (20, 20, 20), font=font)
        out = BytesIO()
        img.save(out, "PNG")
        return out.getvalue()

    return [
        card((255, 255, 255), (20, 20, 20), ["Latte            3.50", "Croissant        1.00", "Tax              0.00", "-------------------", "TOTAL           $4.50", "Paid by card  03/03/2026"], "BLUE BOTTLE COFFEE - RECEIPT"),
        card((18, 18, 24), (240, 90, 90), ["Traceback (most recent call last):", '  File "train.py", line 12, in <module>', "    import numpy as np", "ModuleNotFoundError: No module named 'numpy'"], "Terminal"),
        chat(),
        card((250, 250, 235), (30, 30, 30), ["Guest WiFi", "Network: CafeNet_Guest", "Password: sunrise2026"], "Cafe WiFi Info"),
        card((30, 34, 46), (200, 220, 255), ["def total(items):", "    return sum(i.price for i in items)", "", "print(total(cart))"], "main.py - Code Editor"),
        card((255, 255, 255), (30, 30, 60), ["Revenue grew 12% year over year.", "Operating costs fell 4%.", "Headcount: 48 employees."], "Quarterly Report - Q3 2026"),
    ]


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

    screens = render_screens() or [png(*rgb) for rgb in [(200, 30, 30), (30, 200, 30), (30, 30, 200), (200, 200, 30)]]
    for i, data in enumerate(screens):
        put(f"Screenshot 2026-10-0{i + 1} at 10.00.00.png", data, 6 + i)

    put("notes.txt", b"meeting notes", 9)
    put("budget.xlsx", b"budget sheet", 11)
    put("archive.zip", b"zipped stuff", 22)
    put("mystery.bin", b"\x00\x01\x02", 18)
    put("just-downloaded.pdf", b"fresh file, should be skipped", 0)

    print(f"Playground ready: {DEST} ({len(list(DEST.iterdir()))} files)")


if __name__ == "__main__":
    main()
