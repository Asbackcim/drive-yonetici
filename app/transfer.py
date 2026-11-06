"""Hesaplar arası kopyalama / taşıma.

BİRİNCİL YÖNTEM — paylaşım + sunucu tarafı kopya (permissions + files.copy):
  1. Kaynak hesap, seçili öğeyi hedef hesaba "Görüntüleyen" olarak paylaşır
     (bildirim e-postası gönderilmez).
  2. Hedef hesap ``files.copy`` ile kopyayı KENDİ Drive'ında oluşturur. Veri Google'ın
     sunucuları arasında kopyalanır; bilgisayara hiç inmez, internet kotası harcanmaz,
     100 GB'lık klasör bile ev bağlantısından bağımsız hızda kopyalanır. Google
     Dokümanlar/E-Tablolar gibi yerel türler de bozulmadan kopyalanır ve yeni kopyanın
     sahibi hedef hesaptır.
  3. İş bitince geçici paylaşım kaldırılır (finally bloğunda).

YEDEK YÖNTEM — akış halinde indir/yükle:
  Sahibi kopyalamayı kısıtladıysa vb. ``files.copy`` başarısız olursa dosya kaynak
  hesaptan parça parça indirilir ve aynı anda hedefe resumable upload ile yüklenir.
  Bellekte yalnızca bir parça (8 MB) tutulur; dosya diske hiç yazılmaz.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Iterator

from googleapiclient.http import MediaUpload

from .categorize import FOLDER_MIME
from .journal import Journal
from .operations import PreviewRow
from .retry import with_backoff

log = logging.getLogger(__name__)
GOOGLE_NATIVE_PREFIX = "application/vnd.google-apps."


@dataclass
class TransferNode:
    id: str
    name: str
    mime: str
    size: int
    rel_path: str
    children: list["TransferNode"] = field(default_factory=list)

    @property
    def is_folder(self) -> bool:
        return self.mime == FOLDER_MIME


def collect_tree(src_client, item: dict, rel: str = "", cancel=None, depth: int = 0) -> TransferNode:
    node = TransferNode(item["id"], item["name"], item.get("mimeType", ""), int(item.get("size") or 0),
                        f"{rel}/{item['name']}" if rel else item["name"])
    if node.is_folder and depth < 100:
        for child in sorted(src_client.list_children(item["id"], cancel=cancel), key=lambda c: c["name"].lower()):
            if cancel and cancel():
                break
            node.children.append(collect_tree(src_client, child, node.rel_path, cancel, depth + 1))
    return node


def walk(node: TransferNode) -> Iterator[TransferNode]:
    yield node
    for c in node.children:
        yield from walk(c)


def preview_transfer(roots: list[TransferNode], src_email: str, dst_email: str, dst_label: str,
                     move: bool) -> list[PreviewRow]:
    rows: list[PreviewRow] = []
    for root in roots:
        for n in walk(root):
            if n.is_folder:
                rows.append(PreviewRow("Klasör oluştur", n.name, f"{dst_email}: {dst_label}/{n.rel_path}"))
            else:
                rows.append(PreviewRow("Kopyala", n.name, f"{src_email} -> {dst_email}: {dst_label}/{n.rel_path}",
                                       n.size, n.id))
        if move:
            rows.append(PreviewRow("Çöpe taşı (kaynak)", root.name,
                                   f"{src_email}: kopyalama başarıyla bitince kaynaktaki öğe çöp kutusuna taşınır "
                                   "(30 gün içinde geri alınabilir)", root.size, root.id))
    return rows


# ---------------------------------------------------------------------------
# Akış halinde aktarım (yedek yöntem)
# ---------------------------------------------------------------------------
class StreamingUpload(MediaUpload):
    """İleri doğru akan bir bayt kaynağını resumable upload'a besler.

    googleapiclient her parçayı ``getbytes(başlangıç, uzunluk)`` ile ister. Hata sonrası aynı
    parça tekrar istenebileceği için yalnızca mevcut parça tamponda tutulur.
    """

    def __init__(self, chunks: Iterator[bytes], size: int, mimetype: str, chunksize: int = 8 * 1024 * 1024):
        self._it = chunks
        self._size = size
        self._mime = mimetype or "application/octet-stream"
        self._chunksize = chunksize
        self._buf = bytearray()
        self._buf_start = 0

    # MediaUpload arayüzü
    def chunksize(self):
        return self._chunksize

    def mimetype(self):
        return self._mime

    def size(self):
        return self._size

    def resumable(self):
        return True

    def has_stream(self):
        return False

    def stream(self):
        return None

    def to_json(self):
        raise NotImplementedError("Akış yüklemesi serileştirilemez")

    def getbytes(self, begin: int, length: int) -> bytes:
        if begin < self._buf_start:
            raise IOError("Akış geriye sarılamaz; yükleme baştan başlatılmalı")
        # 'begin' öncesindeki baytları at (gerekirse akıştan okuyup atarak ilerle)
        while self._buf_start + len(self._buf) < begin:
            self._buf_start += len(self._buf)
            self._buf.clear()
            try:
                self._buf.extend(next(self._it))
            except StopIteration:
                break
        drop = begin - self._buf_start
        if drop > 0:
            del self._buf[:drop]
            self._buf_start = begin
        while len(self._buf) < length:
            try:
                self._buf.extend(next(self._it))
            except StopIteration:
                break
        return bytes(self._buf[:length])


def stream_copy(src_client, dst_client, file: TransferNode, dst_parent: str, chunk: int = 8 * 1024 * 1024,
                cancel: Callable[[], bool] | None = None, on_bytes: Callable[[int], None] | None = None) -> str:
    if file.mime.startswith(GOOGLE_NATIVE_PREFIX):
        raise RuntimeError("Google yerel dosyaları (Doküman/E-Tablo) yalnızca sunucu tarafı kopyayla aktarılabilir")
    from google.auth.transport.requests import AuthorizedSession

    session = AuthorizedSession(src_client.credentials)
    url = f"https://www.googleapis.com/drive/v3/files/{file.id}?alt=media"
    resp = with_backoff(lambda: _checked(session.get(url, stream=True, timeout=120)))
    try:
        media = StreamingUpload(resp.iter_content(1024 * 1024), file.size, file.mime, chunk)
        request = dst_client.service().files().create(
            body={"name": file.name, "parents": [dst_parent]}, media_body=media, fields="id")
        result = None
        last = 0
        while result is None:
            if cancel and cancel():
                raise InterruptedError("İptal edildi")
            _, result = request.next_chunk(num_retries=5)
            if on_bytes and request.resumable_progress:
                on_bytes(request.resumable_progress - last)
                last = request.resumable_progress
        return result["id"]
    finally:
        resp.close()


def _checked(resp):
    if resp.status_code >= 400:
        err = RuntimeError(f"İndirme hatası HTTP {resp.status_code}")
        err.status_code = resp.status_code  # retry.is_retryable için
        resp.close()
        raise err
    return resp


# ---------------------------------------------------------------------------
# Uygulama
# ---------------------------------------------------------------------------
@dataclass
class TransferResult:
    batch_id: int
    copied: int = 0
    streamed: int = 0
    failed: list[str] = field(default_factory=list)
    trashed_sources: int = 0
    cancelled: bool = False


def apply_transfer(src_client, dst_client, journal: Journal, roots: list[TransferNode], dst_parent: str,
                   move: bool, progress: Callable[[int, int, str], None] | None = None,
                   cancel: Callable[[], bool] | None = None, allow_stream_fallback: bool = True) -> TransferResult:
    src_email, dst_email = src_client.email, dst_client.email
    title = f"{'Taşıma' if move else 'Kopyalama'}: {src_email} -> {dst_email} ({len(roots)} öğe)"
    batch = journal.start_batch(dst_email, title)
    result = TransferResult(batch)
    total = sum(1 for r in roots for _ in walk(r))
    step = 0

    for root in roots:
        perm_id = None
        root_failed = False
        try:
            perm_id = src_client.add_reader(root.id, dst_email)

            def handle(node: TransferNode, parent: str):
                nonlocal step, root_failed
                if cancel and cancel():
                    result.cancelled = True
                    return
                step += 1
                if progress:
                    progress(step, total, node.rel_path)
                if node.is_folder:
                    fid = dst_client.create_folder(node.name, parent)
                    journal.record(batch, dst_email, "create_folder", fid, node.name, parent=parent)
                    for c in node.children:
                        handle(c, fid)
                    return
                try:
                    new = dst_client.copy(node.id, parent, node.name)
                    journal.record(batch, dst_email, "copy", new["id"], node.name, source=node.id, method="server")
                    result.copied += 1
                except Exception as exc:  # noqa: BLE001
                    if not allow_stream_fallback:
                        root_failed = True
                        result.failed.append(f"{node.rel_path}: {exc}")
                        return
                    try:
                        new_id = stream_copy(src_client, dst_client, node, parent, cancel=cancel)
                        journal.record(batch, dst_email, "copy", new_id, node.name, source=node.id, method="stream")
                        result.streamed += 1
                    except Exception as exc2:  # noqa: BLE001
                        root_failed = True
                        result.failed.append(f"{node.rel_path}: {exc2}")

            handle(root, dst_parent)
        except Exception as exc:  # noqa: BLE001
            root_failed = True
            result.failed.append(f"{root.rel_path}: {exc}")
        finally:
            if perm_id:
                try:
                    src_client.remove_permission(root.id, perm_id)
                except Exception as exc:  # noqa: BLE001
                    result.failed.append(f"Geçici paylaşım kaldırılamadı ({root.name}): {exc}")
        if result.cancelled:
            break
        if move and not root_failed:
            try:
                src_client.trash(root.id)
                journal.record(batch, src_email, "trash", root.id, root.name, reason="hesaplar arası taşıma")
                result.trashed_sources += 1
            except Exception as exc:  # noqa: BLE001
                result.failed.append(f"Kaynak çöpe taşınamadı ({root.name}): {exc}")
    done = result.copied + result.streamed
    journal.finish_batch(batch, "applied" if done else "failed")
    return result
