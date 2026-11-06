"""Rate limit (403/429) ve geçici hatalar için üstel geri çekilme."""
from __future__ import annotations

import json
import logging
import random
import socket
import time
from typing import Callable, TypeVar

log = logging.getLogger(__name__)
T = TypeVar("T")

RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}
RETRYABLE_403_REASONS = {"rateLimitExceeded", "userRateLimitExceeded", "backendError", "sharingRateLimitExceeded"}


def _status_and_reason(exc: Exception) -> tuple[int | None, str]:
    resp = getattr(exc, "resp", None)
    status = getattr(resp, "status", None)
    if status is None:
        status = getattr(exc, "status_code", None)
    reason = ""
    content = getattr(exc, "content", b"") or b""
    try:
        data = json.loads(content.decode("utf-8") if isinstance(content, bytes) else content)
        errs = data.get("error", {}).get("errors") or []
        if errs:
            reason = errs[0].get("reason", "")
    except Exception:
        pass
    return (int(status) if status is not None else None), reason


def is_retryable(exc: Exception) -> bool:
    if isinstance(exc, (socket.timeout, ConnectionError, TimeoutError)):
        return True
    name = type(exc).__name__
    if name in {"ServerNotFoundError", "RedirectMissingLocation", "IncompleteRead"}:
        return True
    status, reason = _status_and_reason(exc)
    if status in RETRYABLE_STATUS:
        return True
    if status == 403 and reason in RETRYABLE_403_REASONS:
        return True
    return False


def backoff_delay(attempt: int, base: float = 1.0, cap: float = 64.0, rng: Callable[[], float] = random.random) -> float:
    """attempt=0 -> ~1sn, 1 -> ~2sn, 2 -> ~4sn ... + rastgele titreşim, üst sınır cap."""
    return min(cap, base * (2 ** attempt)) + rng()


def with_backoff(fn: Callable[[], T], *, max_attempts: int = 7, sleep: Callable[[float], None] = time.sleep,
                 cancel: Callable[[], bool] | None = None) -> T:
    attempt = 0
    while True:
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            if not is_retryable(exc) or attempt >= max_attempts - 1:
                raise
            if cancel and cancel():
                raise
            delay = backoff_delay(attempt)
            log.warning("Geçici hata (%s), %.1f sn sonra tekrar denenecek (deneme %d)", exc, delay, attempt + 1)
            sleep(delay)
            attempt += 1
