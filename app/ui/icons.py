"""Lucide tarzı çizgi ikonlar (24x24 ızgara, 2px çizgi), Pillow ile çizilir.

Harici ikon dosyası gerekmez; exe tek dosya kalır.
"""
from __future__ import annotations

from functools import lru_cache

import customtkinter as ctk
from PIL import Image, ImageDraw

S = 8            # süper örnekleme
W = 2 * S        # çizgi kalınlığı


def _canvas():
    img = Image.new("RGBA", (24 * S, 24 * S), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img)


def _p(*pts):
    return [(x * S, y * S) for x, y in pts]


def _line(d, color, *pts):
    d.line(_p(*pts), fill=color, width=W, joint="curve")
    for x, y in pts:  # yuvarlak uçlar
        r = W / 2
        d.ellipse((x * S - r, y * S - r, x * S + r, y * S + r), fill=color)


def _rect(d, color, x0, y0, x1, y1, r=2):
    d.rounded_rectangle((x0 * S, y0 * S, x1 * S, y1 * S), radius=r * S, outline=color, width=W)


def _circle(d, color, cx, cy, r):
    d.ellipse(((cx - r) * S, (cy - r) * S, (cx + r) * S, (cy + r) * S), outline=color, width=W)


def _arc(d, color, cx, cy, r, start, end):
    d.arc(((cx - r) * S, (cy - r) * S, (cx + r) * S, (cy + r) * S), start, end, fill=color, width=W)


def _draw(name: str, color: str):
    img, d = _canvas()
    if name == "upload":            # cloud-upload
        _arc(d, color, 8, 14, 5, 90, 270)
        _arc(d, color, 13, 10, 6, 180, 330)
        _arc(d, color, 18, 15, 4, 270, 90)
        _line(d, color, (8, 19), (10, 19))
        _line(d, color, (14, 19), (18, 19))
        _line(d, color, (12, 21), (12, 12))
        _line(d, color, (9, 15), (12, 12), (15, 15))
    elif name == "copy":
        _rect(d, color, 8, 8, 21, 21)
        _line(d, color, (4, 16), (4, 5), (5, 3), (16, 3))
    elif name == "hard-drive":
        _rect(d, color, 2, 13, 22, 21)
        _line(d, color, (2, 13), (5.5, 4), (18.5, 4), (22, 13))
        _line(d, color, (6, 17), (6.01, 17))
        _line(d, color, (10, 17), (10.01, 17))
    elif name == "folder-tree":
        _rect(d, color, 13, 3, 21, 9, 1)
        _rect(d, color, 13, 14, 21, 20, 1)
        _line(d, color, (4, 3), (4, 17), (13, 17))
        _line(d, color, (4, 6), (13, 6))
    elif name == "arrows":          # arrow-left-right
        _line(d, color, (3, 8), (21, 8))
        _line(d, color, (17, 4), (21, 8), (17, 12))
        _line(d, color, (21, 16), (3, 16))
        _line(d, color, (7, 12), (3, 16), (7, 20))
    elif name == "history":
        _arc(d, color, 12, 12, 9, 200, 160)
        _line(d, color, (3, 4), (3, 9), (8, 9))
        _line(d, color, (12, 7), (12, 12), (15, 14))
    elif name == "settings":
        _circle(d, color, 12, 12, 3)
        _circle(d, color, 12, 12, 8)
        for a, b in (((12, 1), (12, 4)), ((12, 20), (12, 23)), ((1, 12), (4, 12)), ((20, 12), (23, 12))):
            _line(d, color, a, b)
    elif name == "plus":
        _line(d, color, (12, 5), (12, 19))
        _line(d, color, (5, 12), (19, 12))
    elif name == "user":
        _circle(d, color, 12, 8, 4)
        _arc(d, color, 12, 22, 8, 180, 360)
    elif name == "undo":
        _line(d, color, (9, 14), (4, 9), (9, 4))
        _arc(d, color, 14.5, 14.5, 5.5, 270, 90)
        _line(d, color, (4, 9), (14.5, 9))
        _line(d, color, (14.5, 20), (11, 20))
    elif name == "trash":
        _line(d, color, (3, 6), (21, 6))
        _line(d, color, (19, 6), (18, 20), (17, 21), (7, 21), (6, 20), (5, 6))
        _line(d, color, (8, 6), (8, 4), (9, 3), (15, 3), (16, 4), (16, 6))
    elif name == "folder":
        _line(d, color, (2, 19), (2, 5), (3, 4), (9, 4), (11, 7), (21, 7), (22, 8), (22, 19), (21, 20), (3, 20), (2, 19))
    elif name == "refresh":
        _arc(d, color, 12, 12, 9, 200, 340)
        _arc(d, color, 12, 12, 9, 20, 160)
        _line(d, color, (21, 3), (21, 8), (16, 8))
        _line(d, color, (3, 21), (3, 16), (8, 16))
    elif name == "search":
        _circle(d, color, 11, 11, 7)
        _line(d, color, (21, 21), (16, 16))
    elif name == "stop":
        _rect(d, color, 5, 5, 19, 19)
    elif name == "file":
        _line(d, color, (14, 2), (6, 2), (4, 4), (4, 20), (6, 22), (18, 22), (20, 20), (20, 8), (14, 2))
        _line(d, color, (14, 2), (14, 8), (20, 8))
    elif name == "logout":
        _line(d, color, (9, 21), (5, 21), (3, 19), (3, 5), (5, 3), (9, 3))
        _line(d, color, (16, 17), (21, 12), (16, 7))
        _line(d, color, (21, 12), (9, 12))
    elif name == "check":
        _line(d, color, (20, 6), (9, 17), (4, 12))
    return img.resize((48, 48), Image.LANCZOS)


@lru_cache(maxsize=256)
def icon(name: str, size: int = 18, light: str = "#334155", dark: str = "#CBD5E1") -> ctk.CTkImage:
    return ctk.CTkImage(light_image=_draw(name, light), dark_image=_draw(name, dark), size=(size, size))


def accent_icon(name: str, size: int = 18) -> ctk.CTkImage:
    return icon(name, size, "#FFFFFF", "#042F2E")
