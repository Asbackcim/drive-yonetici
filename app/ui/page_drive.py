"""Kopyalar, Büyük/Eski ve Düzenle sekmeleri."""
from __future__ import annotations

from tkinter import messagebox

import customtkinter as ctk

from ..categorize import build_category_plan, category_distribution, normalize_rules
from ..duplicates import build_path_index, find_duplicates, parent_path, total_reclaimable
from ..formatting import human_bytes, short_date
from ..largeold import file_size, filter_files, last_activity
from ..operations import (apply_category_plan, apply_trash, preview_category_plan, preview_trash_duplicates,
                          preview_trash_files)
from ..validation import ValidationError
from . import theme
from .page_base import Page
from .widgets import (BarChart, DataTable, browse_drive, card, confirm_preview, heading, primary_button,
                      secondary_button, stat)

TRASH_NOTE = ("Seçilen dosyalar KALICI OLARAK SİLİNMEZ; Drive'ın çöp kutusuna taşınır. Google çöp kutusundaki "
              "dosyaları 30 gün saklar. 'Günlük' sekmesindeki 'Son işlemi geri al' ile hepsini geri getirebilirsiniz.")


def _after_apply(page: Page, res, email: str):
    page.ctx.invalidate(email)
    page.ctx.notify("journal")
    msg = f"{res.done} işlem uygulandı."
    if res.cancelled:
        msg += " (İşlem durduruldu.)"
    if res.failed:
        msg += f"\n\n{len(res.failed)} öğe başarısız oldu, ör.:\n" + "\n".join(res.failed[:5])
    messagebox.showinfo("Drive Yönetici", msg)


# ===========================================================================
class DuplicatesPage(Page):
    title = "Kopyalar"

    def __init__(self, master, ctx, runner):
        super().__init__(master, ctx, runner)
        self.groups = []
        self.row_map: dict[str, tuple[int, str]] = {}   # iid -> (grup indeksi, dosya id)
        heading(self, "Kopya dosya bulucu",
                "İçeriği birebir aynı olan dosyalar (Google'ın md5 sağlama toplamına göre) gruplanır. Her grupta "
                "bir dosya 'Korunacak' olarak önerilir: kopya adı taşımayan, 'İndirilenler' gibi geçici klasörlerde "
                "olmayan ve en eski olan.").pack(fill="x", padx=28, pady=(24, 12))
        stats = ctk.CTkFrame(self, fg_color="transparent")
        stats.pack(fill="x", padx=28)
        self.s_groups = stat(stats, "Kopya grubu")
        self.s_files = stat(stats, "Fazla kopya")
        self.s_space = stat(stats, "Kazanılacak alan")

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=28, pady=12)
        primary_button(bar, "Drive'ı tara", self.scan, "search", width=150).pack(side="left")
        secondary_button(bar, "Bunu koru", self.keep_selected, "check", width=120).pack(side="left", padx=8)
        secondary_button(bar, "Seçili kopyaları çöpe taşı", self.trash_selected, "trash", width=210).pack(side="left")
        secondary_button(bar, "Tüm önerilenleri çöpe taşı", self.trash_all, "trash", width=210).pack(side="left",
                                                                                                      padx=8)
        self.status_label(self).pack(fill="x", padx=28)
        self.table = DataTable(self, [("role", "Durum", 110, "w"), ("name", "Ad", 260, "w"),
                                      ("path", "Klasör", 330, "w"), ("size", "Boyut", 90, "e"),
                                      ("created", "Oluşturma", 100, "center")], tree=True)
        self.table.pack(fill="both", expand=True, padx=28, pady=(6, 24))

    def on_account_changed(self):
        self.groups = []
        self.render()

    def scan(self, force=True):
        try:
            self.ctx.require_account()
        except RuntimeError as e:
            messagebox.showwarning("Drive Yönetici", str(e))
            return

        def work(tctx):
            files = self.ctx.drive_files(tctx, force=force)
            tctx.progress("Kopyalar gruplanıyor...")
            return find_duplicates(files, build_path_index(files)), len(files)

        def done(res):
            self.groups, n = res
            self.render()
            self.set_status(f"{n:,} dosya tarandı.".replace(",", "."))

        self.set_status("Drive taranıyor...")
        self.runner.run(work, done, on_progress=self.set_status)

    def render(self):
        self.table.clear()
        self.row_map.clear()
        g_count = len(self.groups)
        self.s_groups.configure(text=f"{g_count:,}".replace(",", "."))
        self.s_files.configure(text=f"{sum(len(g.others) for g in self.groups):,}".replace(",", "."))
        self.s_space.configure(text=human_bytes(total_reclaimable(self.groups)))
        for gi, g in enumerate(self.groups[:3000]):
            k = g.keep
            pid = self.table.insert({"role": "Korunacak", "name": k["name"], "path": g.paths[k["id"]],
                                     "size": human_bytes(g.size), "created": short_date(k.get("createdTime"))},
                                    sort={"size": g.size}, tags=("keep",))
            self.row_map[pid] = (gi, k["id"])
            for o in g.others:
                owned = o.get("ownedByMe", True)
                cid = self.table.insert({"role": "Kopya" if owned else "Başkasına ait", "name": o["name"],
                                         "path": g.paths[o["id"]], "size": human_bytes(g.size),
                                         "created": short_date(o.get("createdTime"))}, parent=pid,
                                        tags=() if owned else ("muted",))
                self.row_map[cid] = (gi, o["id"])

    def keep_selected(self):
        sel = [s for s in self.table.selected() if s in self.row_map]
        if len(sel) != 1:
            messagebox.showinfo("Drive Yönetici", "Korumak istediğiniz tek bir dosyayı seçin.")
            return
        gi, fid = self.row_map[sel[0]]
        g = self.groups[gi]
        if g.keep["id"] == fid:
            return
        new_keep = next(o for o in g.others if o["id"] == fid)
        g.others = [o for o in g.others if o["id"] != fid] + [g.keep]
        g.keep = new_keep
        self.render()

    def _apply(self, rows, title):
        email = self.ctx.require_account()
        if not confirm_preview(self, title, rows, TRASH_NOTE):
            return
        client = self.ctx.client(email)

        def work(tctx):
            return apply_trash(client, self.ctx.journal, email, rows, title,
                               progress=lambda i, n, name: tctx.progress(f"{i}/{n}: {name}"), cancel=tctx.cancelled)

        def done(res):
            _after_apply(self, res, email)
            trashed = {r.file_id for r in rows}
            for g in self.groups:
                g.others = [o for o in g.others if o["id"] not in trashed]
            self.groups = [g for g in self.groups if g.others]
            self.render()

        self.runner.run(work, done, on_progress=self.set_status)

    def trash_selected(self):
        ids = {self.row_map[s][1] for s in self.table.selected() if s in self.row_map}
        if not ids:
            messagebox.showinfo("Drive Yönetici", "Listeden çöpe taşınacak kopyaları seçin (Ctrl ile çoklu seçim).")
            return
        rows = preview_trash_duplicates(self.groups, selected_ids=ids)
        self._apply(rows, f"Kopyaları çöpe taşı ({len(rows)} dosya)")

    def trash_all(self):
        rows = preview_trash_duplicates(self.groups)
        self._apply(rows, f"Tüm önerilen kopyaları çöpe taşı ({len(rows)} dosya)")


# ===========================================================================
SIZE_OPTS = {"Tüm boyutlar": 0, "> 10 MB": 10, "> 100 MB": 100, "> 500 MB": 500, "> 1 GB": 1024}
AGE_OPTS = {"Tüm tarihler": 0, "> 6 ay": 182, "> 1 yıl": 365, "> 2 yıl": 730, "> 5 yıl": 1825}
SORT_OPTS = {"Boyuta göre": "size", "En eskiden": "age"}


class LargeOldPage(Page):
    title = "Büyük/Eski"

    def __init__(self, master, ctx, runner):
        super().__init__(master, ctx, runner)
        self.files: list[dict] = []
        self.shown: dict[str, dict] = {}
        heading(self, "Büyük ve eski dosyalar",
                "Drive'ınızda en çok yer kaplayan ve uzun süredir açılmamış/değiştirilmemiş dosyalar. "
                "'Son etkinlik', son değiştirme ve son açılma tarihlerinin en yenisidir.").pack(
            fill="x", padx=28, pady=(24, 12))
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=28)
        top.grid_columnconfigure(1, weight=1)
        filt = card(top)
        filt.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        menu_kw = dict(width=170, fg_color=theme.SURFACE, button_color=theme.BORDER, text_color=theme.TEXT,
                       command=lambda _v: self.apply_filter())
        ctk.CTkLabel(filt, text="Filtre", font=theme.font(14, "bold"), text_color=theme.TEXT).pack(
            anchor="w", padx=16, pady=(14, 6))
        self.size_m = ctk.CTkOptionMenu(filt, values=list(SIZE_OPTS), **menu_kw)
        self.size_m.set("> 100 MB")
        self.size_m.pack(padx=16, pady=3)
        self.age_m = ctk.CTkOptionMenu(filt, values=list(AGE_OPTS), **menu_kw)
        self.age_m.pack(padx=16, pady=3)
        self.sort_m = ctk.CTkOptionMenu(filt, values=list(SORT_OPTS), **menu_kw)
        self.sort_m.pack(padx=16, pady=3)
        primary_button(filt, "Drive'ı tara", self.scan, "search", width=170).pack(padx=16, pady=(10, 14))
        ch = ctk.CTkFrame(top, fg_color="transparent")
        ch.grid(row=0, column=1, sticky="nsew")
        ctk.CTkLabel(ch, text="Türe göre alan dağılımı", font=theme.font(14, "bold"), text_color=theme.TEXT,
                     anchor="w").pack(fill="x")
        self.chart = BarChart(ch, height=190)
        self.chart.pack(fill="both", expand=True, pady=(6, 0))

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=28, pady=(12, 0))
        self.status_label(bar).pack(side="left", fill="x", expand=True)
        secondary_button(bar, "Seçilileri çöpe taşı", self.trash_selected, "trash", width=180).pack(side="right")
        self.table = DataTable(self, [("name", "Ad", 280, "w"), ("size", "Boyut", 90, "e"),
                                      ("modified", "Değiştirme", 100, "center"),
                                      ("viewed", "Son açılma", 100, "center"), ("path", "Klasör", 300, "w")])
        self.table.pack(fill="both", expand=True, padx=28, pady=(8, 24))

    def on_account_changed(self):
        self.files = []
        self.table.clear()
        self.chart.set_data({})

    def scan(self):
        try:
            self.ctx.require_account()
        except RuntimeError as e:
            messagebox.showwarning("Drive Yönetici", str(e))
            return

        def done(files):
            self.files = files
            self.index = build_path_index(files)
            self.chart.set_data(category_distribution(
                [f for f in files if f.get("ownedByMe", True)], self.ctx.settings.get("categories")))
            self.apply_filter()

        self.runner.run(lambda t: self.ctx.drive_files(t, force=True), done, on_progress=self.set_status)

    def apply_filter(self):
        if not self.files:
            return
        res = filter_files(self.files, min_size_mb=SIZE_OPTS[self.size_m.get()],
                           older_than_days=AGE_OPTS[self.age_m.get()], sort_by=SORT_OPTS[self.sort_m.get()])
        self.table.clear()
        self.shown = {}
        for f in res:
            act = last_activity(f)
            iid = self.table.insert({"name": f["name"], "size": human_bytes(file_size(f)),
                                     "modified": short_date(f.get("modifiedTime")),
                                     "viewed": short_date(f.get("viewedByMeTime")),
                                     "path": parent_path(f, self.index)}, iid=f["id"],
                                    sort={"size": file_size(f), "modified": f.get("modifiedTime") or "",
                                          "viewed": f.get("viewedByMeTime") or "",
                                          "activity": act.isoformat() if act else ""})
            self.shown[iid] = f
        total = sum(file_size(f) for f in res)
        self.set_status(f"{len(res):,} dosya, toplam {human_bytes(total)}".replace(",", ".") +
                        ("  (ilk 2.000 gösteriliyor)" if len(res) >= 2000 else ""))

    def trash_selected(self):
        files = [self.shown[i] for i in self.table.selected() if i in self.shown]
        if not files:
            messagebox.showinfo("Drive Yönetici", "Önce listeden dosya seçin (Ctrl/Shift ile çoklu seçim).")
            return
        email = self.ctx.require_account()
        rows = preview_trash_files(files, "Büyük/eski dosya temizliği")
        title = f"Büyük/eski dosyaları çöpe taşı ({len(rows)} dosya)"
        if not confirm_preview(self, title, rows, TRASH_NOTE):
            return
        client = self.ctx.client(email)

        def done(res):
            _after_apply(self, res, email)
            gone = {r.file_id for r in rows}
            self.files = [f for f in self.files if f["id"] not in gone]
            self.apply_filter()

        self.runner.run(lambda t: apply_trash(client, self.ctx.journal, email, rows, title,
                                              progress=lambda i, n, nm: t.progress(f"{i}/{n}: {nm}"),
                                              cancel=t.cancelled), done, on_progress=self.set_status)


# ===========================================================================
class OrganizePage(Page):
    title = "Düzenle"

    def __init__(self, master, ctx, runner):
        super().__init__(master, ctx, runner)
        self.folder = {"id": "root", "name": "Drive'ım"}
        self.plan = None
        heading(self, "Türüne göre klasörlere ayır",
                "Seçtiğiniz klasördeki dağınık dosyalar Belgeler, Resimler, Videolar, Müzik, Arşivler, Kod ve Diğer "
                "klasörlerine taşınmak üzere önerilir. Alt klasörlere dokunulmaz. Önce öneri, sonra önizleme, "
                "en son sizin onayınızla uygulama yapılır.").pack(fill="x", padx=28, pady=(24, 12))
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.pack(fill="both", expand=True, padx=28, pady=(0, 24))
        main.grid_columnconfigure(0, weight=3)
        main.grid_columnconfigure(1, weight=2)
        main.grid_rowconfigure(1, weight=1)

        bar = ctk.CTkFrame(main, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew")
        self.folder_lbl = ctk.CTkLabel(bar, text="Klasör: Drive'ım (kök)", font=theme.font(13, "bold"),
                                       text_color=theme.TEXT)
        self.folder_lbl.pack(side="left")
        secondary_button(bar, "Klasör seç", self.choose_folder, "folder", width=120).pack(side="left", padx=10)
        self.other_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(bar, text="'Diğer' klasörünü de kullan", variable=self.other_var, fg_color=theme.ACCENT,
                        hover_color=theme.ACCENT_HOVER, text_color=theme.TEXT).pack(side="left", padx=6)

        left = ctk.CTkFrame(main, fg_color="transparent")
        left.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        acts = ctk.CTkFrame(left, fg_color="transparent")
        acts.pack(fill="x")
        secondary_button(acts, "1. Öneri oluştur", self.suggest, "search", width=150).pack(side="left")
        primary_button(acts, "2. Önizle ve uygula", self.apply, "folder-tree", width=190).pack(side="left", padx=8)
        self.status_label(left).pack(fill="x", pady=6)
        self.table = DataTable(left, [("name", "Dosya", 260, "w"), ("cat", "Kategori", 100, "w"),
                                      ("target", "Hedef klasör", 200, "w"), ("size", "Boyut", 80, "e")])
        self.table.pack(fill="both", expand=True)

        right = card(main)
        right.grid(row=1, column=1, sticky="nsew", padx=(16, 0), pady=(10, 0))
        ctk.CTkLabel(right, text="Kategori kuralları", font=theme.font(14, "bold"), text_color=theme.TEXT,
                     anchor="w").pack(fill="x", padx=16, pady=(14, 0))
        ctk.CTkLabel(right, text="Her satır:  Kategori: uzantı, uzantı, ...\nEşleşmeyenler 'Diğer'e gider.",
                     font=theme.font(11), text_color=theme.MUTED, anchor="w", justify="left").pack(fill="x", padx=16)
        self.rules_box = ctk.CTkTextbox(right, font=ctk.CTkFont(family="Consolas", size=12), wrap="word",
                                        fg_color=theme.BG, border_width=1, border_color=theme.BORDER)
        self.rules_box.pack(fill="both", expand=True, padx=16, pady=8)
        rb = ctk.CTkFrame(right, fg_color="transparent")
        rb.pack(fill="x", padx=16, pady=(0, 14))
        secondary_button(rb, "Kuralları kaydet", self.save_rules, width=140).pack(side="left")
        secondary_button(rb, "Varsayılan", self.reset_rules, width=100).pack(side="left", padx=8)
        self._load_rules()

    # kurallar
    def _load_rules(self):
        rules = self.ctx.settings.get("categories")
        self.rules_box.delete("1.0", "end")
        self.rules_box.insert("1.0", "\n".join(f"{k}: {', '.join(v)}" for k, v in rules.items()))

    def _parse_rules(self) -> dict:
        rules = {}
        for ln in self.rules_box.get("1.0", "end").splitlines():
            if not ln.strip():
                continue
            if ":" not in ln:
                raise ValidationError(f"Satırda ':' eksik: {ln.strip()[:40]}")
            name, exts = ln.split(":", 1)
            rules[name.strip()] = [e for e in (x.strip() for x in exts.split(",")) if e]
        return normalize_rules(rules)

    def save_rules(self):
        try:
            rules = self._parse_rules()
        except ValidationError as e:
            messagebox.showwarning("Drive Yönetici", str(e))
            return
        self.ctx.settings.set("categories", rules)
        self._load_rules()
        self.set_status("Kurallar kaydedildi.")

    def reset_rules(self):
        from ..settings import DEFAULT_CATEGORIES
        self.ctx.settings.set("categories", DEFAULT_CATEGORIES)
        self._load_rules()

    # akış
    def on_account_changed(self):
        self.folder = {"id": "root", "name": "Drive'ım"}
        self.folder_lbl.configure(text="Klasör: Drive'ım (kök)")
        self.plan = None
        self.table.clear()

    def choose_folder(self):
        try:
            client = self.ctx.client()
        except RuntimeError as e:
            messagebox.showwarning("Drive Yönetici", str(e))
            return
        res = browse_drive(self, client, "Düzenlenecek klasörü seçin")
        if res:
            self.folder = res
            self.folder_lbl.configure(text=f"Klasör: {res['name']}")
            self.plan = None
            self.table.clear()

    def suggest(self):
        try:
            client = self.ctx.client()
            rules = self._parse_rules()
        except (RuntimeError, ValidationError) as e:
            messagebox.showwarning("Drive Yönetici", str(e))
            return
        folder = self.folder
        include_other = self.other_var.get()

        def work(tctx):
            tctx.progress("Klasör okunuyor...")
            pid = client.root_id() if folder["id"] == "root" else folder["id"]
            return build_category_plan(client.list_children(pid), pid, rules, include_other=include_other)

        def done(plan):
            self.plan = plan
            self.table.clear()
            for it in plan.items:
                self.table.insert({"name": it.name, "cat": it.category,
                                   "target": f"{folder['name']}/{it.target_folder_name}" +
                                             ("" if it.target_folder_id else "  (yeni)"),
                                   "size": human_bytes(it.size)}, sort={"size": it.size})
            summ = ", ".join(f"{k}: {v}" for k, v in plan.summary().items())
            self.set_status(f"{len(plan.items)} dosya için öneri. {summ}" if plan.items
                            else "Bu klasörde ayrılacak dağınık dosya yok.")

        self.runner.run(work, done, on_progress=self.set_status)

    def apply(self):
        if not self.plan or not self.plan.items:
            messagebox.showinfo("Drive Yönetici", "Önce '1. Öneri oluştur' ile bir öneri hazırlayın.")
            return
        email = self.ctx.require_account()
        rows = preview_category_plan(self.plan, self.folder["name"])
        title = f"Türe göre ayır: {self.folder['name']} ({len(self.plan.items)} dosya)"
        if not confirm_preview(self, title, rows, "Dosyalar yalnızca klasörler arasında taşınır; hiçbir dosya silinmez. "
                                                  "'Son işlemi geri al' ile tüm dosyalar eski yerine döner ve "
                                                  "oluşturulan boş klasörler çöpe taşınır."):
            return
        client, plan = self.ctx.client(email), self.plan

        def done(res):
            self.plan = None
            self.table.clear()
            _after_apply(self, res, email)

        self.runner.run(lambda t: apply_category_plan(client, self.ctx.journal, email, plan, title,
                                                      progress=lambda i, n, nm: t.progress(f"{i}/{n}: {nm}"),
                                                      cancel=t.cancelled), done, on_progress=self.set_status)
