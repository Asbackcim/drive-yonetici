import pytest

from app.categorize import build_category_plan, category_distribution, classify, normalize_rules
from app.settings import DEFAULT_CATEGORIES
from app.validation import ValidationError

FOLDER = "application/vnd.google-apps.folder"


@pytest.mark.parametrize("name,mime,expected", [
    ("rapor.PDF", "application/pdf", "Belgeler"),
    ("tatil.jpeg", "image/jpeg", "Resimler"),
    ("IMG_0001", "image/heic", "Resimler"),          # uzantısız, MIME'den
    ("klip.mp4", "video/mp4", "Videolar"),
    ("sarki.flac", "audio/flac", "Müzik"),
    ("yedek.7z", "application/x-7z", "Arşivler"),
    ("main.py", "text/x-python", "Kod"),
    ("Bütçe", "application/vnd.google-apps.spreadsheet", "Belgeler"),
    ("garip.xyz", "application/octet-stream", "Diğer"),
    ("noktasiz", "application/octet-stream", "Diğer"),
])
def test_classify(name, mime, expected):
    assert classify({"name": name, "mimeType": mime}, DEFAULT_CATEGORIES) == expected


def test_user_rules_override():
    rules = {"Belgeler": ["pdf"], "Tasarım": ["psd", "fig"]}
    assert classify({"name": "logo.psd", "mimeType": "image/vnd.adobe"}, rules) == "Tasarım"
    assert classify({"name": "x.docx", "mimeType": "application/x"}, rules) == "Diğer"


def test_rules_validation():
    with pytest.raises(ValidationError):
        normalize_rules({"A": ["pdf"], "B": ["pdf"]})       # çakışan uzantı
    with pytest.raises(ValidationError):
        normalize_rules({"Diğer": ["x"]})                    # ayrılmış kategori
    with pytest.raises(ValidationError):
        normalize_rules({"A": ["p d f"]})                    # geçersiz uzantı
    with pytest.raises(ValidationError):
        normalize_rules({})
    assert normalize_rules({" Belgeler ": [".PDF", "pdf"]}) == {"Belgeler": ["pdf"]}


def test_build_plan_reuses_existing_folder_and_skips_folders():
    children = [
        {"id": "d1", "name": "Resimler", "mimeType": FOLDER},
        {"id": "a", "name": "a.jpg", "mimeType": "image/jpeg", "size": "10"},
        {"id": "b", "name": "b.pdf", "mimeType": "application/pdf", "size": "20"},
        {"id": "c", "name": "c.docx", "mimeType": "application/x", "size": "5"},
        {"id": "e", "name": "Alt", "mimeType": FOLDER},
        {"id": "t", "name": "eski.pdf", "mimeType": "application/pdf", "trashed": True},
    ]
    plan = build_category_plan(children, "root", DEFAULT_CATEGORIES)
    by_id = {i.file_id: i for i in plan.items}
    assert set(by_id) == {"a", "b", "c"}
    assert by_id["a"].target_folder_id == "d1"          # mevcut klasör kullanılır
    assert by_id["b"].target_folder_id is None
    assert plan.folders_to_create == ["Belgeler"]
    assert plan.summary() == {"Belgeler": 2, "Resimler": 1}


def test_plan_min_files_and_other():
    children = [{"id": "x", "name": "x.zzz", "mimeType": "a/b"}, {"id": "y", "name": "y.pdf", "mimeType": "a/b"}]
    plan = build_category_plan(children, "p", DEFAULT_CATEGORIES, include_other=False)
    assert [i.file_id for i in plan.items] == ["y"]
    plan = build_category_plan(children, "p", DEFAULT_CATEGORIES, min_files_per_category=2)
    assert plan.items == []


def test_distribution():
    files = [{"name": "a.jpg", "mimeType": "image/jpeg", "size": "100"},
             {"name": "b.mp4", "mimeType": "video/mp4", "size": "300"},
             {"name": "c.png", "mimeType": "image/png", "size": "50"},
             {"name": "D", "mimeType": FOLDER}]
    assert category_distribution(files, DEFAULT_CATEGORIES) == {"Videolar": 300, "Resimler": 150}
