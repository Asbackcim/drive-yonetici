"""Bellek içi sahte Drive istemcisi (DriveClient arayüzünün test için gereken kısmı).

Gerçek Google'a HİÇBİR istek atılmaz.
"""
from __future__ import annotations

import itertools

FOLDER = "application/vnd.google-apps.folder"


class FakeDrive:
    _ids = itertools.count(1)

    def __init__(self, email: str = "a@example.com", quota_limit: int | None = 15 * 1024**3, usage: int = 0):
        self.email = email
        self.files: dict[str, dict] = {"root": {"id": "root", "name": "Drive'ım", "mimeType": FOLDER,
                                                "parents": [], "trashed": False}}
        self.permissions: dict[str, dict[str, str]] = {}
        self.calls: list[tuple] = []
        self.quota_limit, self.usage = quota_limit, usage
        self.fail_copy_ids: set[str] = set()
        self.shared_with: dict[str, "FakeDrive"] = {}

    # yardımcı
    def add(self, name, parent="root", mime="application/octet-stream", size=0, md5=None, **extra) -> str:
        fid = f"f{next(self._ids)}"
        self.files[fid] = {"id": fid, "name": name, "mimeType": mime, "parents": [parent], "size": str(size),
                           "md5Checksum": md5, "trashed": False, "ownedByMe": True, **extra}
        return fid

    def add_folder(self, name, parent="root") -> str:
        return self.add(name, parent, mime=FOLDER)

    # DriveClient arayüzü
    def root_id(self):
        return "root"

    def quota(self):
        return self.quota_limit, self.usage

    def get(self, fid, fields=None):
        return dict(self.files[fid])

    def list_children(self, parent_id, cancel=None):
        return [dict(f) for f in self.files.values() if parent_id in f.get("parents", []) and not f["trashed"]]

    def find_folder(self, name, parent_id):
        for f in self.list_children(parent_id):
            if f["name"] == name and f["mimeType"] == FOLDER:
                return f["id"]
        return None

    def create_folder(self, name, parent_id):
        self.calls.append(("create_folder", name, parent_id))
        return self.add_folder(name, parent_id)

    def ensure_folder(self, name, parent_id):
        fid = self.find_folder(name, parent_id)
        if fid:
            return fid, False
        return self.create_folder(name, parent_id), True

    def move(self, fid, add_parents, remove_parents):
        self.calls.append(("move", fid, tuple(add_parents), tuple(remove_parents)))
        f = self.files[fid]
        f["parents"] = [p for p in f["parents"] if p not in remove_parents] + list(add_parents)
        return {"id": fid, "parents": f["parents"]}

    def trash(self, fid):
        self.calls.append(("trash", fid))
        self.files[fid]["trashed"] = True
        return {"id": fid, "trashed": True}

    def untrash(self, fid):
        self.calls.append(("untrash", fid))
        self.files[fid]["trashed"] = False
        return {"id": fid, "trashed": False}

    def add_reader(self, fid, email):
        pid = f"p{next(self._ids)}"
        self.permissions.setdefault(fid, {})[pid] = email
        self.calls.append(("add_reader", fid, email))
        return pid

    def remove_permission(self, fid, pid):
        self.calls.append(("remove_permission", fid, pid))
        del self.permissions[fid][pid]

    def copy(self, fid, parent_id, name=None):
        # hedef hesap, kaynak hesabın paylaştığı dosyayı kopyalar
        for src in self.shared_with.values():
            if fid in src.files and self._can_read(src, fid):
                if fid in src.fail_copy_ids:
                    raise RuntimeError("cannotCopyFile")
                s = src.files[fid]
                new = self.add(name or s["name"], parent_id, s["mimeType"], int(s.get("size") or 0), s.get("md5Checksum"))
                self.calls.append(("copy", fid, new))
                return {"id": new, "name": name or s["name"]}
        raise RuntimeError("notFound")

    def _can_read(self, src: "FakeDrive", fid: str) -> bool:
        cur = fid
        for _ in range(50):
            if self.email in src.permissions.get(cur, {}).values():
                return True
            parents = src.files.get(cur, {}).get("parents") or []
            if not parents:
                return False
            cur = parents[0]
        return False
