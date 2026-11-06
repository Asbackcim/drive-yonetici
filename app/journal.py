"""İşlem günlüğü ve "Son işlemi geri al".

Her toplu işlem (ör. "12 kopyayı çöpe taşı") bir PARTİ (batch) olarak kaydedilir;
partinin içindeki her adım (taşıma, çöpe atma, klasör oluşturma, kopyalama) ayrı
satırdır. Geri alma, son partinin adımlarını TERS sırada tersine çevirir:

    move          -> eski klasörlere geri taşı
    trash         -> çöpten geri al (untrash)
    create_folder -> klasör boşsa çöpe taşı
    copy          -> oluşturulan kopyayı çöpe taşı
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import paths

UNDOABLE = {"move", "trash", "create_folder", "copy"}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account TEXT NOT NULL,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open'   -- open | applied | failed | undone | undo_partial
);
CREATE TABLE IF NOT EXISTS ops (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER NOT NULL REFERENCES batches(id),
    account TEXT NOT NULL,
    kind TEXT NOT NULL,
    file_id TEXT,
    name TEXT,
    payload TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    undone INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_ops_batch ON ops(batch_id);
"""


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Journal:
    def __init__(self, db_path: Path | str | None = None):
        self.db_path = str(db_path or paths.journal_db_path())
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    @contextmanager
    def _tx(self):
        with self._lock:
            try:
                yield self._conn
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    # ---- yazma ---------------------------------------------------------------
    def start_batch(self, account: str, title: str) -> int:
        with self._tx() as c:
            cur = c.execute("INSERT INTO batches(account,title,created_at) VALUES (?,?,?)", (account, title, _now()))
            return int(cur.lastrowid)

    def record(self, batch_id: int, account: str, kind: str, file_id: str | None, name: str = "",
               **payload) -> None:
        with self._tx() as c:
            c.execute("INSERT INTO ops(batch_id,account,kind,file_id,name,payload,created_at) VALUES (?,?,?,?,?,?,?)",
                      (batch_id, account, kind, file_id, name, json.dumps(payload, ensure_ascii=False), _now()))

    def finish_batch(self, batch_id: int, status: str = "applied") -> None:
        with self._tx() as c:
            c.execute("UPDATE batches SET status=? WHERE id=?", (status, batch_id))

    # ---- okuma ---------------------------------------------------------------
    def batches(self, limit: int = 200) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT b.*, (SELECT COUNT(*) FROM ops o WHERE o.batch_id=b.id) AS op_count "
                "FROM batches b ORDER BY b.id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def ops(self, batch_id: int) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM ops WHERE batch_id=? ORDER BY id", (batch_id,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["payload"] = json.loads(d["payload"] or "{}")
            out.append(d)
        return out

    def last_undoable_batch(self) -> dict | None:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM batches WHERE status IN ('applied','failed','undo_partial') ORDER BY id DESC").fetchall()
        for r in rows:
            if any(o["kind"] in UNDOABLE and not o["undone"] for o in self.ops(r["id"])):
                return dict(r)
        return None

    # ---- geri alma ------------------------------------------------------------
    def undo_batch(self, batch_id: int, get_client: Callable[[str], object],
                   progress: Callable[[int, int, str], None] | None = None) -> tuple[int, list[str]]:
        """(geri alınan adım sayısı, hata mesajları)."""
        todo = [o for o in reversed(self.ops(batch_id)) if o["kind"] in UNDOABLE and not o["undone"]]
        done = 0
        errors: list[str] = []
        for i, op in enumerate(todo, 1):
            client = get_client(op["account"])
            p = op["payload"]
            try:
                if op["kind"] == "move":
                    client.move(op["file_id"], add_parents=p["from"], remove_parents=p["to"])
                elif op["kind"] == "trash":
                    client.untrash(op["file_id"])
                elif op["kind"] == "copy":
                    client.trash(op["file_id"])
                elif op["kind"] == "create_folder":
                    if client.list_children(op["file_id"]):
                        errors.append(f"'{op['name']}' klasörü boş değil, yerinde bırakıldı.")
                    else:
                        client.trash(op["file_id"])
                with self._tx() as c:
                    c.execute("UPDATE ops SET undone=1 WHERE id=?", (op["id"],))
                done += 1
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{op['name'] or op['file_id']}: {exc}")
            if progress:
                progress(i, len(todo), op["name"] or "")
        remaining = [o for o in self.ops(batch_id) if o["kind"] in UNDOABLE and not o["undone"]]
        self.finish_batch(batch_id, "undone" if not remaining else "undo_partial")
        return done, errors

    def undo_last(self, get_client, progress=None) -> tuple[dict | None, int, list[str]]:
        batch = self.last_undoable_batch()
        if not batch:
            return None, 0, []
        done, errors = self.undo_batch(batch["id"], get_client, progress)
        return batch, done, errors
