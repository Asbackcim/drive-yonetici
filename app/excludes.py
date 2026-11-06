"""Yedeklemede hariç tutma desenleri.

Kurallar:
- Joker içermeyen desen (ör. ``node_modules``) yolun herhangi bir BİLEŞENİYLE
  (klasör ya da dosya adı) birebir eşleşir; büyük/küçük harf duyarsızdır.
- Joker içeren ve '/' içermeyen desen (ör. ``*.tmp``, ``~$*``) her bileşene
  ayrı ayrı uygulanır.
- '/' içeren desen (ör. ``Projeler/*/build``) göreli yolun tamamına uygulanır.
"""
from __future__ import annotations

import fnmatch
from typing import Iterable

from .validation import validate_exclude_pattern

_WILDCARDS = set("*?[")


class ExcludeMatcher:
    def __init__(self, patterns: Iterable[str]):
        self.exact: set[str] = set()
        self.component_globs: list[str] = []
        self.path_globs: list[str] = []
        for raw in patterns:
            if not raw or not raw.strip():
                continue
            p = validate_exclude_pattern(raw).lower().rstrip("/")
            has_wild = any(c in _WILDCARDS for c in p)
            if "/" in p:
                self.path_globs.append(p)
            elif has_wild:
                self.component_globs.append(p)
            else:
                self.exact.add(p)

    def is_excluded(self, rel_path: str) -> bool:
        """rel_path: yedek kökü göreli yol, '/' veya '\\' ayraçlı."""
        norm = rel_path.replace("\\", "/").strip("/").lower()
        if not norm:
            return False
        parts = norm.split("/")
        for part in parts:
            if part in self.exact:
                return True
            for g in self.component_globs:
                if fnmatch.fnmatchcase(part, g):
                    return True
        for g in self.path_globs:
            if fnmatch.fnmatchcase(norm, g) or fnmatch.fnmatchcase(norm, g + "/*"):
                return True
        return False

    def is_name_excluded(self, name: str) -> bool:
        """Tek bir klasör/dosya adı için hızlı kontrol (tarama sırasında budama)."""
        n = name.lower()
        if n in self.exact:
            return True
        return any(fnmatch.fnmatchcase(n, g) for g in self.component_globs)
