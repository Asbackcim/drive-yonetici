"""Renk paleti: Slate nötrleri + tek vurgu rengi (teal-700)."""
from __future__ import annotations

import tkinter.ttk as ttk

import customtkinter as ctk

FONT_FAMILY = "Segoe UI"

# (açık, koyu) çiftleri - CustomTkinter bu biçimi doğrudan kabul eder
BG = ("#F8FAFC", "#0F172A")            # slate-50 / slate-900
SURFACE = ("#FFFFFF", "#1E293B")       # beyaz / slate-800
SIDEBAR = ("#F1F5F9", "#111827")       # slate-100 / gray-900
BORDER = ("#E2E8F0", "#334155")        # slate-200 / slate-700
TEXT = ("#0F172A", "#E2E8F0")          # slate-900 / slate-200
MUTED = ("#64748B", "#94A3B8")         # slate-500 / slate-400
ACCENT = ("#0F766E", "#14B8A6")        # teal-700 / teal-500
ACCENT_HOVER = ("#115E59", "#0D9488")
ACCENT_SOFT = ("#CCFBF1", "#134E4A")
DANGER = ("#B91C1C", "#F87171")
WARNING = ("#B45309", "#FBBF24")
NAV_ACTIVE = ("#E2E8F0", "#1E293B")
NAV_HOVER = ("#E8EDF3", "#1F2937")


SEGMENTED = dict(selected_color=SURFACE, selected_hover_color=SURFACE, unselected_color=BORDER,
                 unselected_hover_color=NAV_HOVER, fg_color=BORDER, text_color=TEXT)


def pick(pair: tuple[str, str]) -> str:
    return pair[1] if ctk.get_appearance_mode() == "Dark" else pair[0]


def font(size: int = 13, weight: str = "normal") -> ctk.CTkFont:
    return ctk.CTkFont(family=FONT_FAMILY, size=size, weight=weight)


def style_treeview(root) -> None:
    """ttk.Treeview'i mevcut temaya uydurur (CustomTkinter'da tablo bileşeni yok)."""
    s = ttk.Style(root)
    try:
        s.theme_use("clam")
    except Exception:
        pass
    bg, fg, border = pick(SURFACE), pick(TEXT), pick(BORDER)
    head_bg = pick(SIDEBAR)
    sel = pick(ACCENT_SOFT)
    s.configure("DY.Treeview", background=bg, fieldbackground=bg, foreground=fg, bordercolor=border,
                borderwidth=0, rowheight=28, font=(FONT_FAMILY, 10))
    s.map("DY.Treeview", background=[("selected", sel)], foreground=[("selected", fg)])
    s.configure("DY.Treeview.Heading", background=head_bg, foreground=pick(MUTED), relief="flat",
                borderwidth=0, font=(FONT_FAMILY, 9, "bold"), padding=(8, 6))
    s.map("DY.Treeview.Heading", background=[("active", pick(NAV_HOVER))])
    s.layout("DY.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
    s.configure("DY.Vertical.TScrollbar", background=pick(BORDER), troughcolor=bg, bordercolor=bg,
                arrowcolor=pick(MUTED), lightcolor=bg, darkcolor=bg)
