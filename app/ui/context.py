"""Sayfalar arasında paylaşılan uygulama durumu."""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

from ..auth import AccountManager
from ..backup import BackupState
from ..journal import Journal
from ..settings import Settings


def resource_path(name: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return base / name


class AppContext:
    def __init__(self):
        self.settings = Settings()
        self.accounts = AccountManager()
        self.journal = Journal()
        self.backup_state = BackupState()
        self.current_email: str | None = None
        self._cache: dict[str, tuple[float, list[dict]]] = {}
        self._cache_lock = threading.Lock()
        self.listeners: list = []   # hesap/günlük değişince haber verilecek sayfalar

    # -- hesaplar ---------------------------------------------------------------
    def client(self, email: str | None = None):
        email = email or self.current_email
        if not email:
            raise RuntimeError("Önce sol menüden bir hesap seçin ya da ekleyin.")
        return self.accounts.client_for(email)

    def require_account(self) -> str:
        if not self.current_email:
            raise RuntimeError("Önce sol menüden bir hesap seçin ya da ekleyin.")
        return self.current_email

    # -- Drive dosya listesi önbelleği ------------------------------------------------
    def drive_files(self, task_ctx=None, force: bool = False, email: str | None = None) -> list[dict]:
        email = email or self.require_account()
        with self._cache_lock:
            hit = self._cache.get(email)
        if hit and not force and time.time() - hit[0] < 1800:
            return hit[1]
        client = self.client(email)

        def progress(n):
            if task_ctx:
                task_ctx.progress(f"Drive taranıyor... {n:,} öğe".replace(",", "."))

        files = client.list_all_files(progress=progress, cancel=task_ctx.cancelled if task_ctx else None)
        with self._cache_lock:
            self._cache[email] = (time.time(), files)
        return files

    def invalidate(self, email: str | None = None) -> None:
        with self._cache_lock:
            if email:
                self._cache.pop(email, None)
            else:
                self._cache.clear()

    def cache_age(self, email: str | None = None) -> float | None:
        hit = self._cache.get(email or self.current_email or "")
        return time.time() - hit[0] if hit else None

    def notify(self, event: str) -> None:
        for fn in list(self.listeners):
            try:
                fn(event)
            except Exception:
                pass


def open_path(p: Path) -> None:
    """Uygulamanın kendi dosyalarını/klasörünü açar (.md için ilişkilendirme yoksa Not Defteri)."""
    if not hasattr(os, "startfile"):
        return
    try:
        os.startfile(str(p))  # noqa: S606
    except OSError:
        import subprocess
        subprocess.Popen(["notepad.exe", str(p)])  # noqa: S603,S607
