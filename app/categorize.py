"""Dosyaları türe göre kategorilere ayırma ve taşıma önerisi üretme."""
from __future__ import annotations

from dataclasses import dataclass, field

from .settings import OTHER_CATEGORY
from .validation import ValidationError, validate_category_name, validate_extension

FOLDER_MIME = "application/vnd.google-apps.folder"

# Google'ın yerel dosya türleri (uzantısı yoktur)
GOOGLE_NATIVE = {
    "application/vnd.google-apps.document": "Belgeler",
    "application/vnd.google-apps.spreadsheet": "Belgeler",
    "application/vnd.google-apps.presentation": "Belgeler",
    "application/vnd.google-apps.form": "Belgeler",
    "application/vnd.google-apps.drawing": "Resimler",
}
MIME_PREFIX = {"image/": "Resimler", "video/": "Videolar", "audio/": "Müzik"}


def normalize_rules(rules: dict[str, list[str]]) -> dict[str, list[str]]:
    """Kullanıcı kurallarını doğrular. Aynı uzantı iki kategoride olamaz."""
    if not isinstance(rules, dict) or not rules:
        raise ValidationError("En az bir kategori tanımlanmalı.")
    seen: dict[str, str] = {}
    out: dict[str, list[str]] = {}
    for cat, exts in rules.items():
        name = validate_category_name(cat)
        if name == OTHER_CATEGORY:
            raise ValidationError(f"'{OTHER_CATEGORY}' otomatik kategoridir, kural olarak eklenemez.")
        if not isinstance(exts, (list, tuple)):
            raise ValidationError(f"'{name}' için uzantı listesi bekleniyordu.")
        clean = []
        for e in exts:
            ext = validate_extension(str(e))
            if ext in seen and seen[ext] != name:
                raise ValidationError(f"'.{ext}' hem '{seen[ext]}' hem '{name}' kategorisinde.")
            seen[ext] = name
            if ext not in clean:
                clean.append(ext)
        out[name] = clean
    return out


def extension_of(name: str) -> str:
    if "." not in name or name.endswith("."):
        return ""
    return name.rsplit(".", 1)[1].lower()


def classify(file: dict, rules: dict[str, list[str]]) -> str:
    mime = file.get("mimeType", "")
    if mime in GOOGLE_NATIVE:
        return GOOGLE_NATIVE[mime] if GOOGLE_NATIVE[mime] in rules else OTHER_CATEGORY
    ext = extension_of(file.get("name", ""))
    if ext:
        for cat, exts in rules.items():
            if ext in exts:
                return cat
    for prefix, cat in MIME_PREFIX.items():
        if mime.startswith(prefix) and cat in rules:
            return cat
    return OTHER_CATEGORY


@dataclass
class MovePlanItem:
    file_id: str
    name: str
    category: str
    from_parent: str
    target_folder_name: str
    target_folder_id: str | None  # None => önce oluşturulacak
    size: int = 0


@dataclass
class MovePlan:
    parent_id: str
    items: list[MovePlanItem] = field(default_factory=list)
    folders_to_create: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for it in self.items:
            out[it.category] = out.get(it.category, 0) + 1
        return out


def build_category_plan(children: list[dict], parent_id: str, rules: dict[str, list[str]],
                        min_files_per_category: int = 1, include_other: bool = True) -> MovePlan:
    """Bir klasörün DOĞRUDAN çocuklarından (klasör olmayan) taşıma planı üretir.

    Klasördeki mevcut aynı adlı kategori klasörleri yeniden kullanılır; yoksa
    oluşturulacaklar listesine eklenir. Hiçbir şey burada uygulanmaz.
    """
    rules = normalize_rules(rules)
    existing_folders = {c["name"]: c["id"] for c in children
                        if c.get("mimeType") == FOLDER_MIME and not c.get("trashed")}
    groups: dict[str, list[dict]] = {}
    for f in children:
        if f.get("mimeType") == FOLDER_MIME or f.get("trashed"):
            continue
        if f.get("ownedByMe") is False and not f.get("capabilities", {}).get("canMoveItemWithinDrive", True):
            continue
        cat = classify(f, rules)
        if cat == OTHER_CATEGORY and not include_other:
            continue
        groups.setdefault(cat, []).append(f)

    plan = MovePlan(parent_id=parent_id)
    for cat in sorted(groups):
        files = groups[cat]
        if len(files) < min_files_per_category:
            continue
        folder_id = existing_folders.get(cat)
        if folder_id is None and cat not in plan.folders_to_create:
            plan.folders_to_create.append(cat)
        for f in sorted(files, key=lambda x: x.get("name", "").lower()):
            plan.items.append(MovePlanItem(
                file_id=f["id"], name=f.get("name", ""), category=cat, from_parent=parent_id,
                target_folder_name=cat, target_folder_id=folder_id, size=int(f.get("size") or 0)))
    return plan


def category_distribution(files: list[dict], rules: dict[str, list[str]]) -> dict[str, int]:
    """Kategori -> toplam bayt (klasörler hariç)."""
    out: dict[str, int] = {}
    for f in files:
        if f.get("mimeType") == FOLDER_MIME:
            continue
        cat = classify(f, rules)
        out[cat] = out.get(cat, 0) + int(f.get("size") or f.get("quotaBytesUsed") or 0)
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))
