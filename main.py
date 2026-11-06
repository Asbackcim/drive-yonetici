"""Drive Yönetici giriş noktası."""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler


def setup_logging() -> None:
    from app import paths

    handler = RotatingFileHandler(paths.log_file_path(), maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(threadName)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    # API istek gövdeleri/token'lar loglanmasın
    for noisy in ("googleapiclient.discovery", "google_auth_httplib2", "urllib3", "google.auth"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def main() -> int:
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # keskin yazı tipleri
    except Exception:
        pass
    setup_logging()
    from app.ui.main_window import MainWindow

    app = MainWindow()
    if "--smoke-test" in sys.argv:  # derleme doğrulaması: pencereyi açıp 3 sn sonra kapat
        app.after(3000, app.destroy)
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
