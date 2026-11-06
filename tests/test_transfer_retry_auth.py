import json

import pytest
from googleapiclient.errors import HttpError

from app.auth import AccountManager, read_client_config
from app.journal import Journal
from app.retry import backoff_delay, with_backoff
from app.transfer import StreamingUpload, apply_transfer, collect_tree, preview_transfer
from app.validation import ValidationError, validate_backup_folder
from fakes import FakeDrive


# ---- hesaplar arası aktarım ----------------------------------------------------
def accounts():
    src, dst = FakeDrive("kaynak@gmail.com"), FakeDrive("hedef@gmail.com")
    dst.shared_with["src"] = src
    top = src.add_folder("Tatil 2023")
    sub = src.add_folder("Videolar", top)
    src.add("a.jpg", top, "image/jpeg", 100)
    src.add("b.mp4", sub, "video/mp4", 5000)
    return src, dst, top


def test_transfer_copy_server_side_and_undo(tmp_path):
    src, dst, top = accounts()
    j = Journal(tmp_path / "j.db")
    tree = collect_tree(src, src.get(top))
    rows = preview_transfer([tree], src.email, dst.email, "Drive'ım", move=False)
    assert [r.action for r in rows] == ["Klasör oluştur", "Kopyala", "Klasör oluştur", "Kopyala"]
    assert dst.calls == [] and src.calls == []           # önizleme yan etkisiz

    res = apply_transfer(src, dst, j, [tree], "root", move=False)
    assert res.copied == 2 and res.failed == [] and res.trashed_sources == 0
    names = sorted(f["name"] for f in dst.files.values() if f["id"] != "root")
    assert names == ["Tatil 2023", "Videolar", "a.jpg", "b.mp4"]
    # geçici paylaşım kaldırıldı, bildirimsiz eklenmişti
    assert src.permissions[top] == {}
    assert not any(f["trashed"] for f in src.files.values())

    clients = {src.email: src, dst.email: dst}
    _, done, errors = j.undo_last(clients.__getitem__)
    assert errors == []
    assert all(f["trashed"] for f in dst.files.values() if f["id"] != "root")


def test_transfer_move_trashes_source_only_on_success(tmp_path):
    src, dst, top = accounts()
    j = Journal(tmp_path / "j.db")
    res = apply_transfer(src, dst, j, [collect_tree(src, src.get(top))], "root", move=True)
    assert res.trashed_sources == 1 and src.files[top]["trashed"]
    clients = {src.email: src, dst.email: dst}
    j.undo_last(clients.__getitem__)
    assert not src.files[top]["trashed"]                  # kaynak geri geldi

    src2, dst2, top2 = accounts()
    bad = [fid for fid, f in src2.files.items() if f["name"] == "b.mp4"][0]
    src2.fail_copy_ids.add(bad)
    res2 = apply_transfer(src2, dst2, Journal(tmp_path / "j2.db"), [collect_tree(src2, src2.get(top2))], "root",
                          move=True, allow_stream_fallback=False)
    assert res2.failed and res2.trashed_sources == 0
    assert not src2.files[top2]["trashed"]                # hata varsa kaynak çöpe atılmaz
    assert src2.permissions[top2] == {}                    # paylaşım yine de kaldırıldı


def test_streaming_upload_buffers_one_chunk():
    data = bytes(range(256)) * 100
    chunks = iter([data[i:i + 1000] for i in range(0, len(data), 1000)])
    up = StreamingUpload(chunks, len(data), "video/mp4", chunksize=4096)
    assert up.getbytes(0, 4096) == data[:4096]
    assert up.getbytes(0, 4096) == data[:4096]            # hata sonrası aynı parça tekrar
    assert up.getbytes(4096, 4096) == data[4096:8192]
    assert len(up._buf) < 4096 + 1000 * 2                 # tüm dosya bellekte değil
    with pytest.raises(IOError):
        up.getbytes(0, 10)
    assert up.getbytes(24576, 4096) == data[24576:]


# ---- üstel geri çekilme ----------------------------------------------------------
class Resp(dict):
    def __init__(self, status):
        super().__init__()
        self.status = status
        self.reason = "x"


def http_error(status, reason=""):
    body = json.dumps({"error": {"errors": [{"reason": reason}]}}).encode()
    return HttpError(Resp(status), body)


def test_backoff_retries_429_and_rate_limit_403():
    calls, sleeps = [], []
    errors = [http_error(429), http_error(403, "userRateLimitExceeded"), http_error(503)]

    def fn():
        calls.append(1)
        if errors:
            raise errors.pop(0)
        return "tamam"

    assert with_backoff(fn, sleep=sleeps.append) == "tamam"
    assert len(calls) == 4
    assert sleeps[0] < sleeps[1] < sleeps[2]              # üstel artış


def test_backoff_does_not_retry_permanent_errors():
    for err in (http_error(404), http_error(403, "insufficientFilePermissions")):
        calls = []

        def fn(err=err):
            calls.append(1)
            raise err

        with pytest.raises(HttpError):
            with_backoff(fn, sleep=lambda s: None)
        assert len(calls) == 1


def test_backoff_gives_up():
    with pytest.raises(HttpError):
        with_backoff(lambda: (_ for _ in ()).throw(http_error(500)), max_attempts=3, sleep=lambda s: None)
    assert 1 <= backoff_delay(0, rng=lambda: 0) <= 1 and backoff_delay(10, rng=lambda: 0) == 64


# ---- kimlik bilgileri / hesaplar ----------------------------------------------------
class MemoryStore:
    def __init__(self):
        self.d = {}

    def save(self, e, t):
        self.d[e] = t

    def load(self, e):
        return self.d.get(e)

    def delete(self, e):
        self.d.pop(e, None)


def test_client_config_validation(tmp_path):
    good = tmp_path / "c.json"
    good.write_text(json.dumps({"installed": {"client_id": "1-abc.apps.googleusercontent.com",
                                              "client_secret": "s", "token_uri": "t"}}))
    assert read_client_config(good)["installed"]["client_secret"] == "s"
    web = tmp_path / "w.json"
    web.write_text(json.dumps({"web": {"client_id": "x", "client_secret": "y"}}))
    with pytest.raises(ValidationError, match="Masaüstü"):
        read_client_config(web)
    junk = tmp_path / "j.json"
    junk.write_text("bozuk")
    with pytest.raises(ValidationError):
        read_client_config(junk)


def test_accounts_never_store_tokens_in_plain_files(tmp_path):
    store = MemoryStore()
    mgr = AccountManager(store, tmp_path / "hesaplar.json", tmp_path / "credentials.json")
    mgr._register("Ali@Gmail.com", "Ali", "1//GIZLI-REFRESH-TOKEN")
    mgr._register("veli@gmail.com", "Veli", "1//BASKA-TOKEN")
    assert [a["email"] for a in mgr.list_accounts()] == ["ali@gmail.com", "veli@gmail.com"]
    assert "GIZLI" not in (tmp_path / "hesaplar.json").read_text(encoding="utf-8")
    assert store.d["ali@gmail.com"] == "1//GIZLI-REFRESH-TOKEN"
    mgr.remove_account("ali@gmail.com", revoke=False)
    assert "ali@gmail.com" not in store.d
    assert [a["email"] for a in mgr.list_accounts()] == ["veli@gmail.com"]


def test_backup_folder_validation(tmp_path):
    (tmp_path / "SahteKlasor").mkdir()
    assert validate_backup_folder(str(tmp_path / "SahteKlasor")).name == "SahteKlasor"
    for bad in ("", "goreli\\yol", str(tmp_path / "yok"), "C:\\", "C:\\Windows"):
        with pytest.raises(ValidationError):
            validate_backup_folder(bad)
