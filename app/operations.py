"""Önizleme -> onay -> uygulama akışı.

Her düzenleyici işlem iki aşamalıdır:
1. ``preview_*`` fonksiyonları HİÇBİR API YAZMA ÇAĞRISI YAPMADAN önizleme satırları üretir.
2. Kullanıcı önizlemeyi onaylarsa ``apply_*`` çalışır; her adım günlüğe yazılır.
Kalıcı silme yoktur: "sil" her zaman çöp kutusuna taşımadır.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .categorize import MovePlan
from .duplicates import DuplicateGroup
from .journal import Journal

Progress = Callable[[int, int, str], None]
Cancel = Callable[[], bool]


@dataclass
class PreviewRow:
    action: str      # "Çöpe taşı", "Taşı", "Klasör oluştur", "Kopyala"
    name: str
    detail: str      # nereden -> nereye / neden
    size: int = 0
    file_id: str = ""


@dataclass
class ApplyResult:
    batch_id: int
    done: int
    failed: list[str]
    cancelled: bool = False


# ---- önizlemeler --------------------------------------------------------------

def preview_trash_duplicates(groups: list[DuplicateGroup], selected_ids: set[str] | None = None) -> list[PreviewRow]:
    rows = []
    for g in groups:
        for f in g.others:
            if selected_ids is not None and f["id"] not in selected_ids:
                continue
            if f.get("ownedByMe") is False:
                continue  # başkasına ait dosya çöpe atılamaz
            rows.append(PreviewRow("Çöpe taşı", f.get("name", ""),
                                   f"{g.paths.get(f['id'], '')}  (korunan: {g.paths.get(g.keep['id'], '')}/"
                                   f"{g.keep.get('name', '')})", g.size, f["id"]))
    return rows


def preview_trash_files(files: list[dict], reason: str = "") -> list[PreviewRow]:
    return [PreviewRow("Çöpe taşı", f.get("name", ""), reason, int(f.get("size") or 0), f["id"]) for f in files]


def preview_category_plan(plan: MovePlan, parent_label: str) -> list[PreviewRow]:
    rows = [PreviewRow("Klasör oluştur", name, f"{parent_label}/{name}") for name in plan.folders_to_create]
    rows += [PreviewRow("Taşı", it.name, f"{parent_label}  ->  {parent_label}/{it.target_folder_name}",
                        it.size, it.file_id) for it in plan.items]
    return rows


# ---- uygulamalar ------------------------------------------------------------

def apply_trash(client, journal: Journal, account: str, rows: list[PreviewRow], title: str,
                progress: Progress | None = None, cancel: Cancel | None = None) -> ApplyResult:
    batch = journal.start_batch(account, title)
    done, failed = 0, []
    for i, r in enumerate(rows, 1):
        if cancel and cancel():
            journal.finish_batch(batch, "applied" if done else "failed")
            return ApplyResult(batch, done, failed, cancelled=True)
        try:
            client.trash(r.file_id)
            journal.record(batch, account, "trash", r.file_id, r.name, size=r.size)
            done += 1
        except Exception as exc:  # noqa: BLE001
            failed.append(f"{r.name}: {exc}")
        if progress:
            progress(i, len(rows), r.name)
    journal.finish_batch(batch, "applied" if done else "failed")
    return ApplyResult(batch, done, failed)


def apply_category_plan(client, journal: Journal, account: str, plan: MovePlan, title: str,
                        progress: Progress | None = None, cancel: Cancel | None = None) -> ApplyResult:
    batch = journal.start_batch(account, title)
    done, failed = 0, []
    folder_ids: dict[str, str] = {it.target_folder_name: it.target_folder_id
                                  for it in plan.items if it.target_folder_id}
    total = len(plan.folders_to_create) + len(plan.items)
    step = 0
    for name in plan.folders_to_create:
        step += 1
        try:
            fid, created = client.ensure_folder(name, plan.parent_id)
            folder_ids[name] = fid
            if created:
                journal.record(batch, account, "create_folder", fid, name, parent=plan.parent_id)
        except Exception as exc:  # noqa: BLE001
            failed.append(f"Klasör '{name}': {exc}")
        if progress:
            progress(step, total, name)
    for it in plan.items:
        step += 1
        if cancel and cancel():
            journal.finish_batch(batch, "applied")
            return ApplyResult(batch, done, failed, cancelled=True)
        target = folder_ids.get(it.target_folder_name)
        if not target:
            failed.append(f"{it.name}: hedef klasör oluşturulamadı")
            continue
        try:
            client.move(it.file_id, add_parents=[target], remove_parents=[it.from_parent])
            journal.record(batch, account, "move", it.file_id, it.name, **{"from": [it.from_parent], "to": [target]})
            done += 1
        except Exception as exc:  # noqa: BLE001
            failed.append(f"{it.name}: {exc}")
        if progress:
            progress(step, total, it.name)
    journal.finish_batch(batch, "applied" if done or not failed else "failed")
    return ApplyResult(batch, done, failed)
