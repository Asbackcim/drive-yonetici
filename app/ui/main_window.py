"""Ana pencere: sol kenar çubuğu (hesaplar + sekmeler) ve içerik alanı."""
from __future__ import annotations

from tkinter import messagebox

import customtkinter as ctk

from .. import __version__
from . import theme
from .context import AppContext
from .icons import icon
from .page_backup import BackupPage
from .page_drive import DuplicatesPage, LargeOldPage, OrganizePage
from .page_misc import JournalPage, SetupPage, TransferPage
from .widgets import TaskRunner, show_error

NAV = [("backup", "Yedekleme", "upload", BackupPage),
       ("dups", "Kopyalar", "copy", DuplicatesPage),
       ("large", "Büyük/Eski", "hard-drive", LargeOldPage),
       ("organize", "Düzenle", "folder-tree", OrganizePage),
       ("transfer", "Taşı/Kopyala", "arrows", TransferPage),
       ("journal", "Günlük", "history", JournalPage)]
THEMES = {"Sistem": "system", "Açık": "light", "Koyu": "dark"}


class MainWindow(ctk.CTk):
    def __init__(self, ctx: AppContext | None = None):
        self.ctx = ctx or AppContext()
        ctk.set_appearance_mode(self.ctx.settings.get("theme"))
        super().__init__(fg_color=theme.BG)
        self.title(f"Drive Yönetici {__version__}")
        self.geometry("1280x820")
        self.minsize(1080, 680)
        theme.style_treeview(self)
        self.runner = TaskRunner(self)
        self.pages: dict[str, ctk.CTkFrame] = {}
        self.nav_buttons: dict[str, ctk.CTkButton] = {}
        self.account_buttons: dict[str, ctk.CTkButton] = {}
        self.current_page = None

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()
        self.content = ctk.CTkFrame(self, fg_color=theme.BG, corner_radius=0)
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_columnconfigure(0, weight=1)

        self.pages["setup"] = SetupPage(self.content, self.ctx, self.runner, on_ready=self.refresh_accounts)
        for key, _label, _ic, cls in NAV:
            self.pages[key] = cls(self.content, self.ctx, self.runner)
        for p in self.pages.values():
            p.grid(row=0, column=0, sticky="nsew")

        self.refresh_accounts()
        if not self.ctx.accounts.has_client_config() or not self.ctx.current_email:
            self.show("setup")
        else:
            self.show("backup")
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---- kenar çubuğu --------------------------------------------------------------
    def _build_sidebar(self):
        sb = ctk.CTkFrame(self, fg_color=theme.SIDEBAR, corner_radius=0, width=250, border_width=0)
        sb.grid(row=0, column=0, sticky="nsw")
        sb.grid_propagate(False)
        sb.pack_propagate(False)
        ctk.CTkLabel(sb, text="Drive Yönetici", font=theme.font(18, "bold"), text_color=theme.TEXT,
                     anchor="w").pack(fill="x", padx=20, pady=(22, 0))
        ctk.CTkLabel(sb, text="Google Drive düzen ve yedek", font=theme.font(11), text_color=theme.MUTED,
                     anchor="w").pack(fill="x", padx=20, pady=(0, 16))

        ctk.CTkLabel(sb, text="HESAPLAR", font=theme.font(10, "bold"), text_color=theme.MUTED,
                     anchor="w").pack(fill="x", padx=20)
        self.acc_frame = ctk.CTkFrame(sb, fg_color="transparent")
        self.acc_frame.pack(fill="x", padx=10, pady=(4, 0))
        row = ctk.CTkFrame(sb, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=(4, 12))
        ctk.CTkButton(row, text="Hesap ekle", image=icon("plus", 16), anchor="w", height=30, width=120,
                      fg_color="transparent", text_color=theme.ACCENT, hover_color=theme.NAV_HOVER,
                      font=theme.font(12, "bold"), command=self.add_account).pack(side="left")
        ctk.CTkButton(row, text="Çıkar", image=icon("logout", 16), anchor="w", height=30, width=90,
                      fg_color="transparent", text_color=theme.MUTED, hover_color=theme.NAV_HOVER,
                      font=theme.font(12), command=self.remove_account).pack(side="right")

        ctk.CTkFrame(sb, height=1, fg_color=theme.BORDER).pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(sb, text="ARAÇLAR", font=theme.font(10, "bold"), text_color=theme.MUTED,
                     anchor="w").pack(fill="x", padx=20, pady=(10, 2))
        for key, label, ic, _cls in NAV:
            btn = ctk.CTkButton(sb, text=label, image=icon(ic), anchor="w", height=38, corner_radius=8,
                                fg_color="transparent", text_color=theme.TEXT, hover_color=theme.NAV_HOVER,
                                font=theme.font(13), command=lambda k=key: self.show(k))
            btn.pack(fill="x", padx=10, pady=1)
            self.nav_buttons[key] = btn
        btn = ctk.CTkButton(sb, text="Kurulum", image=icon("settings"), anchor="w", height=38, corner_radius=8,
                            fg_color="transparent", text_color=theme.TEXT, hover_color=theme.NAV_HOVER,
                            font=theme.font(13), command=lambda: self.show("setup"))
        btn.pack(fill="x", padx=10, pady=1)
        self.nav_buttons["setup"] = btn

        bottom = ctk.CTkFrame(sb, fg_color="transparent")
        bottom.pack(side="bottom", fill="x", padx=16, pady=16)
        ctk.CTkLabel(bottom, text="Tema", font=theme.font(11), text_color=theme.MUTED, anchor="w").pack(fill="x")
        self.theme_btn = ctk.CTkSegmentedButton(bottom, values=list(THEMES), command=self.set_theme,
                                                **theme.SEGMENTED)
        self.theme_btn.pack(fill="x", pady=(4, 0))
        current = {v: k for k, v in THEMES.items()}.get(self.ctx.settings.get("theme"), "Sistem")
        self.theme_btn.set(current)

    def refresh_accounts(self):
        for w in self.acc_frame.winfo_children():
            w.destroy()
        self.account_buttons.clear()
        accounts = self.ctx.accounts.list_accounts()
        emails = [a["email"] for a in accounts]
        if self.ctx.current_email not in emails:
            self.ctx.current_email = emails[0] if emails else None
        if not accounts:
            ctk.CTkLabel(self.acc_frame, text="Henüz hesap yok", font=theme.font(12), text_color=theme.MUTED,
                         anchor="w").pack(fill="x", padx=10, pady=4)
        for a in accounts:
            b = ctk.CTkButton(self.acc_frame, text=a["email"], image=icon("user", 16), anchor="w", height=32,
                              corner_radius=8, font=theme.font(12), text_color=theme.TEXT,
                              hover_color=theme.NAV_HOVER, command=lambda e=a["email"]: self.select_account(e))
            b.pack(fill="x", pady=1)
            self.account_buttons[a["email"]] = b
        self._highlight_account()
        for p in self.pages.values():
            p.on_account_changed()

    def _highlight_account(self):
        for email, b in self.account_buttons.items():
            active = email == self.ctx.current_email
            b.configure(fg_color=theme.ACCENT_SOFT if active else "transparent",
                        font=theme.font(12, "bold" if active else "normal"))

    def select_account(self, email: str):
        if self.runner.busy:
            messagebox.showinfo("Drive Yönetici", "Bir işlem sürerken hesap değiştirilemez.")
            return
        self.ctx.current_email = email
        self._highlight_account()
        for p in self.pages.values():
            p.on_account_changed()
        if self.current_page == "setup":
            self.show("backup")

    def add_account(self):
        if not self.ctx.accounts.has_client_config():
            messagebox.showinfo("Drive Yönetici", "Önce Kurulum ekranından credentials.json dosyasını seçin.")
            self.show("setup")
            return
        messagebox.showinfo("Hesap ekle", "Tarayıcınızda Google giriş sayfası açılacak.\n\nGiriş yapıp izin "
                                          "verdikten sonra bu pencereye dönün. Şifreniz bu uygulamaya yazılmaz.")

        def done(email):
            self.ctx.current_email = email
            self.refresh_accounts()
            self.show("backup")
            messagebox.showinfo("Drive Yönetici", f"{email} eklendi.")

        self.runner.run(lambda t: self.ctx.accounts.add_account_interactive(), done)

    def remove_account(self):
        email = self.ctx.current_email
        if not email:
            return
        if not messagebox.askyesno("Hesabı çıkar",
                                   f"{email} bu uygulamadan çıkarılsın mı?\n\nBilgisayardaki oturum anahtarı silinir "
                                   "ve Google'daki erişim iptal edilir. Drive'ınızdaki dosyalara dokunulmaz."):
            return

        def done(_):
            self.ctx.current_email = None
            self.ctx.invalidate(email)
            self.refresh_accounts()

        self.runner.run(lambda t: self.ctx.accounts.remove_account(email), done, show_error)

    # ---- gezinme ------------------------------------------------------------------
    def show(self, key: str):
        page = self.pages[key]
        page.tkraise()
        self.current_page = key
        for k, b in self.nav_buttons.items():
            b.configure(fg_color=theme.NAV_ACTIVE if k == key else "transparent",
                        font=theme.font(13, "bold" if k == key else "normal"))
        try:
            page.on_show()
        except Exception as exc:  # noqa: BLE001
            show_error(exc)

    def set_theme(self, label: str):
        mode = THEMES[label]
        self.ctx.settings.set("theme", mode)
        ctk.set_appearance_mode(mode)
        self.after(50, self._restyle)

    def _restyle(self):
        theme.style_treeview(self)
        for p in self.pages.values():
            for chart in _find(p, "BarChart"):
                chart.redraw()

    def on_close(self):
        if self.runner.busy and not messagebox.askyesno(
                "Drive Yönetici", "Bir işlem sürüyor. Yine de kapatılsın mı?\n\nYarım kalan yedekleme bir sonraki "
                                  "açılışta kaldığı yerden devam eder."):
            return
        self.runner.cancel()
        self.destroy()


def _find(widget, cls_name: str):
    for child in widget.winfo_children():
        if type(child).__name__ == cls_name:
            yield child
        yield from _find(child, cls_name)
