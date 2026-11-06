"""Ortak arayüz bileşenleri: arka plan görev yürütücü, tablo, önizleme penceresi, grafik."""
from __future__ import annotations

import logging
import queue
import threading
import tkinter as tk
import tkinter.ttk as ttk
from tkinter import messagebox
from typing import Callable

import customtkinter as ctk

from ..formatting import human_bytes
from ..operations import PreviewRow
from . import theme
from .icons import accent_icon, icon

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Arka plan görevleri: arayüz asla donmaz
# ---------------------------------------------------------------------------
class TaskContext:
    def __init__(self, q: queue.Queue, cancel_event: threading.Event):
        self._q = q
        self._cancel = cancel_event

    def progress(self, *payload) -> None:
        self._q.put(("progress", payload))

    def cancelled(self) -> bool:
        return self._cancel.is_set()


class TaskRunner:
    """Uzun işleri ayrı iş parçacığında çalıştırır; sonuçlar ana döngüye kuyrukla taşınır."""

    def __init__(self, root: tk.Misc):
        self.root = root
        self.busy = False
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self, fn: Callable[[TaskContext], object], on_done: Callable[[object], None] | None = None,
            on_error: Callable[[Exception], None] | None = None,
            on_progress: Callable[..., None] | None = None) -> bool:
        if self.busy:
            messagebox.showinfo("Drive Yönetici", "Başka bir işlem sürüyor. Bitmesini bekleyin ya da durdurun.")
            return False
        self.busy = True
        self._cancel = threading.Event()
        q: queue.Queue = queue.Queue()
        ctx = TaskContext(q, self._cancel)

        def worker():
            try:
                q.put(("done", fn(ctx)))
            except Exception as exc:  # noqa: BLE001
                log.exception("Görev hatası")
                q.put(("error", exc))

        threading.Thread(target=worker, daemon=True, name="gorev").start()

        def poll():
            last_progress = None
            try:
                while True:
                    kind, val = q.get_nowait()
                    if kind == "progress":
                        last_progress = val
                        continue
                    if last_progress and on_progress:
                        on_progress(*last_progress)
                    self.busy = False
                    if kind == "done":
                        on_done and on_done(val)
                    else:
                        (on_error or show_error)(val)
                    return
            except queue.Empty:
                pass
            if last_progress and on_progress:
                on_progress(*last_progress)
            self.root.after(120, poll)

        self.root.after(120, poll)
        return True


def friendly_error(exc: Exception) -> str:
    name = type(exc).__name__
    text = str(exc)
    if name == "RefreshError" or "invalid_grant" in text:
        return ("Bu hesabın oturumu sona ermiş ya da erişim kaldırılmış.\n\n"
                "Google 'Test' modundaki uygulamalarda oturumu 7 günde bir kapatır. "
                "Sol menüden 'Hesap ekle' ile aynı hesabı tekrar bağlayın.")
    status = getattr(getattr(exc, "resp", None), "status", None)
    if status == 403 and "storageQuotaExceeded" in text:
        return "Drive depolama alanınız dolu."
    if status == 403:
        return f"Google bu işleme izin vermedi (403).\n\n{getattr(exc, 'reason', text)}"
    if status == 404:
        return "Dosya ya da klasör bulunamadı (silinmiş veya erişim kaldırılmış olabilir)."
    if name in {"ServerNotFoundError", "ConnectionError", "TimeoutError", "timeout"}:
        return "İnternet bağlantısı kurulamadı. Bağlantınızı kontrol edip tekrar deneyin."
    return text or name


def show_error(exc: Exception) -> None:
    messagebox.showerror("Drive Yönetici", friendly_error(exc))


# ---------------------------------------------------------------------------
# Tablo
# ---------------------------------------------------------------------------
class DataTable(ctk.CTkFrame):
    def __init__(self, master, columns: list[tuple[str, str, int, str]], tree: bool = False,
                 selectmode: str = "extended", height: int = 12):
        """columns: (anahtar, başlık, genişlik, hizalama 'w'|'e'|'center')"""
        super().__init__(master, fg_color=theme.SURFACE, corner_radius=8, border_width=1,
                         border_color=theme.BORDER)
        self.columns = columns
        keys = [c[0] for c in columns]
        show = "tree headings" if tree else "headings"
        self.tv = ttk.Treeview(self, columns=keys, show=show, selectmode=selectmode, style="DY.Treeview",
                               height=height)
        if tree:
            self.tv.column("#0", width=28, stretch=False)
        for key, title, width, anchor in columns:
            self.tv.heading(key, text=title, anchor=anchor if anchor != "e" else "e",
                            command=lambda k=key: self.sort_by(k))
            self.tv.column(key, width=width, anchor=anchor, stretch=anchor == "w")
        sb = ttk.Scrollbar(self, orient="vertical", command=self.tv.yview, style="DY.Vertical.TScrollbar")
        self.tv.configure(yscrollcommand=sb.set)
        self.tv.grid(row=0, column=0, sticky="nsew", padx=(1, 0), pady=1)
        sb.grid(row=0, column=1, sticky="ns", pady=1)
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self._sort_desc: dict[str, bool] = {}
        self.sort_keys: dict[str, dict[str, object]] = {}   # iid -> {kolon: sıralama değeri}
        self.tv.tag_configure("muted", foreground=theme.pick(theme.MUTED))
        self.tv.tag_configure("keep", foreground=theme.pick(theme.ACCENT))

    def clear(self) -> None:
        self.tv.delete(*self.tv.get_children())
        self.sort_keys.clear()

    def insert(self, values: dict, iid: str | None = None, parent: str = "", sort: dict | None = None,
               tags: tuple = (), open: bool = True) -> str:
        row = [values.get(c[0], "") for c in self.columns]
        iid = self.tv.insert(parent, "end", iid=iid, values=row, tags=tags, open=open)
        if sort:
            self.sort_keys[iid] = sort
        return iid

    def selected(self) -> list[str]:
        return list(self.tv.selection())

    def sort_by(self, key: str) -> None:
        desc = not self._sort_desc.get(key, False)
        self._sort_desc[key] = desc
        items = list(self.tv.get_children(""))

        def k(iid):
            sk = self.sort_keys.get(iid, {})
            if key in sk:
                return sk[key]
            return str(self.tv.set(iid, key)).lower()

        try:
            items.sort(key=k, reverse=desc)
        except TypeError:
            items.sort(key=lambda i: str(k(i)), reverse=desc)
        for idx, iid in enumerate(items):
            self.tv.move(iid, "", idx)


# ---------------------------------------------------------------------------
# Önizleme penceresi: her yıkıcı işlemden önce zorunlu
# ---------------------------------------------------------------------------
class PreviewDialog(ctk.CTkToplevel):
    def __init__(self, master, title: str, rows: list[PreviewRow], explanation: str,
                 confirm_text: str = "Onayla ve uygula"):
        super().__init__(master)
        self.title(title)
        self.geometry("980x620")
        self.minsize(720, 420)
        self.configure(fg_color=theme.BG)
        self.result = False
        self.transient(master)

        ctk.CTkLabel(self, text=title, font=theme.font(18, "bold"), text_color=theme.TEXT,
                     anchor="w").pack(fill="x", padx=20, pady=(18, 2))
        counts: dict[str, int] = {}
        for r in rows:
            counts[r.action] = counts.get(r.action, 0) + 1
        total = sum(r.size for r in rows if r.action.startswith(("Çöpe", "Kopyala", "Taşı")))
        summary = "  ·  ".join(f"{v} × {k}" for k, v in counts.items())
        ctk.CTkLabel(self, text=f"{summary}   |   ilgili veri: {human_bytes(total)}", font=theme.font(12),
                     text_color=theme.MUTED, anchor="w").pack(fill="x", padx=20)
        ctk.CTkLabel(self, text=explanation, font=theme.font(12), text_color=theme.TEXT, anchor="w",
                     justify="left", wraplength=920).pack(fill="x", padx=20, pady=(8, 8))

        table = DataTable(self, [("action", "İşlem", 150, "w"), ("name", "Ad", 260, "w"),
                                 ("detail", "Ayrıntı", 420, "w"), ("size", "Boyut", 90, "e")])
        table.pack(fill="both", expand=True, padx=20)
        for i, r in enumerate(rows[:20000]):
            table.insert({"action": r.action, "name": r.name, "detail": r.detail,
                          "size": human_bytes(r.size) if r.size else ""}, iid=str(i), sort={"size": r.size})
        if len(rows) > 20000:
            ctk.CTkLabel(self, text=f"İlk 20.000 satır gösteriliyor (toplam {len(rows)}).",
                         text_color=theme.MUTED).pack(padx=20, anchor="w")

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=20, pady=16)
        ctk.CTkLabel(bar, text="Kalıcı silme yapılmaz. Bu işlem günlüğe yazılır ve 'Son işlemi geri al' ile "
                                "geri alınabilir.", text_color=theme.MUTED, font=theme.font(11)).pack(side="left")
        ctk.CTkButton(bar, text=confirm_text, image=accent_icon("check"), fg_color=theme.ACCENT,
                      hover_color=theme.ACCENT_HOVER, command=self._ok, width=180).pack(side="right")
        ctk.CTkButton(bar, text="Vazgeç", fg_color="transparent", border_width=1, border_color=theme.BORDER,
                      text_color=theme.TEXT, hover_color=theme.NAV_HOVER, command=self.destroy,
                      width=110).pack(side="right", padx=8)
        self.after(50, self._focus)

    def _focus(self):
        try:
            self.grab_set()
            self.focus_force()
        except tk.TclError:
            pass

    def _ok(self):
        self.result = True
        self.destroy()


def confirm_preview(master, title: str, rows: list[PreviewRow], explanation: str) -> bool:
    if not rows:
        messagebox.showinfo("Drive Yönetici", "Uygulanacak bir değişiklik yok.")
        return False
    dlg = PreviewDialog(master, title, rows, explanation)
    master.wait_window(dlg)
    return dlg.result


# ---------------------------------------------------------------------------
# Yatay çubuk grafik (tür bazlı alan dağılımı)
# ---------------------------------------------------------------------------
class BarChart(ctk.CTkFrame):
    def __init__(self, master, height: int = 220):
        super().__init__(master, fg_color=theme.SURFACE, corner_radius=8, border_width=1,
                         border_color=theme.BORDER)
        self.canvas = tk.Canvas(self, height=height, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True, padx=12, pady=12)
        self.data: dict[str, int] = {}
        self.canvas.bind("<Configure>", lambda e: self.redraw())

    def set_data(self, data: dict[str, int]) -> None:
        self.data = data
        self.redraw()

    def redraw(self) -> None:
        c = self.canvas
        c.delete("all")
        c.configure(bg=theme.pick(theme.SURFACE))
        w = max(200, c.winfo_width())
        if not self.data:
            c.create_text(w / 2, 40, text="Henüz veri yok. Önce Drive'ı tarayın.",
                          fill=theme.pick(theme.MUTED), font=(theme.FONT_FAMILY, 10))
            return
        total = sum(self.data.values()) or 1
        mx = max(self.data.values()) or 1
        label_w, value_w = 90, 150
        bar_w = max(40, w - label_w - value_w - 10)
        y = 6
        for name, val in self.data.items():
            c.create_text(0, y + 9, text=name, anchor="w", fill=theme.pick(theme.TEXT),
                          font=(theme.FONT_FAMILY, 10))
            length = max(2, bar_w * val / mx)
            c.create_rectangle(label_w, y + 2, label_w + bar_w, y + 16, fill=theme.pick(theme.BORDER), width=0)
            c.create_rectangle(label_w, y + 2, label_w + length, y + 16, fill=theme.pick(theme.ACCENT), width=0)
            c.create_text(label_w + bar_w + 10, y + 9, anchor="w", fill=theme.pick(theme.MUTED),
                          text=f"{human_bytes(val)}  ({val * 100 / total:.0f}%)", font=(theme.FONT_FAMILY, 10))
            y += 26
        c.configure(height=max(60, y + 4))


# ---------------------------------------------------------------------------
# Küçük yardımcılar
# ---------------------------------------------------------------------------
def heading(master, text: str, sub: str = "") -> ctk.CTkFrame:
    f = ctk.CTkFrame(master, fg_color="transparent")
    ctk.CTkLabel(f, text=text, font=theme.font(22, "bold"), text_color=theme.TEXT, anchor="w").pack(fill="x")
    if sub:
        ctk.CTkLabel(f, text=sub, font=theme.font(12), text_color=theme.MUTED, anchor="w", justify="left",
                     wraplength=900).pack(fill="x", pady=(2, 0))
    return f


def primary_button(master, text: str, command, icon_name: str | None = None, **kw) -> ctk.CTkButton:
    return ctk.CTkButton(master, text=text, command=command, fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
                         text_color=("#FFFFFF", "#042F2E"), text_color_disabled=("#CBD5E1", "#475569"),
                         font=theme.font(13, "bold"), height=34,
                         image=accent_icon(icon_name) if icon_name else None, **kw)


def secondary_button(master, text: str, command, icon_name: str | None = None, **kw) -> ctk.CTkButton:
    return ctk.CTkButton(master, text=text, command=command, fg_color="transparent", border_width=1,
                         border_color=theme.BORDER, text_color=theme.TEXT, hover_color=theme.NAV_HOVER,
                         font=theme.font(13), height=34, image=icon(icon_name) if icon_name else None, **kw)


def card(master, **kw) -> ctk.CTkFrame:
    return ctk.CTkFrame(master, fg_color=theme.SURFACE, corner_radius=10, border_width=1,
                        border_color=theme.BORDER, **kw)


def stat(master, label: str, value: str = "-") -> ctk.CTkLabel:
    f = card(master)
    ctk.CTkLabel(f, text=label, font=theme.font(11), text_color=theme.MUTED, anchor="w").pack(
        fill="x", padx=14, pady=(10, 0))
    v = ctk.CTkLabel(f, text=value, font=theme.font(20, "bold"), text_color=theme.TEXT, anchor="w")
    v.pack(fill="x", padx=14, pady=(0, 10))
    f.pack(side="left", fill="x", expand=True, padx=(0, 10))
    return v


# ---------------------------------------------------------------------------
# Drive klasör/dosya seçici
# ---------------------------------------------------------------------------
class DriveBrowser(ctk.CTkToplevel):
    """Bir hesabın Drive'ında gezinip klasör (veya dosya/klasör) seçme penceresi."""

    def __init__(self, master, runner_root, client, title: str, pick_files: bool = False):
        super().__init__(master)
        self.title(title)
        self.geometry("760x540")
        self.configure(fg_color=theme.BG)
        self.transient(master)
        self.client = client
        self.pick_files = pick_files
        self.stack: list[tuple[str, str]] = [("root", "Drive'ım")]
        self.items: dict[str, dict] = {}
        self.result: list[dict] | dict | None = None
        self.runner = TaskRunner(self)

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=16, pady=(14, 6))
        secondary_button(top, "Yukarı", self.up, width=90).pack(side="left")
        self.path_lbl = ctk.CTkLabel(top, text="", font=theme.font(13, "bold"), text_color=theme.TEXT, anchor="w")
        self.path_lbl.pack(side="left", padx=12, fill="x", expand=True)
        ctk.CTkLabel(self, text=("Klasöre girmek için çift tıklayın. " +
                                 ("Aktarılacak dosya/klasörleri seçin (Ctrl ile çoklu seçim)."
                                  if pick_files else "")), text_color=theme.MUTED, font=theme.font(11),
                     anchor="w").pack(fill="x", padx=16)
        self.table = DataTable(self, [("name", "Ad", 420, "w"), ("kind", "Tür", 110, "w"),
                                      ("size", "Boyut", 100, "e")],
                               selectmode="extended" if pick_files else "browse")
        self.table.pack(fill="both", expand=True, padx=16, pady=8)
        self.table.tv.bind("<Double-1>", self._open)
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=16, pady=(0, 14))
        primary_button(bar, "Seçilenleri al" if pick_files else "Bu klasörü seç", self._choose,
                       width=170).pack(side="right")
        secondary_button(bar, "Vazgeç", self.destroy, width=100).pack(side="right", padx=8)
        self.load()
        self.after(50, lambda: self.grab_set())

    def load(self):
        fid, _ = self.stack[-1]
        self.path_lbl.configure(text=" / ".join(n for _, n in self.stack))
        self.table.clear()
        self.table.insert({"name": "Yükleniyor..."}, iid="__loading")

        def fetch(ctx):
            return self.client.list_children(fid)

        def done(children):
            if not self.winfo_exists():
                return
            self.table.clear()
            self.items = {c["id"]: c for c in children}
            for c in sorted(children, key=lambda c: (c.get("mimeType") != "application/vnd.google-apps.folder",
                                                     c["name"].lower())):
                is_folder = c.get("mimeType") == "application/vnd.google-apps.folder"
                if not is_folder and not self.pick_files:
                    continue
                self.table.insert({"name": c["name"], "kind": "Klasör" if is_folder else "Dosya",
                                   "size": "" if is_folder else human_bytes(int(c.get("size") or 0))}, iid=c["id"])

        self.runner.run(fetch, done)

    def _open(self, _evt=None):
        sel = self.table.selected()
        if not sel or sel[0] not in self.items:
            return
        item = self.items[sel[0]]
        if item.get("mimeType") == "application/vnd.google-apps.folder":
            self.stack.append((item["id"], item["name"]))
            self.load()

    def up(self):
        if len(self.stack) > 1:
            self.stack.pop()
            self.load()

    def _choose(self):
        if self.pick_files:
            sel = [self.items[i] for i in self.table.selected() if i in self.items]
            if not sel:
                messagebox.showinfo("Drive Yönetici", "Lütfen en az bir öğe seçin.", parent=self)
                return
            self.result = sel
        else:
            sel = [i for i in self.table.selected() if i in self.items]
            if sel:  # klasör seçiliyse onu, değilse bulunulan klasörü al
                self.result = {"id": sel[0], "name": "/".join(n for _, n in self.stack) + "/" + self.items[sel[0]]["name"]}
            else:
                fid, _ = self.stack[-1]
                self.result = {"id": fid, "name": "/".join(n for _, n in self.stack)}
        self.destroy()


def browse_drive(master, client, title: str, pick_files: bool = False):
    dlg = DriveBrowser(master, master, client, title, pick_files)
    master.wait_window(dlg)
    return dlg.result
