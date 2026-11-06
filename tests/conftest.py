import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Testler kullanıcının gerçek %APPDATA% klasörüne asla yazmaz."""
    monkeypatch.setenv("DRIVE_YONETICI_HOME", str(tmp_path / "home"))
    return tmp_path / "home"
