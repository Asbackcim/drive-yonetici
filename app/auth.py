"""Google hesapları: OAuth (installed-app / loopback) ve şifreli token saklama.

- Uygulama ASLA Google şifresi istemez; giriş tarayıcıda Google'ın kendi sayfasında yapılır.
- Refresh token yalnızca Windows Kimlik Bilgisi Yöneticisi'nde (keyring -> WinVault,
  kullanıcıya özel DPAPI şifrelemesi) tutulur. Diske düz metin token yazılmaz.
- hesaplar.json yalnızca e-posta ve görünen adı içerir.
"""
from __future__ import annotations

import json
import shutil
import threading
from datetime import datetime
from pathlib import Path

from . import paths
from .validation import ValidationError, validate_email

SCOPES = ["https://www.googleapis.com/auth/drive"]
KEYRING_SERVICE = "DriveYonetici"
TOKEN_URI = "https://oauth2.googleapis.com/token"


class TokenStore:
    """keyring tabanlı şifreli depo. Testlerde sahte bir sürümüyle değiştirilir."""

    def __init__(self):
        import keyring
        try:
            from keyring.backends.Windows import WinVaultKeyring
            keyring.set_keyring(WinVaultKeyring())
        except Exception:  # Windows dışı ortam: sistemin varsayılan güvenli deposu
            pass
        self._kr = keyring

    def save(self, email: str, refresh_token: str) -> None:
        self._kr.set_password(KEYRING_SERVICE, email, json.dumps({"refresh_token": refresh_token}))

    def load(self, email: str) -> str | None:
        raw = self._kr.get_password(KEYRING_SERVICE, email)
        if not raw:
            return None
        try:
            return json.loads(raw).get("refresh_token")
        except json.JSONDecodeError:
            return None

    def delete(self, email: str) -> None:
        try:
            self._kr.delete_password(KEYRING_SERVICE, email)
        except Exception:
            pass


class AuthError(Exception):
    pass


def read_client_config(path: Path) -> dict:
    """credentials.json'u doğrular; 'installed' (Masaüstü uygulaması) türünde olmalı."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise ValidationError("Seçilen dosya okunamadı ya da geçerli bir JSON değil.")
    if "web" in data and "installed" not in data:
        raise ValidationError("Bu dosya 'Web uygulaması' istemcisine ait. Lütfen OAuth istemcisini "
                              "'Masaüstü uygulaması' türünde oluşturun (KURULUM.md, Adım 5).")
    inst = data.get("installed")
    if not isinstance(inst, dict) or not inst.get("client_id") or not inst.get("client_secret"):
        raise ValidationError("Bu bir Google OAuth 'Masaüstü uygulaması' credentials.json dosyası değil.")
    if not str(inst["client_id"]).endswith(".apps.googleusercontent.com"):
        raise ValidationError("client_id beklenen biçimde değil.")
    return data


class AccountManager:
    def __init__(self, token_store: TokenStore | None = None, accounts_file: Path | None = None,
                 credentials_file: Path | None = None):
        self.store = token_store or TokenStore()
        self.accounts_file = accounts_file or paths.accounts_path()
        self.credentials_file = credentials_file or paths.credentials_path()
        self._lock = threading.Lock()
        self._clients: dict = {}

    # ---- istemci yapılandırması -------------------------------------------
    def has_client_config(self) -> bool:
        if not self.credentials_file.exists():
            return False
        try:
            read_client_config(self.credentials_file)
            return True
        except ValidationError:
            return False

    def install_client_config(self, src: str | Path) -> None:
        read_client_config(Path(src))
        shutil.copyfile(src, self.credentials_file)

    def _client(self) -> dict:
        return read_client_config(self.credentials_file)["installed"]

    # ---- hesap listesi ------------------------------------------------------
    def list_accounts(self) -> list[dict]:
        if not self.accounts_file.exists():
            return []
        try:
            data = json.loads(self.accounts_file.read_text(encoding="utf-8"))
            return [a for a in data if isinstance(a, dict) and a.get("email")]
        except (OSError, json.JSONDecodeError):
            return []

    def _write_accounts(self, accounts: list[dict]) -> None:
        tmp = self.accounts_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(accounts, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.accounts_file)

    def _register(self, email: str, display_name: str, refresh_token: str) -> None:
        email = validate_email(email)
        with self._lock:
            self.store.save(email, refresh_token)
            accounts = [a for a in self.list_accounts() if a["email"] != email]
            accounts.append({"email": email, "display_name": display_name,
                             "added_at": datetime.now().isoformat(timespec="seconds")})
            accounts.sort(key=lambda a: a["email"])
            self._write_accounts(accounts)
            self._clients.pop(email, None)

    # ---- OAuth --------------------------------------------------------------
    def add_account_interactive(self) -> str:
        """Tarayıcıda Google giriş sayfasını açar (loopback akışı). Eklenen e-postayı döndürür."""
        from google_auth_oauthlib.flow import InstalledAppFlow

        if not self.has_client_config():
            raise AuthError("Önce Kurulum ekranından credentials.json dosyasını seçin.")
        flow = InstalledAppFlow.from_client_secrets_file(str(self.credentials_file), scopes=SCOPES)
        creds = flow.run_local_server(
            host="localhost", port=0, open_browser=True, access_type="offline", prompt="consent select_account",
            authorization_prompt_message="", success_message=(
                "Drive Yönetici hesabınıza bağlandı. Bu sekmeyi kapatıp uygulamaya dönebilirsiniz."),
            timeout_seconds=300)
        if not creds.refresh_token:
            raise AuthError("Google yenileme anahtarı vermedi. Hesabı Google hesabınızın 'Üçüncü taraf "
                            "erişimi' sayfasından kaldırıp tekrar ekleyin.")
        from .drive_client import DriveClient
        user = DriveClient(creds).about().get("user", {})
        email = user.get("emailAddress")
        if not email:
            raise AuthError("Hesabın e-posta adresi alınamadı.")
        self._register(email, user.get("displayName", ""), creds.refresh_token)
        return validate_email(email)

    def credentials(self, email: str):
        from google.oauth2.credentials import Credentials

        rt = self.store.load(email)
        if not rt:
            raise AuthError(f"{email} için kayıtlı oturum yok. Hesabı yeniden ekleyin.")
        c = self._client()
        return Credentials(token=None, refresh_token=rt, client_id=c["client_id"],
                           client_secret=c["client_secret"], token_uri=c.get("token_uri", TOKEN_URI),
                           scopes=SCOPES)

    def client_for(self, email: str):
        from .drive_client import DriveClient

        with self._lock:
            if email not in self._clients:
                self._clients[email] = DriveClient(self.credentials(email), email=email)
            return self._clients[email]

    def remove_account(self, email: str, revoke: bool = True) -> None:
        """Hesabı çıkarır: token Windows deposundan silinir (isteğe bağlı Google'da iptal edilir)."""
        email = validate_email(email)
        rt = self.store.load(email)
        if revoke and rt:
            try:
                import requests
                requests.post("https://oauth2.googleapis.com/revoke", data={"token": rt}, timeout=10)
            except Exception:
                pass  # çevrimdışıysa yerel silme yine yapılır
        with self._lock:
            self.store.delete(email)
            self._write_accounts([a for a in self.list_accounts() if a["email"] != email])
            self._clients.pop(email, None)
