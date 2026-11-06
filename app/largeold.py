"""Büyük / eski dosyaları süzme ve sıralama."""
from __future__ import annotations

from datetime import datetime, timedelta

from .categorize import FOLDER_MIME
from .formatting import now_utc, parse_rfc3339

MB = 1024 * 1024


def file_size(f: dict) -> int:
    return int(f.get("size") or f.get("quotaBytesUsed") or 0)


def last_activity(f: dict) -> datetime | None:
    """Son değiştirme ve son açma tarihlerinden en yenisi."""
    dates = [d for d in (parse_rfc3339(f.get("modifiedTime")), parse_rfc3339(f.get("viewedByMeTime"))) if d]
    return max(dates) if dates else None


def filter_files(files: list[dict], *, min_size_mb: float = 0, older_than_days: int = 0,
                 sort_by: str = "size", now: datetime | None = None, owned_only: bool = True,
                 limit: int | None = 2000) -> list[dict]:
    """sort_by: 'size' (büyükten küçüğe) veya 'age' (en eskiden yeniye)."""
    now = now or now_utc()
    min_bytes = int(min_size_mb * MB)
    cutoff = now - timedelta(days=older_than_days) if older_than_days > 0 else None
    out = []
    for f in files:
        if f.get("mimeType") == FOLDER_MIME or f.get("trashed"):
            continue
        if owned_only and f.get("ownedByMe") is False:
            continue
        if file_size(f) < min_bytes:
            continue
        if cutoff is not None:
            act = last_activity(f)
            if act is None or act > cutoff:
                continue
        out.append(f)
    if sort_by == "age":
        out.sort(key=lambda f: (last_activity(f) or now, -file_size(f)))
    else:
        out.sort(key=lambda f: -file_size(f))
    return out[:limit] if limit else out
