"""Yedekleme sekmesi."""
from __future__ import annotations

from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from ..backup import BackupEngine, BackupState, QuotaError, backup_folder_name, build_plan, scan
from ..excludes import ExcludeMatcher
from ..formatting import human_bytes, human_duration
from ..settings import DEFAULT_EXCLUDES
from ..validation import ValidationError, validate_backup_folder, validate_exclude_pattern
from . import theme
from .page_base import Page
from .widgets import DataTable, card, heading, primary_button, secondary_button, show_error

NEW_SET = "Yeni yedek seti oluştur"


class BackupPage(Page):
    title = "Yedekleme"

    def __init__(self, master, ctx, runner):
        super().__init__(master, ctx, runner)
        self.plan = None
        self.engine: BackupEngine | None = None
        self.sets: dict[str, int] = {}

        body = ctk.CTkScrollableFrame(self, fg_color=theme.BG)
        body.pack(fill="both", expand=True)
        heading(body, "Bilgisayar yedeği",
                "Seçtiğiniz klasörler, seçili hesabın Drive'ında 'Bilgisayar Yedeği - <tarih>' klasörüne yüklenir. "
                "Sonraki çalıştırmalarda yalnızca yeni ve değişen dosyalar gönderilir. Bilgisayarınızdaki dosyalara "
                "dokunulmaz; Drive'daki hiçbir dosya silinmez.").pack(fill="x", padx=28, pady=(24, 16))

        row = ctk.CTkFrame(body, fg_color="transparent")
        row.pack(fill="x", padx=28)
        row.grid_columnconfigure((0, 1), weight=1, uniform="c")

        # kaynak klasörler
        src = card(row)
        src.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        ctk.CTkLabel(src, text="Yedeklenecek klasörler", font=theme.font(14, "bold"), text_color=theme.TEXT,
                     anchor="w").pack(fill="x", padx=16, pady=(14, 6))
        self.src_table = DataTable(src, [("path", "Klasör", 380, "w")], height=6)
        self.src_table.pack(fill="both", expand=True, padx=16)
        b = ctk.CTkFrame(src, fg_color="transparent")
        b.pack(fill="x", padx=16, pady=12)
        secondary_button(b, "Klasör ekle", self.add_folder, "plus", width=130).pack(side="left")
        secondary_button(b, "Seçileni kaldır", self.remove_folder, "trash", width=140).pack(side="left", padx=8)

        # dışlama desenleri
        ex = card(row)
        ex.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        ctk.CTkLabel(ex, text="Hariç tutulanlar (her satıra bir desen)", font=theme.font(14, "bold"),
                     text_color=theme.TEXT, anchor="w").pack(fill="x", padx=16, pady=(14, 0))
        ctk.CTkLabel(ex, text="Ad (node_modules), joker (*.tmp) ya da yol deseni (Projeler/*/build).",
                     font=theme.font(11), text_color=theme.MUTED, anchor="w").pack(fill="x", padx=16)
        self.ex_box = ctk.CTkTextbox(ex, height=150, font=ctk.CTkFont(family="Consolas", size=12),
                                     fg_color=theme.BG, border_width=1, border_color=theme.BORDER)
        self.ex_box.pack(fill="both", expand=True, padx=16, pady=6)
        b2 = ctk.CTkFrame(ex, fg_color="transparent")
        b2.pack(fill="x", padx=16, pady=(0, 12))
        secondary_button(b2, "Kaydet", self.save_excludes, width=90).pack(side="left")
        secondary_button(b2, "Varsayılana dön", self.reset_excludes, width=130).pack(side="left", padx=8)

        # ayarlar + eylemler
        opt = card(body)
        opt.pack(fill="x", padx=28, pady=16)
        g = ctk.CTkFrame(opt, fg_color="transparent")
        g.pack(fill="x", padx=16, pady=14)
        ctk.CTkLabel(g, text="Yedek seti", text_color=theme.MUTED, font=theme.font(12)).grid(row=0, column=0, sticky="w")
        self.set_menu = ctk.CTkOptionMenu(g, values=[NEW_SET], width=320, fg_color=theme.SURFACE,
                                          button_color=theme.BORDER, text_color=theme.TEXT,
                                          command=lambda _v: self._reset_plan())
        self.set_menu.grid(row=1, column=0, sticky="w", padx=(0, 20))
        ctk.CTkLabel(g, text="Aynı anda yüklenen dosya", text_color=theme.MUTED,
                     font=theme.font(12)).grid(row=0, column=1, sticky="w")
        self.workers = ctk.CTkSegmentedButton(g, values=["1", "2", "3", "4", "6"],
                                              command=self._save_workers, **theme.SEGMENTED)
        self.workers.grid(row=1, column=1, sticky="w")
        self.workers.set(str(ctx.settings.get("parallel_uploads")))

        actions = ctk.CTkFrame(opt, fg_color="transparent")
        actions.pack(fill="x", padx=16, pady=(0, 14))
        self.analyze_btn = secondary_button(actions, "1. Analiz et", self.analyze, "search", width=150)
        self.analyze_btn.pack(side="left")
        self.start_btn = primary_button(actions, "2. Yedeklemeyi başlat", self.start, "upload", width=210,
                                        state="disabled")
        self.start_btn.pack(side="left", padx=10)
        self.stop_btn = secondary_button(actions, "Durdur", self.stop, "stop", width=110, state="disabled")
        self.stop_btn.pack(side="left")

        # ilerleme
        prog = card(body)
        prog.pack(fill="x", padx=28, pady=(0, 24))
        self.summary = ctk.CTkLabel(prog, text="Analiz için klasör ekleyip '1. Analiz et' düğmesine basın.",
                                    font=theme.font(13), text_color=theme.TEXT, anchor="w", justify="left",
                                    wraplength=900)
        self.summary.pack(fill="x", padx=16, pady=(14, 8))
        self.bar = ctk.CTkProgressBar(prog, progress_color=theme.ACCENT, fg_color=theme.BORDER, height=10)
        self.bar.pack(fill="x", padx=16)
        self.bar.set(0)
        self.detail = ctk.CTkLabel(prog, text="", font=theme.font(12), text_color=theme.MUTED, anchor="w",
                                   justify="left", wraplength=900)
        self.detail.pack(fill="x", padx=16, pady=(8, 14))

        self._load_sources()
        self._load_excludes()

    # ---- kaynaklar ---------------------------------------------------------------
    def _sources(self) -> list[str]:
        return list(self.ctx.settings.get("backup_folders") or [])

    def _load_sources(self):
        self.src_table.clear()
        for i, p in enumerate(self._sources()):
            self.src_table.insert({"path": p}, iid=str(i))

    def add_folder(self):
        chosen = filedialog.askdirectory(title="Yedeklenecek klasörü seçin", mustexist=True)
        if not chosen:
            return
        try:
            p = str(validate_backup_folder(chosen))
        except ValidationError as e:
            messagebox.showwarning("Drive Yönetici", str(e))
            return
        current = self._sources()
        for existing in current:
            ep = Path(existing)
            if Path(p) == ep or ep in Path(p).parents:
                messagebox.showinfo("Drive Yönetici", f"Bu klasör zaten yedekleniyor:\n{existing}")
                return
        current = [c for c in current if Path(p) not in Path(c).parents]  # alt klasörleri birleştir
        current.append(p)
        self.ctx.settings.set("backup_folders", current)
        self._load_sources()
        self._reset_plan()

    def remove_folder(self):
        sel = self.src_table.selected()
        if not sel:
            return
        current = self._sources()
        for iid in sorted((int(s) for s in sel), reverse=True):
            current.pop(iid)
        self.ctx.settings.set("backup_folders", current)
        self._load_sources()
        self._reset_plan()

    # ---- dışlamalar ---------------------------------------------------------------
    def _load_excludes(self):
        self.ex_box.delete("1.0", "end")
        self.ex_box.insert("1.0", "\n".join(self.ctx.settings.get("exclude_patterns")))

    def _parse_excludes(self) -> list[str]:
        lines = [ln.strip() for ln in self.ex_box.get("1.0", "end").splitlines() if ln.strip()]
        return [validate_exclude_pattern(ln) for ln in lines]

    def save_excludes(self):
        try:
            pats = self._parse_excludes()
            ExcludeMatcher(pats)
        except ValidationError as e:
            messagebox.showwarning("Drive Yönetici", str(e))
            return
        self.ctx.settings.set("exclude_patterns", pats)
        self._reset_plan()
        self.set_status("Kaydedildi")

    def reset_excludes(self):
        self.ctx.settings.set("exclude_patterns", list(DEFAULT_EXCLUDES))
        self._load_excludes()
        self._reset_plan()

    def _save_workers(self, v):
        self.ctx.settings.set("parallel_uploads", int(v))

    # ---- setler -------------------------------------------------------------------
    def on_show(self):
        self.on_account_changed()

    def on_account_changed(self):
        email = self.ctx.current_email
        self.sets = {}
        values = [NEW_SET]
        if email:
            for s in self.ctx.backup_state.sets_for(email):
                label = f"{s['name']}  (son: {(s['last_run'] or 'hiç')[:16].replace('T', ' ')})"
                self.sets[label] = s["id"]
                values.append(label)
        self.set_menu.configure(values=values)
        self.set_menu.set(values[1] if len(values) > 1 else NEW_SET)
        self._reset_plan()

    def _reset_plan(self):
        self.plan = None
        if not self.runner.busy:
            self.start_btn.configure(state="disabled")

    # ---- analiz -------------------------------------------------------------------
    def analyze(self):
        try:
            email = self.ctx.require_account()
            sources = [validate_backup_folder(p) for p in self._sources()]
            if not sources:
                raise ValidationError("Önce en az bir klasör ekleyin.")
            matcher = ExcludeMatcher(self._parse_excludes())
        except (ValidationError, RuntimeError) as e:
            messagebox.showwarning("Drive Yönetici", str(e))
            return
        set_id = self.sets.get(self.set_menu.get(), -1)
        state: BackupState = self.ctx.backup_state

        def work(tctx):
            errors: list[str] = []
            files = scan(sources, matcher, errors, cancel=tctx.cancelled)
            plan = build_plan(state, set_id, files, cancel=tctx.cancelled,
                              on_scan=lambda n: tctx.progress(f"Klasörler taranıyor... {n:,} dosya".replace(",", ".")))
            plan.scan_errors.extend(errors)
            limit, usage = self.ctx.client(email).quota()
            return plan, limit, usage

        def done(res):
            plan, limit, usage = res
            self.plan = plan
            self.quota = (limit, usage)
            new = sum(1 for i in plan.items if i.decision == "new")
            changed = sum(1 for i in plan.items if i.decision == "changed")
            txt = (f"Yüklenecek: {new:,} yeni + {changed:,} değişen dosya, toplam {human_bytes(plan.upload_bytes)}.   "
                   f"Değişmeyen: {plan.skipped + len(plan.touched):,} dosya (atlanacak).").replace(",", ".")
            if limit is not None:
                free = max(0, limit - usage)
                txt += f"\nDrive'da boş alan: {human_bytes(free)} / {human_bytes(limit)}."
                if plan.upload_bytes > free:
                    txt += "  UYARI: Boş alan yetersiz! Yer açın ya da daha az klasör seçin."
            if plan.scan_errors:
                txt += f"\nOkunamayan {len(plan.scan_errors)} öğe atlanacak (ör. {plan.scan_errors[0][:120]})."
            self.summary.configure(text=txt)
            self.detail.configure(text="")
            self.bar.set(0)
            self.start_btn.configure(state="normal" if plan.upload_items or plan.touched else "disabled")
            if not plan.upload_items:
                self.detail.configure(text="Her şey güncel. Yüklenecek yeni dosya yok.")

        self.summary.configure(text="Analiz ediliyor...")
        self.runner.run(work, done, on_progress=lambda msg: self.summary.configure(text=msg))

    # ---- yükleme -------------------------------------------------------------------
    def start(self):
        if not self.plan:
            return
        try:
            email = self.ctx.require_account()
            client = self.ctx.client(email)
        except RuntimeError as e:
            messagebox.showwarning("Drive Yönetici", str(e))
            return
        limit, usage = getattr(self, "quota", (None, 0))
        if limit is not None and self.plan.upload_bytes > max(0, limit - usage):
            if not messagebox.askyesno("Drive'da yer yetersiz",
                                       f"Yüklenecek veri {human_bytes(self.plan.upload_bytes)}, Drive'da boş alan "
                                       f"{human_bytes(max(0, limit - usage))}.\n\nYine de başlansın mı? Alan "
                                       "dolduğunda kalan dosyalar yüklenemez."):
                return
        set_label = self.set_menu.get()
        state = self.ctx.backup_state
        if set_label == NEW_SET:
            set_id = state.create_set(email, backup_folder_name())
        else:
            set_id = self.sets[set_label]
        self.engine = BackupEngine(client, state, set_id, workers=int(self.ctx.settings.get("parallel_uploads")),
                                   chunk_mb=int(self.ctx.settings.get("chunk_mb")))
        plan, engine = self.plan, self.engine

        def work(tctx):
            return engine.run(plan, on_progress=lambda snap: tctx.progress(snap))

        def progress(snap):
            tb = snap["total_bytes"] or 1
            self.bar.set(min(1.0, snap["done_bytes"] / tb))
            speed = snap["speed"]
            self.summary.configure(text=(f"{snap['done_files']:,} / {snap['total_files']:,} dosya   ·   "
                                         f"{human_bytes(snap['done_bytes'])} / {human_bytes(snap['total_bytes'])}   ·   "
                                         f"{human_bytes(speed)}/sn   ·   kalan {human_duration(snap['eta'])}")
                                   .replace(",", "."))
            active = ", ".join(a.rsplit("/", 1)[-1] for a in snap["active"][:3])
            self.detail.configure(text=(f"Yükleniyor: {active}" if active else "") +
                                  (f"   ·   hatalı: {snap['failed']}" if snap["failed"] else ""))

        def done(tracker):
            self._set_running(False)
            self.plan = None
            self.start_btn.configure(state="disabled")
            if engine.cancelled:
                self.detail.configure(text="Durduruldu. Yarım kalan dosyalar bir sonraki çalıştırmada kaldığı "
                                           "yerden devam eder.")
            else:
                msg = f"Yedekleme tamamlandı: {tracker.done_files - len(tracker.failed)} dosya yüklendi."
                if tracker.failed:
                    msg += f" {len(tracker.failed)} dosya yüklenemedi (ör. {tracker.failed[0][:160]})."
                self.detail.configure(text=msg)
            self.ctx.journal.finish_batch(
                self.ctx.journal.start_batch(email, f"Yedekleme: {tracker.done_files} dosya, "
                                                    f"{human_bytes(tracker.done_bytes)}"), "info")
            self.ctx.invalidate(email)
            self.ctx.notify("journal")
            self.on_account_changed()

        def error(exc):
            self._set_running(False)
            if isinstance(exc, QuotaError):
                messagebox.showwarning("Drive Yönetici", "Drive'da yeterli alan yok.")
            else:
                show_error(exc)

        if self.runner.run(work, done, error, progress):
            self._set_running(True)

    def stop(self):
        if self.engine:
            self.engine.cancel()
        self.runner.cancel()
        self.detail.configure(text="Durduruluyor... (yüklenmekte olan parça bitince duracak)")

    def _set_running(self, running: bool):
        self.stop_btn.configure(state="normal" if running else "disabled")
        self.analyze_btn.configure(state="disabled" if running else "normal")
        self.start_btn.configure(state="disabled")
