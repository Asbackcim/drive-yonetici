"""Taşı/Kopyala, Günlük ve Kurulum sekmeleri."""
from __future__ import annotations

from tkinter import filedialog, messagebox

import customtkinter as ctk

from .. import paths
from ..formatting import human_bytes
from ..transfer import apply_transfer, collect_tree, preview_transfer
from ..validation import ValidationError
from . import theme
from .context import open_path, resource_path
from .page_base import Page
from .widgets import (DataTable, browse_drive, card, confirm_preview, heading, primary_button, secondary_button,
                      show_error)


# ===========================================================================
class TransferPage(Page):
    title = "Taşı/Kopyala"

    def __init__(self, master, ctx, runner):
        super().__init__(master, ctx, runner)
        self.items: list[dict] = []
        self.dest = {"id": "root", "name": "Drive'ım"}
        heading(self, "Hesaplar arası taşıma ve kopyalama",
                "Yöntem: kaynak hesap seçili öğeyi hedef hesapla geçici olarak (bildirim göndermeden) paylaşır, "
                "hedef hesap Google sunucularında kendi kopyasını oluşturur ve paylaşım hemen kaldırılır. Dosyalar "
                "bilgisayarınıza inmez, internet kotanız harcanmaz. Kopyalanamayan dosyalar otomatik olarak parça "
                "parça (diske yazmadan) aktarılır.").pack(fill="x", padx=28, pady=(24, 12))

        form = card(self)
        form.pack(fill="x", padx=28)
        g = ctk.CTkFrame(form, fg_color="transparent")
        g.pack(fill="x", padx=16, pady=14)
        mk = dict(width=280, fg_color=theme.SURFACE, button_color=theme.BORDER, text_color=theme.TEXT)
        ctk.CTkLabel(g, text="Kaynak hesap", text_color=theme.MUTED).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(g, text="Hedef hesap", text_color=theme.MUTED).grid(row=0, column=1, sticky="w", padx=(20, 0))
        self.src_m = ctk.CTkOptionMenu(g, values=["-"], command=lambda _v: self._clear_items(), **mk)
        self.src_m.grid(row=1, column=0, sticky="w")
        self.dst_m = ctk.CTkOptionMenu(g, values=["-"], command=lambda _v: self._reset_dest(), **mk)
        self.dst_m.grid(row=1, column=1, sticky="w", padx=(20, 0))
        ctk.CTkLabel(g, text="İşlem", text_color=theme.MUTED).grid(row=0, column=2, sticky="w", padx=(20, 0))
        self.mode = ctk.CTkSegmentedButton(g, values=["Kopyala", "Taşı"], **theme.SEGMENTED)
        self.mode.set("Kopyala")
        self.mode.grid(row=1, column=2, sticky="w", padx=(20, 0))

        b = ctk.CTkFrame(form, fg_color="transparent")
        b.pack(fill="x", padx=16, pady=(0, 14))
        secondary_button(b, "Kaynaktan dosya/klasör seç", self.pick_items, "file", width=230).pack(side="left")
        secondary_button(b, "Hedef klasörü seç", self.pick_dest, "folder", width=170).pack(side="left", padx=8)
        self.dest_lbl = ctk.CTkLabel(b, text="Hedef: Drive'ım", text_color=theme.TEXT, font=theme.font(12, "bold"))
        self.dest_lbl.pack(side="left", padx=8)

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=28, pady=(12, 0))
        self.status_label(bar).pack(side="left", fill="x", expand=True)
        primary_button(bar, "Önizle ve uygula", self.run_transfer, "arrows", width=180).pack(side="right")
        self.table = DataTable(self, [("name", "Seçilen öğe", 360, "w"), ("kind", "Tür", 100, "w"),
                                      ("size", "Boyut", 100, "e")])
        self.table.pack(fill="both", expand=True, padx=28, pady=(8, 24))

    def on_show(self):
        self.on_account_changed()

    def on_account_changed(self):
        emails = [a["email"] for a in self.ctx.accounts.list_accounts()] or ["-"]
        self.src_m.configure(values=emails)
        self.dst_m.configure(values=emails)
        if self.src_m.get() not in emails:
            self.src_m.set(self.ctx.current_email or emails[0])
        if self.dst_m.get() not in emails or self.dst_m.get() == self.src_m.get():
            others = [e for e in emails if e != self.src_m.get()]
            self.dst_m.set(others[0] if others else emails[0])

    def _clear_items(self):
        self.items = []
        self.table.clear()

    def _reset_dest(self):
        self.dest = {"id": "root", "name": "Drive'ım"}
        self.dest_lbl.configure(text="Hedef: Drive'ım")

    def _accounts(self):
        src, dst = self.src_m.get(), self.dst_m.get()
        if "-" in (src, dst):
            raise ValidationError("Bu özellik için en az iki hesap ekleyin.")
        if src == dst:
            raise ValidationError("Kaynak ve hedef hesap farklı olmalı.")
        return src, dst

    def pick_items(self):
        try:
            src, _ = self._accounts()
        except ValidationError as e:
            messagebox.showwarning("Drive Yönetici", str(e))
            return
        res = browse_drive(self, self.ctx.client(src), f"{src} - aktarılacak öğeleri seçin", pick_files=True)
        if res:
            self.items = res
            self.table.clear()
            for it in res:
                folder = it.get("mimeType") == "application/vnd.google-apps.folder"
                self.table.insert({"name": it["name"], "kind": "Klasör" if folder else "Dosya",
                                   "size": "" if folder else human_bytes(int(it.get("size") or 0))})

    def pick_dest(self):
        try:
            _, dst = self._accounts()
        except ValidationError as e:
            messagebox.showwarning("Drive Yönetici", str(e))
            return
        res = browse_drive(self, self.ctx.client(dst), f"{dst} - hedef klasörü seçin")
        if res:
            self.dest = res
            self.dest_lbl.configure(text=f"Hedef: {res['name']}")

    def run_transfer(self):
        try:
            src, dst = self._accounts()
        except ValidationError as e:
            messagebox.showwarning("Drive Yönetici", str(e))
            return
        if not self.items:
            messagebox.showinfo("Drive Yönetici", "Önce kaynaktan dosya ya da klasör seçin.")
            return
        move = self.mode.get() == "Taşı"
        sc, dc = self.ctx.client(src), self.ctx.client(dst)
        items, dest = list(self.items), dict(self.dest)

        def collect(tctx):
            tctx.progress("Klasör içerikleri okunuyor...")
            return [collect_tree(sc, it, cancel=tctx.cancelled) for it in items]

        def collected(roots):
            rows = preview_transfer(roots, src, dst, dest["name"], move)
            title = f"{'Taşı' if move else 'Kopyala'}: {src} -> {dst}"
            expl = ("Kopyalar hedef hesabın Drive'ında oluşturulur ve hedef hesabın kotasını kullanır. "
                    + ("Taşıma modunda, kopyalama HATASIZ biterse kaynaktaki öğe çöp kutusuna taşınır (silinmez). "
                       if move else "Kaynaktaki dosyalara dokunulmaz. ")
                    + "'Son işlemi geri al' oluşturulan kopyaları çöpe taşır ve kaynağı geri getirir.")
            if not confirm_preview(self, title, rows, expl):
                return
            dest_id = dest["id"] if dest["id"] != "root" else None

            def work(tctx):
                target = dest_id or dc.root_id()
                return apply_transfer(sc, dc, self.ctx.journal, roots, target, move,
                                      progress=lambda i, n, nm: tctx.progress(f"{i}/{n}: {nm}"),
                                      cancel=tctx.cancelled)

            def done(res):
                self.ctx.invalidate(src)
                self.ctx.invalidate(dst)
                self.ctx.notify("journal")
                msg = (f"Sunucu tarafı kopya: {res.copied}, akışla aktarılan: {res.streamed}"
                       + (f", kaynakta çöpe taşınan: {res.trashed_sources}" if move else "") + ".")
                if res.failed:
                    msg += f"\n\n{len(res.failed)} sorun:\n" + "\n".join(res.failed[:6])
                messagebox.showinfo("Drive Yönetici", msg)
                self._clear_items()

            self.runner.run(work, done, on_progress=self.set_status)

        self.runner.run(collect, collected, on_progress=self.set_status)


# ===========================================================================
STATUS_TR = {"applied": "Uygulandı", "failed": "Başarısız", "undone": "Geri alındı",
             "undo_partial": "Kısmen geri alındı", "open": "Yarım kaldı", "info": "Bilgi"}
KIND_TR = {"move": "Taşındı", "trash": "Çöpe taşındı", "create_folder": "Klasör oluşturuldu", "copy": "Kopyalandı"}


class JournalPage(Page):
    title = "Günlük"

    def __init__(self, master, ctx, runner):
        super().__init__(master, ctx, runner)
        heading(self, "İşlem günlüğü",
                "Uygulamanın Drive'ınızda yaptığı her değişiklik burada kayıtlıdır. 'Son işlemi geri al' en son "
                "uygulanan toplu işlemi tersine çevirir (taşınanlar eski yerine döner, çöpe atılanlar geri gelir).").pack(
            fill="x", padx=28, pady=(24, 12))
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=28)
        primary_button(bar, "Son işlemi geri al", self.undo_last, "undo", width=190).pack(side="left")
        secondary_button(bar, "Yenile", self.refresh, "refresh", width=100).pack(side="left", padx=8)
        secondary_button(bar, "Veri klasörünü aç", lambda: open_path(paths.app_dir()), "folder",
                         width=160).pack(side="left")
        self.status_label(self).pack(fill="x", padx=28, pady=6)
        self.batches = DataTable(self, [("when", "Tarih", 140, "w"), ("account", "Hesap", 200, "w"),
                                        ("title", "İşlem", 380, "w"), ("count", "Adım", 60, "e"),
                                        ("status", "Durum", 130, "w")], selectmode="browse", height=9)
        self.batches.pack(fill="both", expand=True, padx=28)
        self.batches.tv.bind("<<TreeviewSelect>>", lambda e: self.show_ops())
        self.ops = DataTable(self, [("kind", "Adım", 150, "w"), ("name", "Ad", 320, "w"),
                                    ("account", "Hesap", 200, "w"), ("undone", "Geri alındı", 100, "center")],
                             height=7)
        self.ops.pack(fill="both", expand=True, padx=28, pady=(10, 24))
        ctx.listeners.append(lambda ev: ev == "journal" and self.refresh())

    def on_show(self):
        self.refresh()

    def refresh(self):
        self.batches.clear()
        for b in self.ctx.journal.batches():
            self.batches.insert({"when": b["created_at"].replace("T", " "), "account": b["account"],
                                 "title": b["title"], "count": b["op_count"],
                                 "status": STATUS_TR.get(b["status"], b["status"])}, iid=str(b["id"]))
        self.ops.clear()

    def show_ops(self):
        self.ops.clear()
        sel = self.batches.selected()
        if not sel:
            return
        for o in self.ctx.journal.ops(int(sel[0]))[:5000]:
            self.ops.insert({"kind": KIND_TR.get(o["kind"], o["kind"]), "name": o["name"], "account": o["account"],
                             "undone": "Evet" if o["undone"] else ""})

    def undo_last(self):
        batch = self.ctx.journal.last_undoable_batch()
        if not batch:
            messagebox.showinfo("Drive Yönetici", "Geri alınacak bir işlem yok.")
            return
        if not messagebox.askyesno("Son işlemi geri al",
                                   f"Şu işlem geri alınacak:\n\n{batch['title']}\n({batch['created_at'].replace('T', ' ')})"
                                   "\n\nDevam edilsin mi?"):
            return

        def work(tctx):
            return self.ctx.journal.undo_batch(batch["id"], self.ctx.client,
                                               progress=lambda i, n, nm: tctx.progress(f"Geri alınıyor {i}/{n}: {nm}"))

        def done(res):
            n, errors = res
            self.ctx.invalidate()
            self.refresh()
            msg = f"{n} adım geri alındı."
            if errors:
                msg += f"\n\n{len(errors)} adım geri alınamadı (tekrar deneyebilirsiniz):\n" + "\n".join(errors[:6])
            messagebox.showinfo("Drive Yönetici", msg)

        self.runner.run(work, done, on_progress=self.set_status)


# ===========================================================================
class SetupPage(Page):
    title = "Kurulum"

    def __init__(self, master, ctx, runner, on_ready):
        super().__init__(master, ctx, runner)
        self.on_ready = on_ready
        body = ctk.CTkScrollableFrame(self, fg_color=theme.BG)
        body.pack(fill="both", expand=True)
        heading(body, "Hoş geldiniz",
                "Drive Yönetici, Google hesabınıza sizin oluşturduğunuz bir anahtar dosyasıyla bağlanır. Şifreniz "
                "bu uygulamaya hiçbir zaman yazılmaz; giriş Google'ın kendi sayfasında yapılır.").pack(
            fill="x", padx=28, pady=(24, 16))

        self.step1 = card(body)
        self.step1.pack(fill="x", padx=28, pady=(0, 12))
        ctk.CTkLabel(self.step1, text="Adım 1 - Google anahtar dosyası (credentials.json)", font=theme.font(15, "bold"),
                     text_color=theme.TEXT, anchor="w").pack(fill="x", padx=16, pady=(14, 4))
        ctk.CTkLabel(self.step1, justify="left", anchor="w", wraplength=880, text_color=theme.TEXT, font=theme.font(12),
                     text=("Bir kez yapılır, yaklaşık 10 dakika sürer:\n"
                           "  1. console.cloud.google.com adresinde yeni bir proje oluşturun.\n"
                           "  2. 'Google Drive API'yi etkinleştirin.\n"
                           "  3. 'OAuth izin ekranı'nı 'Harici' ve 'Test' modunda ayarlayıp Gmail adreslerinizi "
                           "test kullanıcısı olarak ekleyin.\n"
                           "  4. 'Masaüstü uygulaması' türünde OAuth istemcisi oluşturup JSON dosyasını indirin.\n"
                           "  5. İndirdiğiniz dosyayı aşağıdaki düğmeyle seçin.\n"
                           "Ayrıntılı, ekran metinli anlatım için 'Kurulum rehberini aç' düğmesine basın.")).pack(
            fill="x", padx=16)
        b = ctk.CTkFrame(self.step1, fg_color="transparent")
        b.pack(fill="x", padx=16, pady=14)
        primary_button(b, "credentials.json dosyasını seç", self.pick_credentials, "file", width=260).pack(side="left")
        secondary_button(b, "Kurulum rehberini aç", self.open_guide, "file", width=190).pack(side="left", padx=8)
        self.cred_lbl = ctk.CTkLabel(b, text="", text_color=theme.MUTED)
        self.cred_lbl.pack(side="left", padx=8)

        step2 = card(body)
        step2.pack(fill="x", padx=28)
        ctk.CTkLabel(step2, text="Adım 2 - Google hesabı ekleyin", font=theme.font(15, "bold"), text_color=theme.TEXT,
                     anchor="w").pack(fill="x", padx=16, pady=(14, 4))
        ctk.CTkLabel(step2, justify="left", anchor="w", wraplength=880, text_color=theme.TEXT, font=theme.font(12),
                     text=("Sol menüdeki 'Hesap ekle' düğmesine basın. Tarayıcınızda Google giriş sayfası açılır. "
                           "'Google bu uygulamayı doğrulamadı' uyarısı görürseniz bu normaldir (uygulamayı siz "
                           "oluşturdunuz): 'Gelişmiş' > 'Drive Yönetici'ye git (güvenli değil)' seçin ve izin verin. "
                           "Birden fazla hesabı tek tek ekleyebilirsiniz.\n\n"
                           "Not: Google, 'Test' modundaki uygulamaların oturumunu 7 günde bir kapatır. Böyle olursa "
                           "aynı hesabı 'Hesap ekle' ile yeniden bağlamanız yeterlidir.")).pack(fill="x", padx=16,
                                                                                                    pady=(0, 14))
        self.refresh()

    def refresh(self):
        if self.ctx.accounts.has_client_config():
            self.cred_lbl.configure(text="Anahtar dosyası yüklü.", text_color=theme.ACCENT)
        else:
            self.cred_lbl.configure(text="Henüz seçilmedi.", text_color=theme.MUTED)

    def on_show(self):
        self.refresh()

    def pick_credentials(self):
        p = filedialog.askopenfilename(title="credentials.json dosyasını seçin",
                                       filetypes=[("JSON dosyası", "*.json"), ("Tüm dosyalar", "*.*")])
        if not p:
            return
        try:
            self.ctx.accounts.install_client_config(p)
        except ValidationError as e:
            messagebox.showwarning("Drive Yönetici", str(e))
            return
        except OSError as e:
            show_error(e)
            return
        self.refresh()
        messagebox.showinfo("Drive Yönetici", "Anahtar dosyası kaydedildi. Şimdi sol menüden 'Hesap ekle'ye basın.")
        self.on_ready()

    def open_guide(self):
        p = resource_path("KURULUM.md")
        if p.exists():
            open_path(p)
        else:
            messagebox.showinfo("Drive Yönetici", "KURULUM.md bulunamadı.")
