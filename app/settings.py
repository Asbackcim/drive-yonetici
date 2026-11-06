"""Kullanıcı ayarları (JSON). Gizli bilgi İÇERMEZ."""
from __future__ import annotations

import copy
import json
import threading
from pathlib import Path

from . import paths

DEFAULT_EXCLUDES = [
    "node_modules",
    ".git",
    ".svn",
    "__pycache__",
    ".venv",
    "Library",
    "Temp",
    "tmp",
    "$RECYCLE.BIN",
    "System Volume Information",
    "bin",
    "obj",
    "*.tmp",
    "*.temp",
    "~$*",
    "Thumbs.db",
    "desktop.ini",
    "*.lnk",
    "*.part",
    "*.crdownload",
]

DEFAULT_CATEGORIES: dict[str, list[str]] = {
    "Belgeler": ["pdf", "doc", "docx", "odt", "rtf", "txt", "md", "xls", "xlsx", "ods", "csv",
                 "ppt", "pptx", "odp", "epub", "pages", "numbers", "key"],
    "Resimler": ["jpg", "jpeg", "png", "gif", "bmp", "webp", "heic", "heif", "tif", "tiff",
                 "svg", "raw", "cr2", "nef", "arw", "dng", "psd", "ai"],
    "Videolar": ["mp4", "mov", "avi", "mkv", "wmv", "flv", "webm", "m4v", "3gp", "mts"],
    "Müzik": ["mp3", "wav", "flac", "aac", "ogg", "m4a", "wma", "opus", "aiff"],
    "Arşivler": ["zip", "rar", "7z", "tar", "gz", "bz2", "xz", "iso", "dmg", "tgz"],
    "Kod": ["py", "js", "ts", "tsx", "jsx", "java", "c", "cpp", "h", "cs", "go", "rs", "php",
            "rb", "html", "css", "json", "xml", "yml", "yaml", "sql", "sh", "ps1", "ipynb"],
}
OTHER_CATEGORY = "Diğer"

DEFAULTS = {
    "theme": "system",  # system | light | dark
    "exclude_patterns": DEFAULT_EXCLUDES,
    "categories": DEFAULT_CATEGORIES,
    "parallel_uploads": 3,
    "chunk_mb": 8,
    "backup_folders": [],
}


class Settings:
    def __init__(self, path: Path | None = None):
        self.path = path or paths.settings_path()
        self._lock = threading.Lock()
        self.data = copy.deepcopy(DEFAULTS)
        self.load()

    def load(self) -> None:
        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    for k in DEFAULTS:
                        if k in loaded:
                            self.data[k] = loaded[k]
            except (OSError, json.JSONDecodeError):
                pass  # bozuk dosya -> varsayılanlar
        self.data["parallel_uploads"] = max(1, min(6, int(self.data.get("parallel_uploads", 3))))
        self.data["chunk_mb"] = max(1, min(64, int(self.data.get("chunk_mb", 8))))

    def save(self) -> None:
        with self._lock:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.path)

    def get(self, key: str):
        return self.data.get(key, DEFAULTS.get(key))

    def set(self, key: str, value) -> None:
        self.data[key] = value
        self.save()
