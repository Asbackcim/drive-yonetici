from datetime import datetime, timezone

from app.duplicates import build_path_index, find_duplicates, total_reclaimable
from app.largeold import filter_files
from app.operations import preview_trash_duplicates

FOLDER = "application/vnd.google-apps.folder"


def f(id, name, parent, md5=None, size=100, created="2020-01-01T00:00:00Z", **kw):
    return {"id": id, "name": name, "parents": [parent], "md5Checksum": md5, "size": str(size),
            "mimeType": "application/octet-stream", "createdTime": created, **kw}


def sample():
    return [
        {"id": "F1", "name": "Fotoğraflar", "mimeType": FOLDER, "parents": ["ROOT"]},
        {"id": "F2", "name": "Downloads", "mimeType": FOLDER, "parents": ["ROOT"]},
        {"id": "F3", "name": "2019", "mimeType": FOLDER, "parents": ["F1"]},
        f("a1", "tatil.jpg", "F3", "m1", 5000, "2019-06-01T00:00:00Z"),
        f("a2", "tatil (1).jpg", "F2", "m1", 5000, "2018-01-01T00:00:00Z"),   # daha eski ama zayıf klasör+kopya adı
        f("a3", "tatil.jpg", "ROOT", "m1", 5000, "2021-01-01T00:00:00Z"),
        f("b1", "rapor.pdf", "F1", "m2", 300),
        f("b2", "rapor.pdf", "F3", "m2", 300, "2019-01-01T00:00:00Z"),
        f("c1", "tek.pdf", "F1", "m3", 10),
        f("d1", "Doküman", "F1", None),                                          # md5 yok (Google yerel)
        f("d2", "Doküman", "F2", None),
        f("e1", "x.bin", "F1", "m4", 10, trashed=True),
        f("e2", "x.bin", "F2", "m4", 10),
    ]


def test_groups_and_keep_suggestion():
    files = sample()
    groups = find_duplicates(files)
    assert len(groups) == 2
    g1 = groups[0]                                    # en çok alan kazandıran önce
    assert g1.md5 == "m1" and g1.count == 3
    assert g1.keep["id"] == "a1"                      # iyi klasörde, kopya adı yok
    assert {o["id"] for o in g1.others} == {"a2", "a3"}
    assert g1.reclaimable == 10000
    g2 = groups[1]
    assert g2.keep["id"] == "b2"                      # aynı koşullarda en eski
    assert total_reclaimable(groups) == 10300


def test_paths():
    idx = build_path_index(sample())
    assert idx["F3"] == "Drive'ım/Fotoğraflar/2019"


def test_not_owned_not_counted_or_trashed():
    files = [f("x1", "a", "R", "m", 100), f("x2", "a", "R", "m", 100, ownedByMe=False)]
    g = find_duplicates(files)[0]
    assert g.keep["id"] == "x1"
    assert g.reclaimable == 0
    assert preview_trash_duplicates([g]) == []


def test_preview_respects_selection():
    groups = find_duplicates(sample())
    rows = preview_trash_duplicates(groups, selected_ids={"a3"})
    assert [r.file_id for r in rows] == ["a3"]
    assert all(r.action == "Çöpe taşı" for r in rows)


def test_large_old_filter():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    files = [
        {"id": "1", "name": "film", "mimeType": "video/mp4", "size": str(500 * 1024**2),
         "modifiedTime": "2020-01-01T00:00:00Z"},
        {"id": "2", "name": "yeni", "mimeType": "video/mp4", "size": str(900 * 1024**2),
         "modifiedTime": "2025-12-01T00:00:00Z"},
        {"id": "3", "name": "kucuk", "mimeType": "a/b", "size": "10", "modifiedTime": "2010-01-01T00:00:00Z"},
        {"id": "4", "name": "acilmis", "mimeType": "a/b", "size": str(200 * 1024**2),
         "modifiedTime": "2019-01-01T00:00:00Z", "viewedByMeTime": "2025-11-01T00:00:00Z"},
    ]
    assert [x["id"] for x in filter_files(files, min_size_mb=100, now=now)] == ["2", "1", "4"]
    assert [x["id"] for x in filter_files(files, min_size_mb=100, older_than_days=365, now=now)] == ["1"]
    assert [x["id"] for x in filter_files(files, older_than_days=365, sort_by="age", now=now)] == ["3", "1"]
