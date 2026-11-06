"""Google Drive API v3 ince sarmalayıcısı.

- Her iş parçacığı kendi httplib2 bağlantısını kullanır (httplib2 thread-safe değildir).
- Tüm çağrılar üstel geri çekilme (retry.with_backoff) ile yapılır.
- Kalıcı silme (files.delete / emptyTrash) BİLEREK YOKTUR. Yalnızca trashed=true.
"""
from __future__ import annotations

import threading
from typing import Callable, Iterator

from .categorize import FOLDER_MIME
from .retry import with_backoff
from .validation import sanitize_drive_name, validate_drive_id

FILE_FIELDS = ("id,name,mimeType,size,quotaBytesUsed,md5Checksum,parents,createdTime,modifiedTime,"
               "viewedByMeTime,trashed,ownedByMe,webViewLink,capabilities(canTrash,canMoveItemWithinDrive,canCopy)")


def _q_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("'", "\\'")


class DriveClient:
    def __init__(self, credentials, email: str = ""):
        self.credentials = credentials
        self.email = email
        self._local = threading.local()
        self._root_id: str | None = None

    # ---- altyapı -----------------------------------------------------------
    def service(self):
        svc = getattr(self._local, "svc", None)
        if svc is None:
            import google_auth_httplib2
            import httplib2
            from googleapiclient.discovery import build

            http = google_auth_httplib2.AuthorizedHttp(self.credentials, http=httplib2.Http(timeout=120))
            svc = build("drive", "v3", http=http, cache_discovery=False, static_discovery=True)
            self._local.svc = svc
        return svc

    def authorized_http(self):
        return self.service()._http

    def _exec(self, request_factory: Callable):
        return with_backoff(lambda: request_factory().execute())

    # ---- okuma -------------------------------------------------------------
    def about(self) -> dict:
        return self._exec(lambda: self.service().about().get(fields="user(emailAddress,displayName),storageQuota"))

    def quota(self) -> tuple[int | None, int]:
        """(limit, kullanılan). limit None => sınırsız."""
        q = self.about().get("storageQuota", {})
        limit = int(q["limit"]) if q.get("limit") else None
        return limit, int(q.get("usage", 0))

    def root_id(self) -> str:
        if self._root_id is None:
            self._root_id = self._exec(lambda: self.service().files().get(fileId="root", fields="id"))["id"]
        return self._root_id

    def get(self, file_id: str, fields: str = FILE_FIELDS) -> dict:
        if file_id != "root":
            validate_drive_id(file_id)
        return self._exec(lambda: self.service().files().get(fileId=file_id, fields=fields, supportsAllDrives=True))

    def iter_files(self, query: str, fields: str = FILE_FIELDS, page_size: int = 1000,
                   cancel: Callable[[], bool] | None = None) -> Iterator[dict]:
        token = None
        while True:
            resp = self._exec(lambda: self.service().files().list(
                q=query, fields=f"nextPageToken,files({fields})", pageSize=page_size,
                pageToken=token, spaces="drive"))
            yield from resp.get("files", [])
            token = resp.get("nextPageToken")
            if not token or (cancel and cancel()):
                return

    def list_all_files(self, progress: Callable[[int], None] | None = None,
                       cancel: Callable[[], bool] | None = None, include_shared: bool = False) -> list[dict]:
        q = "trashed = false" + ("" if include_shared else " and 'me' in owners")
        out = []
        for f in self.iter_files(q, cancel=cancel):
            out.append(f)
            if progress and len(out) % 500 == 0:
                progress(len(out))
        if progress:
            progress(len(out))
        return out

    def list_children(self, parent_id: str, cancel=None) -> list[dict]:
        pid = "root" if parent_id == "root" else validate_drive_id(parent_id)
        return list(self.iter_files(f"'{pid}' in parents and trashed = false", cancel=cancel))

    def list_folders(self, parent_id: str = "root") -> list[dict]:
        pid = "root" if parent_id == "root" else validate_drive_id(parent_id)
        q = f"'{pid}' in parents and trashed = false and mimeType = '{FOLDER_MIME}'"
        return sorted(self.iter_files(q, fields="id,name,parents"), key=lambda f: f["name"].lower())

    def find_folder(self, name: str, parent_id: str) -> str | None:
        q = (f"name = '{_q_escape(name)}' and '{parent_id}' in parents and "
             f"mimeType = '{FOLDER_MIME}' and trashed = false")
        for f in self.iter_files(q, fields="id,name", page_size=10):
            return f["id"]
        return None

    # ---- yazma (hepsi geri alınabilir) -------------------------------------
    def create_folder(self, name: str, parent_id: str) -> str:
        body = {"name": sanitize_drive_name(name), "mimeType": FOLDER_MIME, "parents": [parent_id]}
        return self._exec(lambda: self.service().files().create(body=body, fields="id"))["id"]

    def ensure_folder(self, name: str, parent_id: str) -> tuple[str, bool]:
        existing = self.find_folder(sanitize_drive_name(name), parent_id)
        if existing:
            return existing, False
        return self.create_folder(name, parent_id), True

    def move(self, file_id: str, add_parents: list[str], remove_parents: list[str]) -> dict:
        validate_drive_id(file_id)
        return self._exec(lambda: self.service().files().update(
            fileId=file_id, addParents=",".join(add_parents), removeParents=",".join(remove_parents),
            fields="id,parents"))

    def trash(self, file_id: str) -> dict:
        validate_drive_id(file_id)
        return self._exec(lambda: self.service().files().update(
            fileId=file_id, body={"trashed": True}, fields="id,trashed"))

    def untrash(self, file_id: str) -> dict:
        validate_drive_id(file_id)
        return self._exec(lambda: self.service().files().update(
            fileId=file_id, body={"trashed": False}, fields="id,trashed"))

    def copy(self, file_id: str, parent_id: str, name: str | None = None) -> dict:
        validate_drive_id(file_id)
        body: dict = {"parents": [parent_id]}
        if name:
            body["name"] = sanitize_drive_name(name)
        return self._exec(lambda: self.service().files().copy(fileId=file_id, body=body, fields="id,name,size"))

    def add_reader(self, file_id: str, email: str) -> str:
        body = {"type": "user", "role": "reader", "emailAddress": email}
        resp = self._exec(lambda: self.service().permissions().create(
            fileId=file_id, body=body, sendNotificationEmail=False, fields="id"))
        return resp["id"]

    def remove_permission(self, file_id: str, permission_id: str) -> None:
        self._exec(lambda: self.service().permissions().delete(fileId=file_id, permissionId=permission_id))
