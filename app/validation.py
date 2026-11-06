"""Kullanıcı girdisi doğrulama (yollar, dosya/klasör adları, desenler)."""
from __future__ import annotations

import os
import re
from pathlib import Path

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_WIN_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


class ValidationError(ValueError):
    """Kullanıcıya gösterilebilir Türkçe hata mesajı taşır."""


def _forbidden_roots() -> list[Path]:
    roots = []
    for var in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramData"):
        v = os.environ.get(var)
        if v:
            roots.append(Path(v).resolve())
    return roots


def validate_backup_folder(raw: str) -> Path:
    """Yedeklenecek yerel klasörü doğrular ve mutlak yol döndürür."""
    if not raw or not raw.strip():
        raise ValidationError("Klasör yolu boş olamaz.")
    if _CONTROL.search(raw):
        raise ValidationError("Klasör yolunda geçersiz karakter var.")
    p = Path(raw.strip()).expanduser()
    if not p.is_absolute():
        raise ValidationError("Lütfen tam bir klasör yolu seçin (ör. C:\\Kullanıcılar\\...).")
    try:
        p = p.resolve(strict=True)
    except (OSError, RuntimeError):
        raise ValidationError(f"Klasör bulunamadı: {raw}")
    if not p.is_dir():
        raise ValidationError(f"Bu bir klasör değil: {p}")
    if p.parent == p:
        raise ValidationError("Bir sürücünün tamamı (ör. C:\\) seçilemez; alt klasörleri seçin.")
    for root in _forbidden_roots():
        if p == root or root in p.parents:
            raise ValidationError(f"Sistem klasörleri yedeklenemez: {p}")
    return p


def sanitize_drive_name(name: str, max_len: int = 200) -> str:
    """Drive'da oluşturulacak klasör/dosya adını temizler."""
    if name is None:
        raise ValidationError("Ad boş olamaz.")
    cleaned = _CONTROL.sub("", str(name)).strip()
    cleaned = cleaned.replace("/", "-").replace("\\", "-")
    if not cleaned or cleaned in {".", ".."}:
        raise ValidationError("Geçerli bir ad girin.")
    return cleaned[:max_len]


def validate_category_name(name: str) -> str:
    n = sanitize_drive_name(name, max_len=60)
    if n.upper() in _WIN_RESERVED:
        raise ValidationError(f"'{n}' ayrılmış bir addır.")
    return n


def validate_extension(ext: str) -> str:
    e = ext.strip().lower().lstrip(".")
    if not e or not re.fullmatch(r"[a-z0-9_+\-]{1,15}", e):
        raise ValidationError(f"Geçersiz uzantı: '{ext}'")
    return e


def validate_exclude_pattern(pattern: str) -> str:
    p = pattern.strip().replace("\\", "/")
    if not p:
        raise ValidationError("Boş dışlama deseni olamaz.")
    if _CONTROL.search(p) or len(p) > 200:
        raise ValidationError(f"Geçersiz dışlama deseni: '{pattern}'")
    if ".." in p.split("/"):
        raise ValidationError("Dışlama deseninde '..' kullanılamaz.")
    return p


def validate_email(email: str) -> str:
    e = (email or "").strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", e) or len(e) > 254:
        raise ValidationError(f"Geçersiz e-posta adresi: '{email}'")
    return e


def validate_drive_id(file_id: str) -> str:
    if not file_id or not re.fullmatch(r"[A-Za-z0-9_\-]{1,200}", file_id):
        raise ValidationError("Geçersiz Drive kimliği.")
    return file_id
