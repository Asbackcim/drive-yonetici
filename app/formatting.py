"""İnsan okunur biçimlendirme yardımcıları."""
from __future__ import annotations

from datetime import datetime, timezone

_UNITS = ["B", "KB", "MB", "GB", "TB"]


def human_bytes(n: float | int | None) -> str:
    if n is None:
        return "-"
    n = float(n)
    for unit in _UNITS:
        if abs(n) < 1024 or unit == _UNITS[-1]:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}".replace(".", ",")
        n /= 1024
    return f"{n:.1f} TB"


def human_duration(seconds: float | None) -> str:
    if seconds is None or seconds != seconds or seconds < 0:
        return "hesaplanıyor"
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h} sa {m} dk"
    if m:
        return f"{m} dk {s} sn"
    return f"{s} sn"


def parse_rfc3339(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def short_date(value: str | None) -> str:
    d = parse_rfc3339(value)
    if not d:
        return "-"
    return d.astimezone().strftime("%d.%m.%Y")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
