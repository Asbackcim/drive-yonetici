"""Önizleme -> uygulama -> günlük -> geri alma akışı (sahte Drive ile)."""
from app.categorize import build_category_plan
from app.journal import Journal
from app.operations import (apply_category_plan, apply_trash, preview_category_plan, preview_trash_files)
from app.settings import DEFAULT_CATEGORIES
from fakes import FakeDrive


def setup():
    d = FakeDrive("a@example.com")
    ids = {
        "foto": d.add("foto.jpg", mime="image/jpeg", size=10),
        "rapor": d.add("rapor.pdf", mime="application/pdf", size=20),
        "sarki": d.add("sarki.mp3", mime="audio/mpeg", size=30),
    }
    existing = d.add_folder("Resimler")
    return d, ids, existing


def test_preview_makes_no_changes(tmp_path):
    d, ids, _ = setup()
    plan = build_category_plan(d.list_children("root"), "root", DEFAULT_CATEGORIES)
    rows = preview_category_plan(plan, "Drive'ım")
    assert d.calls == []                                  # önizleme hiçbir şey değiştirmez
    assert [r.action for r in rows].count("Klasör oluştur") == 2   # Belgeler, Müzik (Resimler zaten var)
    assert [r.action for r in rows].count("Taşı") == 3


def test_category_apply_and_undo(tmp_path):
    d, ids, existing = setup()
    j = Journal(tmp_path / "j.db")
    plan = build_category_plan(d.list_children("root"), "root", DEFAULT_CATEGORIES)
    res = apply_category_plan(d, j, d.email, plan, "Türe göre ayır")
    assert res.done == 3 and res.failed == []
    assert d.files[ids["foto"]]["parents"] == [existing]
    new_folders = [c[1] for c in d.calls if c[0] == "create_folder"]
    assert sorted(new_folders) == ["Belgeler", "Müzik"]

    batch, done, errors = j.undo_last(lambda acc: d)
    assert batch["id"] == res.batch_id and errors == []
    assert done == 5                                      # 3 taşıma + 2 klasör
    for fid in ids.values():
        assert d.files[fid]["parents"] == ["root"]
    # oluşturulan boş klasörler çöpe gitti (kalıcı silme yok), önceden var olan dokunulmadı
    trashed = {d.files[c]["name"] for c in d.files if d.files[c]["trashed"]}
    assert trashed == {"Belgeler", "Müzik"}
    assert not d.files[existing]["trashed"]
    assert j.last_undoable_batch() is None


def test_trash_apply_and_undo(tmp_path):
    d, ids, _ = setup()
    j = Journal(tmp_path / "j.db")
    rows = preview_trash_files([d.get(ids["rapor"]), d.get(ids["sarki"])], "kopya")
    res = apply_trash(d, j, d.email, rows, "Kopyaları çöpe taşı")
    assert res.done == 2
    assert d.files[ids["rapor"]]["trashed"] and d.files[ids["sarki"]]["trashed"]
    assert not any(c[0] == "delete" for c in d.calls)

    j.undo_last(lambda acc: d)
    assert not d.files[ids["rapor"]]["trashed"] and not d.files[ids["sarki"]]["trashed"]
    assert j.batches()[0]["status"] == "undone"


def test_undo_only_last_batch_and_partial_errors(tmp_path):
    d, ids, _ = setup()
    j = Journal(tmp_path / "j.db")
    apply_trash(d, j, d.email, preview_trash_files([d.get(ids["foto"])]), "1")
    apply_trash(d, j, d.email, preview_trash_files([d.get(ids["rapor"])]), "2")

    j.undo_last(lambda acc: d)
    assert d.files[ids["foto"]]["trashed"]                # ilk parti yerinde
    assert not d.files[ids["rapor"]]["trashed"]

    class Broken(FakeDrive):
        def untrash(self, fid):
            raise RuntimeError("ağ hatası")

    b = Broken()
    b.files = d.files
    _, done, errors = j.undo_last(lambda acc: b)
    assert done == 0 and len(errors) == 1
    assert j.batches()[1]["status"] == "undo_partial"     # tekrar denenebilir
    assert j.last_undoable_batch()["title"] == "1"
