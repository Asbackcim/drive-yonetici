"""Bilgisayar yedeği: artımlı, devam ettirilebilir, paralel yükleme.

Tasarım (100+ GB için):
- Yerel tarama bir üreteçtir (os.scandir) ve dışlanan klasörlere hiç inmez.
- Durum SQLite'ta tutulur: her dosya için boyut, mtime (ns), Drive'daki md5 ve Drive kimliği.
- Karar mantığı (``decide``):
    kayıt yok                         -> YENİ (yükle)
    boyut farklı                      -> DEĞİŞTİ (yeni sürüm olarak yükle)
    boyut + mtime aynı                -> ATLA (dosya okunmaz bile)
    boyut aynı, mtime farklı:
        yerel md5 == kayıtlı md5      -> DOKUN (yalnızca mtime güncellenir, yükleme yok)
        aksi halde                    -> DEĞİŞTİ
- Büyük dosyalar 8 MB'lik parçalarla "resumable upload" ile gönderilir. Oturum adresi
  (resumable URI) veritabanına yazılır; uygulama kapanıp açılsa bile yükleme kaldığı
  bayttan devam eder (Google oturumları ~1 hafta geçerlidir).
- Aynı anda en fazla N (varsayılan 3) dosya yüklenir.
- Drive'daki hiçbir dosya silinmez; değişen dosyalar aynı Drive dosyasının yeni
  sürümü olarak yüklenir.
"""
from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator

from . import paths
from .excludes import ExcludeMatcher
from .retry import is_retryable, with_backoff
from .validation import sanitize_drive_name

log = logging.getLogger(__name__)

SIMPLE_UPLOAD_LIMIT = 5 * 1024 * 1024
NEW, CHANGED, SKIP, TOUCH = "new", "changed", "skip", "touch"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account TEXT NOT NULL,
    name TEXT NOT NULL,
    drive_root_id TEXT,
    created_at TEXT NOT NULL,
    last_run TEXT
);
CREATE TABLE IF NOT EXISTS files (
    set_id INTEGER NOT NULL,
    local_path TEXT NOT NULL,
    size INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL,
    md5 TEXT,
    drive_id TEXT,
    uploaded_at TEXT,
    PRIMARY KEY (set_id, local_path)
);
CREATE TABLE IF NOT EXISTS folders (
    set_id INTEGER NOT NULL,
    rel_dir TEXT NOT NULL,
    drive_id TEXT NOT NULL,
    PRIMARY KEY (set_id, rel_dir)
);
CREATE TABLE IF NOT EXISTS sessions (
    set_id INTEGER NOT NULL,
    local_path TEXT NOT NULL,
    resumable_uri TEXT NOT NULL,
    size INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    PRIMARY KEY (set_id, local_path)
);
"""


# ---------------------------------------------------------------------------
# Veri tipleri
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class LocalFile:
    abs_path: str
    rel_path: str      # "Belgeler/2024/fatura.pdf" ('/' ayraçlı, yedek kökü göreli)
    size: int
    mtime_ns: int


@dataclass
class FileRecord:
    size: int
    mtime_ns: int
    md5: str | None
    drive_id: str | None


@dataclass
class PlanItem:
    file: LocalFile
    decision: str
    drive_id: str | None = None   # CHANGED ise güncellenecek Drive dosyası


@dataclass
class BackupPlan:
    items: list[PlanItem] = field(default_factory=list)
    touched: list[tuple[LocalFile, str]] = field(default_factory=list)
    skipped: int = 0
    scan_errors: list[str] = field(default_factory=list)

    @property
    def upload_items(self) -> list[PlanItem]:
        return [i for i in self.items if i.decision in (NEW, CHANGED)]

    @property
    def upload_bytes(self) -> int:
        return sum(i.file.size for i in self.upload_items)


class QuotaError(Exception):
    def __init__(self, needed: int, free: int):
        super().__init__("Drive'da yeterli alan yok")
        self.needed, self.free = needed, free


# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------
def md5_of(path: str, chunk: int = 4 * 1024 * 1024, cancel: Callable[[], bool] | None = None) -> str:
    h = hashlib.md5()
    with open(path, "rb") as fh:
        while True:
            if cancel and cancel():
                raise InterruptedError
            b = fh.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def decide(local: LocalFile, record: FileRecord | None, md5_func: Callable[[str], str]) -> tuple[str, str | None]:
    """Artımlı yedek karar mantığı. (karar, hesaplanan_md5|None) döndürür."""
    if record is None or not record.drive_id:
        return NEW, None
    if record.size != local.size:
        return CHANGED, None
    if record.mtime_ns == local.mtime_ns:
        return SKIP, None
    digest = md5_func(local.abs_path)
    if record.md5 and digest == record.md5:
        return TOUCH, digest
    return CHANGED, digest


def source_labels(sources: list[Path]) -> dict[Path, str]:
    """Aynı adlı iki kaynak klasör için benzersiz Drive klasör adları üretir."""
    labels: dict[Path, str] = {}
    used: set[str] = set()
    for s in sources:
        base = sanitize_drive_name(s.name or str(s).replace(":", ""))
        name, n = base, 2
        while name.lower() in used:
            name = f"{base} ({n})"
            n += 1
        used.add(name.lower())
        labels[s] = name
    return labels


def scan(sources: list[Path], matcher: ExcludeMatcher, errors: list[str] | None = None,
         cancel: Callable[[], bool] | None = None) -> Iterator[LocalFile]:
    """Kaynak klasörleri gezer; dışlanan klasörlere inmez. Sembolik bağları izlemez."""
    labels = source_labels(sources)
    for src in sources:
        stack: list[tuple[str, str]] = [(str(src), labels[src])]
        while stack:
            if cancel and cancel():
                return
            abs_dir, rel_dir = stack.pop()
            try:
                with os.scandir(abs_dir) as it:
                    entries = sorted(it, key=lambda e: e.name.lower())
            except OSError as exc:
                if errors is not None:
                    errors.append(f"{abs_dir}: {exc.strerror or exc}")
                continue
            subdirs = []
            for e in entries:
                if matcher.is_name_excluded(e.name):
                    continue
                rel = f"{rel_dir}/{e.name}"
                try:
                    if e.is_symlink():
                        continue
                    if e.is_dir(follow_symlinks=False):
                        if not matcher.is_excluded(rel):
                            subdirs.append((e.path, rel))
                        continue
                    if matcher.is_excluded(rel):
                        continue
                    st = e.stat(follow_symlinks=False)
                    yield LocalFile(e.path, rel, st.st_size, st.st_mtime_ns)
                except OSError as exc:
                    if errors is not None:
                        errors.append(f"{e.path}: {exc.strerror or exc}")
            stack.extend(reversed(subdirs))


# ---------------------------------------------------------------------------
# Durum veritabanı
# ---------------------------------------------------------------------------
class BackupState:
    def __init__(self, db_path: str | Path | None = None):
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(db_path or paths.backup_db_path()), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def _exec(self, sql: str, args: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn.execute(sql, args)
            self._conn.commit()
            return cur

    def _query(self, sql: str, args: tuple = ()) -> list[tuple]:
        with self._lock:
            return self._conn.execute(sql, args).fetchall()

    # setler
    def create_set(self, account: str, name: str) -> int:
        return int(self._exec("INSERT INTO sets(account,name,created_at) VALUES (?,?,?)",
                              (account, name, datetime.now().isoformat(timespec="seconds"))).lastrowid)

    def sets_for(self, account: str) -> list[dict]:
        rows = self._query("SELECT id,name,drive_root_id,created_at,last_run FROM sets WHERE account=? ORDER BY id DESC",
                           (account,))
        return [dict(zip(("id", "name", "drive_root_id", "created_at", "last_run"), r)) for r in rows]

    def set_root(self, set_id: int, drive_id: str) -> None:
        self._exec("UPDATE sets SET drive_root_id=? WHERE id=?", (drive_id, set_id))

    def get_set(self, set_id: int) -> dict | None:
        rows = self._query("SELECT id,account,name,drive_root_id FROM sets WHERE id=?", (set_id,))
        return dict(zip(("id", "account", "name", "drive_root_id"), rows[0])) if rows else None

    def mark_run(self, set_id: int) -> None:
        self._exec("UPDATE sets SET last_run=? WHERE id=?", (datetime.now().isoformat(timespec="seconds"), set_id))

    # dosyalar
    def get_record(self, set_id: int, rel_path: str) -> FileRecord | None:
        rows = self._query("SELECT size,mtime_ns,md5,drive_id FROM files WHERE set_id=? AND local_path=?",
                           (set_id, rel_path))
        return FileRecord(*rows[0]) if rows else None

    def put_record(self, set_id: int, f: LocalFile, md5: str | None, drive_id: str | None) -> None:
        self._exec("INSERT OR REPLACE INTO files(set_id,local_path,size,mtime_ns,md5,drive_id,uploaded_at) "
                   "VALUES (?,?,?,?,?,?,?)",
                   (set_id, f.rel_path, f.size, f.mtime_ns, md5, drive_id, datetime.now().isoformat(timespec="seconds")))

    def count_files(self, set_id: int) -> int:
        return self._query("SELECT COUNT(*) FROM files WHERE set_id=?", (set_id,))[0][0]

    # klasörler
    def get_folder(self, set_id: int, rel_dir: str) -> str | None:
        rows = self._query("SELECT drive_id FROM folders WHERE set_id=? AND rel_dir=?", (set_id, rel_dir))
        return rows[0][0] if rows else None

    def put_folder(self, set_id: int, rel_dir: str, drive_id: str) -> None:
        self._exec("INSERT OR REPLACE INTO folders(set_id,rel_dir,drive_id) VALUES (?,?,?)", (set_id, rel_dir, drive_id))

    # yarım kalan yükleme oturumları
    def get_session(self, set_id: int, f: LocalFile) -> str | None:
        rows = self._query("SELECT resumable_uri,size,mtime_ns FROM sessions WHERE set_id=? AND local_path=?",
                           (set_id, f.rel_path))
        if rows and rows[0][1] == f.size and rows[0][2] == f.mtime_ns:
            return rows[0][0]
        return None

    def put_session(self, set_id: int, f: LocalFile, uri: str) -> None:
        self._exec("INSERT OR REPLACE INTO sessions VALUES (?,?,?,?,?,?)",
                   (set_id, f.rel_path, uri, f.size, f.mtime_ns, datetime.now().isoformat(timespec="seconds")))

    def drop_session(self, set_id: int, f: LocalFile) -> None:
        self._exec("DELETE FROM sessions WHERE set_id=? AND local_path=?", (set_id, f.rel_path))

    def pending_sessions(self, set_id: int) -> int:
        return self._query("SELECT COUNT(*) FROM sessions WHERE set_id=?", (set_id,))[0][0]


def build_plan(state: BackupState, set_id: int, files: Iterator[LocalFile],
               md5_func: Callable[[str], str] = md5_of, cancel: Callable[[], bool] | None = None,
               on_scan: Callable[[int], None] | None = None) -> BackupPlan:
    plan = BackupPlan()
    n = 0
    for f in files:
        if cancel and cancel():
            break
        n += 1
        if on_scan and n % 1000 == 0:
            on_scan(n)
        rec = state.get_record(set_id, f.rel_path)
        try:
            decision, digest = decide(f, rec, md5_func)
        except OSError as exc:
            plan.scan_errors.append(f"{f.abs_path}: {exc}")
            continue
        if decision == SKIP:
            plan.skipped += 1
        elif decision == TOUCH:
            plan.touched.append((f, digest))
        else:
            plan.items.append(PlanItem(f, decision, rec.drive_id if rec else None))
    if on_scan:
        on_scan(n)
    return plan


# ---------------------------------------------------------------------------
# İlerleme
# ---------------------------------------------------------------------------
class ProgressTracker:
    def __init__(self, total_bytes: int, total_files: int, clock: Callable[[], float] = time.monotonic):
        self.total_bytes, self.total_files = total_bytes, total_files
        self.done_bytes = 0
        self.done_files = 0
        self.failed: list[str] = []
        self.active: dict[str, float] = {}
        self._clock = clock
        self._samples: deque[tuple[float, int]] = deque()
        self._lock = threading.Lock()

    def add_bytes(self, n: int) -> None:
        with self._lock:
            self.done_bytes += n
            now = self._clock()
            self._samples.append((now, self.done_bytes))
            while self._samples and now - self._samples[0][0] > 15:
                self._samples.popleft()

    def file_done(self, ok: bool, msg: str = "") -> None:
        with self._lock:
            self.done_files += 1
            if not ok:
                self.failed.append(msg)

    def speed(self) -> float:
        with self._lock:
            if len(self._samples) < 2:
                return 0.0
            (t0, b0), (t1, b1) = self._samples[0], self._samples[-1]
            return (b1 - b0) / (t1 - t0) if t1 > t0 else 0.0

    def eta(self) -> float | None:
        s = self.speed()
        if s <= 0:
            return None
        return max(0.0, (self.total_bytes - self.done_bytes) / s)

    def snapshot(self) -> dict:
        return {"done_bytes": self.done_bytes, "total_bytes": self.total_bytes, "done_files": self.done_files,
                "total_files": self.total_files, "speed": self.speed(), "eta": self.eta(),
                "failed": len(self.failed), "active": list(self.active)}


# ---------------------------------------------------------------------------
# Yükleme motoru
# ---------------------------------------------------------------------------
def backup_folder_name(when: datetime | None = None) -> str:
    return f"Bilgisayar Yedeği - {(when or datetime.now()).strftime('%d.%m.%Y')}"


class BackupEngine:
    def __init__(self, client, state: BackupState, set_id: int, workers: int = 3, chunk_mb: int = 8):
        self.client = client
        self.state = state
        self.set_id = set_id
        self.workers = max(1, min(6, workers))
        self.chunk = max(1, chunk_mb) * 1024 * 1024
        self._cancel = threading.Event()
        self._folder_lock = threading.Lock()

    def cancel(self) -> None:
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    # -- kota ---------------------------------------------------------------
    def check_quota(self, needed: int) -> tuple[int | None, int]:
        limit, usage = self.client.quota()
        if limit is not None and usage + needed > limit:
            raise QuotaError(needed, max(0, limit - usage))
        return limit, usage

    # -- klasörler -----------------------------------------------------------
    def ensure_root(self) -> str:
        s = self.state.get_set(self.set_id)
        if s and s["drive_root_id"]:
            return s["drive_root_id"]
        fid = self.client.create_folder(s["name"], self.client.root_id())
        self.state.set_root(self.set_id, fid)
        return fid

    def ensure_dir(self, rel_dir: str) -> str:
        if not rel_dir:
            return self.ensure_root()
        with self._folder_lock:
            cached = self.state.get_folder(self.set_id, rel_dir)
            if cached:
                return cached
        parent_rel, _, name = rel_dir.rpartition("/")
        parent_id = self.ensure_dir(parent_rel)
        with self._folder_lock:
            cached = self.state.get_folder(self.set_id, rel_dir)
            if cached:
                return cached
            fid, _ = self.client.ensure_folder(name, parent_id)
            self.state.put_folder(self.set_id, rel_dir, fid)
            return fid

    # -- tek dosya -------------------------------------------------------------
    def _upload_one(self, item: PlanItem, parent_id: str, tracker: ProgressTracker) -> None:
        from googleapiclient.errors import HttpError
        from googleapiclient.http import MediaFileUpload

        f = item.file
        files_api = self.client.service().files()
        mtime_iso = datetime.fromtimestamp(f.mtime_ns / 1e9, tz=timezone.utc).isoformat().replace("+00:00", "Z")
        fields = "id,md5Checksum,size"

        def make_request(resumable: bool):
            media = MediaFileUpload(f.abs_path, mimetype="application/octet-stream",
                                    chunksize=self.chunk if resumable else -1, resumable=resumable)
            if item.decision == CHANGED and item.drive_id:
                return files_api.update(fileId=item.drive_id, body={"modifiedTime": mtime_iso},
                                        media_body=media, fields=fields)
            body = {"name": f.rel_path.rsplit("/", 1)[-1], "parents": [parent_id], "modifiedTime": mtime_iso}
            return files_api.create(body=body, media_body=media, fields=fields)

        if f.size <= SIMPLE_UPLOAD_LIMIT:
            resp = with_backoff(lambda: make_request(False).execute(), cancel=lambda: self.cancelled)
            tracker.add_bytes(f.size)
        else:
            resp = self._resumable(make_request, f, tracker, HttpError)
            if resp is None:
                return  # iptal edildi; oturum devam için saklı
        # Yükleme sırasında dosya değiştiyse kaydetme -> bir sonraki çalıştırmada tekrar gönderilir
        try:
            st = os.stat(f.abs_path)
            unchanged = st.st_size == f.size and st.st_mtime_ns == f.mtime_ns
        except OSError:
            unchanged = False
        if unchanged:
            self.state.put_record(self.set_id, f, resp.get("md5Checksum"), resp["id"])

    def _resumable(self, make_request, f: LocalFile, tracker: ProgressTracker, HttpError):
        request = make_request(True)
        uri = self.state.get_session(self.set_id, f)
        if uri:
            request.resumable_uri = uri
            request._in_error_state = True  # sunucuya kaç bayt aldığını sorar, oradan devam eder
        reported = 0
        attempt = 0
        resp = None
        while resp is None:
            if self.cancelled:
                return None
            try:
                status, resp = request.next_chunk()
                attempt = 0
                if request.resumable_uri and request.resumable_uri != uri:
                    uri = request.resumable_uri
                    self.state.put_session(self.set_id, f, uri)
                progress = request.resumable_progress or 0
                if progress > reported:
                    tracker.add_bytes(progress - reported)
                    reported = progress
            except HttpError as exc:
                if exc.resp.status in (404, 410):  # oturum süresi dolmuş: baştan başla
                    self.state.drop_session(self.set_id, f)
                    tracker.add_bytes(-reported)
                    reported = 0
                    request = make_request(True)
                    uri = None
                    continue
                if not is_retryable(exc) or attempt >= 7:
                    raise
                request._in_error_state = True
                time.sleep(min(64, 2 ** attempt))
                attempt += 1
            except (OSError, TimeoutError) as exc:
                if attempt >= 7:
                    raise
                log.warning("Bağlantı hatası %s, devam edilecek", exc)
                request._in_error_state = True
                time.sleep(min(64, 2 ** attempt))
                attempt += 1
        if f.size > reported:
            tracker.add_bytes(f.size - reported)
        self.state.drop_session(self.set_id, f)
        return resp

    # -- tüm plan ---------------------------------------------------------------
    def run(self, plan: BackupPlan, on_progress: Callable[[dict], None] | None = None) -> ProgressTracker:
        for f, digest in plan.touched:  # yalnızca tarih değişmiş, içerik aynı
            rec = self.state.get_record(self.set_id, f.rel_path)
            self.state.put_record(self.set_id, f, digest, rec.drive_id if rec else None)
        items = plan.upload_items
        tracker = ProgressTracker(sum(i.file.size for i in items), len(items))
        self.ensure_root()
        slots = threading.BoundedSemaphore(self.workers * 2)
        pending = [0]
        pending_lock = threading.Lock()

        def work(item: PlanItem):
            name = item.file.rel_path
            tracker.active[name] = time.monotonic()
            try:
                parent = self.ensure_dir(item.file.rel_path.rpartition("/")[0])
                self._upload_one(item, parent, tracker)
                tracker.file_done(True)
            except Exception as exc:  # noqa: BLE001
                log.exception("Yükleme hatası: %s", name)
                tracker.file_done(False, f"{item.file.abs_path}: {exc}")
            finally:
                tracker.active.pop(name, None)
                with pending_lock:
                    pending[0] -= 1
                slots.release()

        with ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix="yukleme") as pool:
            for item in items:
                while not slots.acquire(timeout=0.5):
                    if on_progress:
                        on_progress(tracker.snapshot())
                if self.cancelled:
                    slots.release()
                    break
                with pending_lock:
                    pending[0] += 1
                pool.submit(work, item)
                if on_progress:
                    on_progress(tracker.snapshot())
            while pending[0] > 0:
                if on_progress:
                    on_progress(tracker.snapshot())
                time.sleep(0.5)
        self.state.mark_run(self.set_id)
        if on_progress:
            on_progress(tracker.snapshot())
        return tracker
