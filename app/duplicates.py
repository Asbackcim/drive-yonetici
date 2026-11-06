"""Drive'da md5Checksum ile aynı içerikli dosyaları bulma."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .categorize import FOLDER_MIME

# Bu adları taşıyan klasörler "geçici/dağınık" sayılır; korunacak kopya için daha az tercih edilir.
_WEAK_FOLDER_WORDS = ("indirilenler", "downloads", "download", "yeni klasör", "new folder", "kopya",
                      "copy", "temp", "geçici", "yedek eski", "untitled", "adsız")
_COPY_NAME = re.compile(r"(\(\d+\)|\bkopyası\b|\bcopy of\b|\bcopy\b|\bkopya\b|_\d+$)", re.IGNORECASE)


def build_path_index(files: list[dict], root_id: str | None = None) -> dict[str, str]:
    """Klasör id -> 'Drive'ım/A/B' biçiminde yol."""
    folders = {f["id"]: f for f in files if f.get("mimeType") == FOLDER_MIME}
    cache: dict[str, str] = {}

    def path_of(fid: str, depth: int = 0) -> str:
        if fid in cache:
            return cache[fid]
        if depth > 64 or fid not in folders:
            return "Drive'ım" if (root_id is None or fid == root_id or fid not in folders) else "?"
        f = folders[fid]
        parents = f.get("parents") or []
        parent_path = path_of(parents[0], depth + 1) if parents else "Benimle paylaşılanlar"
        cache[fid] = f"{parent_path}/{f.get('name', '?')}"
        return cache[fid]

    return {fid: path_of(fid) for fid in folders} | {"__root__": "Drive'ım"}


def parent_path(file: dict, index: dict[str, str]) -> str:
    parents = file.get("parents") or []
    if not parents:
        return "Benimle paylaşılanlar"
    return index.get(parents[0], "Drive'ım")


def _keep_score(file: dict, path: str) -> tuple:
    """Küçük skor = korunmaya daha uygun."""
    lower = path.lower()
    weak_folder = any(w in lower for w in _WEAK_FOLDER_WORDS)
    in_root = path == "Drive'ım"
    copy_name = bool(_COPY_NAME.search(file.get("name", "").rsplit(".", 1)[0]))
    not_owned = file.get("ownedByMe") is False
    created = file.get("createdTime") or file.get("modifiedTime") or "9999"
    return (not_owned, weak_folder, copy_name, in_root, created, -path.count("/"), file.get("id", ""))


@dataclass
class DuplicateGroup:
    md5: str
    size: int
    keep: dict
    others: list[dict] = field(default_factory=list)
    paths: dict[str, str] = field(default_factory=dict)  # file_id -> klasör yolu

    @property
    def reclaimable(self) -> int:
        return self.size * len([o for o in self.others if o.get("ownedByMe", True)])

    @property
    def count(self) -> int:
        return 1 + len(self.others)


def find_duplicates(files: list[dict], path_index: dict[str, str] | None = None,
                    min_size: int = 1) -> list[DuplicateGroup]:
    """md5Checksum + boyut aynı olan (çöpte olmayan) dosyaları gruplar.

    Google Dokümanlar/E-Tablolar gibi yerel türlerde md5 olmadığı için dahil edilmez.
    Gruplar kazanılacak alana göre büyükten küçüğe sıralanır.
    """
    path_index = path_index if path_index is not None else build_path_index(files)
    buckets: dict[tuple[str, int], list[dict]] = {}
    for f in files:
        md5 = f.get("md5Checksum")
        if not md5 or f.get("trashed") or f.get("mimeType") == FOLDER_MIME:
            continue
        size = int(f.get("size") or 0)
        if size < min_size:
            continue
        buckets.setdefault((md5, size), []).append(f)

    groups: list[DuplicateGroup] = []
    for (md5, size), members in buckets.items():
        if len(members) < 2:
            continue
        paths = {m["id"]: parent_path(m, path_index) for m in members}
        ordered = sorted(members, key=lambda m: _keep_score(m, paths[m["id"]]))
        groups.append(DuplicateGroup(md5=md5, size=size, keep=ordered[0], others=ordered[1:], paths=paths))
    groups.sort(key=lambda g: (-g.reclaimable, g.md5))
    return groups


def total_reclaimable(groups: list[DuplicateGroup]) -> int:
    return sum(g.reclaimable for g in groups)
