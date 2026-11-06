import pytest

from app.excludes import ExcludeMatcher
from app.settings import DEFAULT_EXCLUDES
from app.validation import ValidationError


@pytest.fixture
def m():
    return ExcludeMatcher(DEFAULT_EXCLUDES)


@pytest.mark.parametrize("path", [
    "Projeler/site/node_modules/react/index.js",
    "Projeler/app/.git/HEAD",
    "Kod/MyApp/bin/Debug/app.exe",
    "Kod/MyApp/obj/project.assets.json",
    "Belgeler/rapor.tmp",
    "Belgeler/~$rapor.docx",
    "Unity/Oyun/Library/cache.bin",
    "Masaustu/Thumbs.db",
    "Indirilenler/film.mkv.crdownload",
    "A/NODE_MODULES/x.js",          # büyük/küçük harf duyarsız
    "A\\Temp\\x.log",               # Windows ayracı
])
def test_excluded(m, path):
    assert m.is_excluded(path)


@pytest.mark.parametrize("path", [
    "Belgeler/rapor.docx",
    "Resimler/2024/tatil.jpg",
    "Kod/binary-search/main.py",    # 'bin' tam bileşen değil
    "Belgeler/template.txt",        # 'temp' içerir ama eşleşmez
    "Muzik/objektif.mp3",
])
def test_not_excluded(m, path):
    assert not m.is_excluded(path)


def test_path_glob_and_custom_patterns():
    m = ExcludeMatcher(["Projeler/*/build", "*.iso"])
    assert m.is_excluded("Projeler/oyun/build/out.bin")
    assert not m.is_excluded("Diger/oyun/build/out.bin")
    assert m.is_excluded("Arsiv/windows.ISO")


def test_invalid_patterns_rejected():
    with pytest.raises(ValidationError):
        ExcludeMatcher(["../gizli"])
    with pytest.raises(ValidationError):
        ExcludeMatcher(["kötü\x00desen"])


def test_name_excluded_fast_path(m):
    assert m.is_name_excluded("node_modules")
    assert m.is_name_excluded("a.TMP")
    assert not m.is_name_excluded("Belgeler")
