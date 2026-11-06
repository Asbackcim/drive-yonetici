"""Artımlı yedek karar mantığı, tarama, durum DB'si ve yükleme motoru (sahte Drive ile)."""
import hashlib
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app import backup
from app.backup import (CHANGED, NEW, SKIP, TOUCH, BackupEngine, BackupState, FileRecord, LocalFile,
                        ProgressTracker, QuotaError, build_plan, decide, scan, source_labels)
from app.excludes import ExcludeMatcher
from app.settings import DEFAULT_EXCLUDES


def lf(size=10, mtime=1000, path="x"):
    return LocalFile(path, "Kaynak/x", size, mtime)


def boom(_):
    raise AssertionError("md5 hesaplanmamalıydı")


# ---- decide ----------------------------------------------------------------------
def test_decide_new():
    assert decide(lf(), None, boom) == (NEW, None)
    assert decide(lf(), FileRecord(10, 1000, "m", None), boom) == (NEW, None)   # Drive kimliği yoksa


def test_decide_size_changed_without_hashing():
    assert decide(lf(size=11), FileRecord(10, 1000, "m", "D"), boom) == (CHANGED, None)


def test_decide_unchanged_without_hashing():
    assert decide(lf(), FileRecord(10, 1000, "m", "D"), boom) == (SKIP, None)


def test_decide_mtime_changed_same_content():
    assert decide(lf(mtime=2000), FileRecord(10, 1000, "abc", "D"), lambda p: "abc") == (TOUCH, "abc")


def test_decide_mtime_changed_different_content():
    assert decide(lf(mtime=2000), FileRecord(10, 1000, "abc", "D"), lambda p: "zzz") == (CHANGED, "zzz")


# ---- tarama --------------------------------------------------------------------
@pytest.fixture
def tree(tmp_path) -> Path:
    """Kullanıcı klasörlerine dokunmamak için tamamen sahte bir test klasörü."""
    root = tmp_path / "SahteBelgeler"
    (root / "Raporlar").mkdir(parents=True)
    (root / "proje" / "node_modules" / "lib").mkdir(parents=True)
    (root / "proje" / ".git").mkdir(parents=True)
    (root / "Raporlar" / "a.txt").write_bytes(b"merhaba")
    (root / "Raporlar" / "b.docx").write_bytes(b"x" * 100)
    (root / "Raporlar" / "~$b.docx").write_bytes(b"kilit")
    (root / "gecici.tmp").write_bytes(b"t")
    (root / "proje" / "main.py").write_bytes(b"print(1)")
    (root / "proje" / "node_modules" / "lib" / "i.js").write_bytes(b"js")
    (root / "proje" / ".git" / "HEAD").write_bytes(b"ref")
    return root


def test_scan_respects_excludes(tree):
    found = sorted(f.rel_path for f in scan([tree], ExcludeMatcher(DEFAULT_EXCLUDES)))
    assert found == ["SahteBelgeler/Raporlar/a.txt", "SahteBelgeler/Raporlar/b.docx", "SahteBelgeler/proje/main.py"]


def test_source_labels_unique(tmp_path):
    a, b = tmp_path / "x" / "Belgeler", tmp_path / "y" / "Belgeler"
    labels = source_labels([a, b])
    assert labels[a] == "Belgeler" and labels[b] == "Belgeler (2)"


# ---- plan + durum -------------------------------------------------------------
def test_incremental_plan_cycle(tree, tmp_path):
    state = BackupState(tmp_path / "s.db")
    sid = state.create_set("a@example.com", "Bilgisayar Yedeği - 01.01.2026")
    m = ExcludeMatcher(DEFAULT_EXCLUDES)

    plan = build_plan(state, sid, scan([tree], m))
    assert {i.decision for i in plan.items} == {NEW} and len(plan.items) == 3
    for it in plan.items:  # yüklenmiş gibi kaydet
        state.put_record(sid, it.file, backup.md5_of(it.file.abs_path), "D-" + it.file.rel_path)

    plan2 = build_plan(state, sid, scan([tree], m))
    assert plan2.items == [] and plan2.skipped == 3

    # içerik değişti (boyut farklı)
    (tree / "Raporlar" / "a.txt").write_bytes(b"merhaba dunya")
    # yalnızca tarih değişti
    p = tree / "Raporlar" / "b.docx"
    st = p.stat()
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    # yeni dosya
    (tree / "Raporlar" / "c.pdf").write_bytes(b"pdf")

    plan3 = build_plan(state, sid, scan([tree], m))
    decisions = {i.file.rel_path.rsplit("/", 1)[-1]: i.decision for i in plan3.items}
    assert decisions == {"a.txt": CHANGED, "c.pdf": NEW}
    assert [f.rel_path.rsplit("/", 1)[-1] for f, _ in plan3.touched] == ["b.docx"]
    changed = [i for i in plan3.items if i.decision == CHANGED][0]
    assert changed.drive_id == "D-SahteBelgeler/Raporlar/a.txt"   # aynı Drive dosyası güncellenecek
    assert plan3.upload_bytes == len(b"merhaba dunya") + 3


# ---- motor (sahte Drive) ------------------------------------------------------
def make_client(quota=(10**12, 0)):
    client = MagicMock()
    client.quota.return_value = quota
    client.root_id.return_value = "ROOT"
    counter = iter(range(1, 10_000))
    client.create_folder.side_effect = lambda name, parent: f"folder{next(counter)}"
    client.ensure_folder.side_effect = lambda name, parent: (f"dir:{parent}/{name}", True)
    files_api = client.service.return_value.files.return_value

    def create(body, media_body, fields):
        req = MagicMock()
        data = Path(media_body._filename).read_bytes()
        req.execute.return_value = {"id": "drv-" + body["name"], "md5Checksum": hashlib.md5(data).hexdigest()}
        return req

    files_api.create.side_effect = create
    files_api.update.side_effect = lambda fileId, body, media_body, fields: MagicMock(
        execute=MagicMock(return_value={"id": fileId, "md5Checksum": "yeni"}))
    return client, files_api


def test_engine_uploads_then_skips(tree, tmp_path):
    state = BackupState(tmp_path / "s.db")
    sid = state.create_set("a@example.com", "Bilgisayar Yedeği - 01.01.2026")
    client, files_api = make_client()
    m = ExcludeMatcher(DEFAULT_EXCLUDES)

    engine = BackupEngine(client, state, sid, workers=2)
    plan = build_plan(state, sid, scan([tree], m))
    snaps = []
    tracker = engine.run(plan, on_progress=snaps.append)
    assert tracker.done_files == 3 and tracker.failed == []
    assert tracker.done_bytes == tracker.total_bytes == plan.upload_bytes
    assert files_api.create.call_count == 3
    client.create_folder.assert_called_once_with("Bilgisayar Yedeği - 01.01.2026", "ROOT")
    assert state.count_files(sid) == 3
    assert snaps[-1]["done_files"] == 3

    # ikinci çalıştırma: hiçbir şey yüklenmez
    plan2 = build_plan(state, sid, scan([tree], m))
    assert plan2.upload_items == []
    engine.run(plan2)
    assert files_api.create.call_count == 3

    # değişen dosya update ile (yeni sürüm) gönderilir, create ile değil
    (tree / "proje" / "main.py").write_bytes(b"print(2)  # degisti")
    plan3 = build_plan(state, sid, scan([tree], m))
    engine.run(plan3)
    assert files_api.create.call_count == 3
    assert files_api.update.call_count == 1
    assert files_api.update.call_args.kwargs["fileId"] == "drv-main.py"


def test_quota_check():
    client, _ = make_client(quota=(1000, 900))
    engine = BackupEngine(client, MagicMock(), 1)
    with pytest.raises(QuotaError) as e:
        engine.check_quota(200)
    assert e.value.free == 100
    engine.check_quota(100)
    client.quota.return_value = (None, 5)   # sınırsız
    engine.check_quota(10**15)


def test_resumable_upload_resumes_saved_session(tmp_path):
    big = tmp_path / "SahteVideo"
    big.mkdir()
    fpath = big / "film.mp4"
    fpath.write_bytes(os.urandom(backup.SIMPLE_UPLOAD_LIMIT + 1024))
    st = fpath.stat()
    local = LocalFile(str(fpath), "SahteVideo/film.mp4", st.st_size, st.st_mtime_ns)

    state = BackupState(tmp_path / "s.db")
    sid = state.create_set("a@example.com", "Yedek")
    state.set_root(sid, "ROOT-FOLDER")
    state.put_session(sid, local, "https://upload.example/session-123")   # önceki yarım yükleme

    client, files_api = make_client()
    seen = {}

    def create(body, media_body, fields):
        req = MagicMock()
        req.resumable_uri = None
        req.resumable_progress = 0

        def next_chunk():
            seen["uri"] = req.resumable_uri
            seen["error_state"] = req._in_error_state
            req.resumable_progress = local.size
            return None, {"id": "drv-film", "md5Checksum": "abc"}

        req.next_chunk.side_effect = next_chunk
        return req

    files_api.create.side_effect = create
    engine = BackupEngine(client, state, sid, workers=1)
    plan = backup.BackupPlan(items=[backup.PlanItem(local, NEW)])
    tracker = engine.run(plan)

    assert seen == {"uri": "https://upload.example/session-123", "error_state": True}
    assert tracker.failed == [] and tracker.done_bytes == local.size
    assert state.pending_sessions(sid) == 0                       # tamamlanınca oturum silinir
    assert state.get_record(sid, local.rel_path).drive_id == "drv-film"


def test_progress_tracker_speed_eta():
    t = [0.0]
    tr = ProgressTracker(1000, 2, clock=lambda: t[0])
    tr.add_bytes(0)
    t[0] = 10.0
    tr.add_bytes(500)
    assert tr.speed() == pytest.approx(50.0)
    assert tr.eta() == pytest.approx(10.0)
