"""Uygulama veri klasörleri.

Tüm kalıcı veriler %APPDATA%\\DriveYonetici altında tutulur. Token'lar burada
DEĞİL, Windows Kimlik Bilgisi Yöneticisi'nde (keyring / DPAPI) saklanır.
"""
from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "DriveYonetici"


def app_dir() -> Path:
    override = os.environ.get("DRIVE_YONETICI_HOME")
    if override:
        base = Path(override)
    else:
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / APP_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def credentials_path() -> Path:
    return app_dir() / "credentials.json"


def settings_path() -> Path:
    return app_dir() / "ayarlar.json"


def accounts_path() -> Path:
    return app_dir() / "hesaplar.json"


def backup_db_path() -> Path:
    return app_dir() / "yedek_durumu.sqlite3"


def journal_db_path() -> Path:
    return app_dir() / "islem_gunlugu.sqlite3"


def log_file_path() -> Path:
    return app_dir() / "uygulama.log"
