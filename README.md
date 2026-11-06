# Drive Yönetici

Windows 11 için Türkçe arayüzlü masaüstü uygulaması: birden fazla Google hesabını tek yerden
yönetir, bilgisayar yedeği alır, Drive'daki kopyaları / büyük-eski dosyaları bulur, dağınık
dosyaları türüne göre klasörler ve hesaplar arasında dosya kopyalar/taşır.

İlk kurulum için: **[KURULUM.md](KURULUM.md)**

## Hızlı başlangıç (geliştirici)

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q          # birim testleri (Drive API sahte/mock)
python main.py               # uygulamayı kaynak koddan çalıştır
.\build.ps1                  # testler + dist\DriveYonetici.exe
```

## Teknoloji seçimi ve gerekçesi

**Python 3.11+ (3.14 ile derlendi) + CustomTkinter + google-api-python-client + PyInstaller.**

- Google'ın resmi Python istemcisi; resumable upload, `MediaUpload` uzantı noktası ve
  `google-auth-oauthlib` loopback OAuth akışı hazır ve olgun.
- CustomTkinter, Windows'ta yerel Tk üzerinde çalışır: WebView2/Chromium gerektirmez,
  exe ~30 MB civarında kalır, açık/koyu tema desteği yerleşiktir. Tablolar için `ttk.Treeview`
  tema renklerine uyarlanmıştır.
- Tauri/Electron değerlendirildi: Node kurulu olsa da Tauri için Rust araç zinciri gerekir,
  Electron ise ~150 MB paket + ayrı bir Drive SDK katmanı demek. Bu makinede tek komutla
  (`build.ps1`) derlenebilen en küçük ve en sağlam yol Python yığınıydı.
- İkonlar Lucide çizgi stilinde, Pillow ile koddan çizilir (harici varlık dosyası yok).

## Mimari

```
main.py                 giriş, log yapılandırması (%APPDATA%\DriveYonetici\uygulama.log)
app/
  auth.py               OAuth (InstalledAppFlow.run_local_server), hesap listesi, keyring token deposu
  drive_client.py       Drive v3 sarmalayıcı; iş parçacığı başına httplib2; delete YOK, yalnız trashed=true
  retry.py              403 rate-limit / 429 / 5xx için üstel geri çekilme + titreşim
  backup.py             tarama, artımlı karar, SQLite durum, resumable + paralel yükleme, ilerleme/ETA
  excludes.py           dışlama desenleri (ad, joker, yol deseni)
  duplicates.py         md5Checksum ile kopya gruplama + "korunacak" önerisi
  largeold.py           boyut/yaş filtreleri
  categorize.py         tür kuralları, taşıma planı, alan dağılımı
  operations.py         önizleme satırları + uygulama (günlüğe yazarak)
  transfer.py           hesaplar arası kopya/taşıma (sunucu tarafı kopya + akış yedeği)
  journal.py            SQLite işlem günlüğü + "Son işlemi geri al"
  validation.py         yol / ad / uzantı / desen / e-posta doğrulama
  ui/                   CustomTkinter arayüzü (sayfalar, tablo, önizleme penceresi, grafik)
tests/                  pytest; Drive tamamen sahte (FakeDrive / MagicMock)
```

Uzun işler `TaskRunner` ile ayrı iş parçacığında çalışır; sonuç ve ilerleme bir kuyruk
üzerinden `after()` ile ana döngüye taşınır, arayüz donmaz.

## Güvenlik kuralları nasıl uygulanıyor

| Kural | Uygulama |
|---|---|
| Şifre yazılmaz | Giriş tarayıcıda Google sayfasında (loopback `localhost:<rastgele port>`) |
| Token şifreli | Refresh token yalnız Windows Kimlik Bilgisi Yöneticisi'nde (keyring → WinVault, DPAPI). `hesaplar.json` yalnız e-posta içerir (testle doğrulanır) |
| Hesap çıkarma | Token keyring'den silinir + Google'da `revoke` edilir |
| Kalıcı silme yok | `DriveClient`'ta `files.delete`/`emptyTrash` hiç yoktur; "sil" = `files.update(trashed=true)` |
| Önizlemesiz işlem yok | Kopya temizliği, büyük dosya temizliği, türe göre ayırma, hesaplar arası taşıma: hepsi `PreviewDialog` onayından geçer |
| Geri alma | Her toplu işlem bir parti olarak günlüğe yazılır; geri alma adımları ters sırayla tersine çevirir |
| Sır yok | Kaynakta anahtar/secret yok; `credentials.json` kullanıcı tarafından seçilir, `%APPDATA%`'ya kopyalanır, `.gitignore`'da |
| Backoff | 429, 5xx, 403 `rateLimitExceeded/userRateLimitExceeded` → 1,2,4..64 sn + rastgele |
| Girdi doğrulama | Yedek klasörü (mutlak, var, sürücü kökü/sistem klasörü değil), Drive adları, uzantılar, desenler, e-posta, Drive kimlikleri |

## Bilgisayar yedeği - tasarım

- **Konum:** Seçili hesabın `Drive'ım/Bilgisayar Yedeği - GG.AA.YYYY/<kaynak klasör adı>/...`
- **Yedek seti:** İlk çalıştırmada tarihli klasör oluşturulur ve bir "set" olarak kaydedilir.
  Sonraki çalıştırmalar aynı seti seçerek yalnızca farkları gönderir. İstenirse "Yeni yedek seti"
  ile yeni tarihli bir tam yedek başlatılır.
- **Artımlı karar:** kayıt yok → yeni; boyut farklı → değişti; boyut+mtime aynı → atla (dosya okunmaz);
  yalnız mtime farklı → yerel md5 hesaplanır, Drive'ın md5'iyle aynıysa yalnızca kayıt güncellenir.
  Değişen dosya, Drive'daki **aynı dosyanın yeni sürümü** olarak yüklenir (`files.update`), eski sürüm silinmez.
- **Resumable:** 5 MB üstü dosyalar 8 MB parçalarla; oturum adresi SQLite'a yazılır. Uygulama kapanır ya da
  bağlantı koparsa bir sonraki çalıştırmada sunucuya "kaç bayt aldın?" sorulup kalan baytlardan devam edilir.
  Oturum süresi dolmuşsa (404/410) dosya baştan gönderilir.
- **Paralellik:** 1-6 (varsayılan 3) eşzamanlı dosya; iş kuyruğu sınırlı tutulur (milyonlarca dosya için bellek sabit).
- **100+ GB:** tarama üreteçtir ve dışlanan klasörlere hiç inmez; durum SQLite (WAL) dosyasında;
  ilerleme 15 sn'lik kayan pencereyle hız ve kalan süre hesaplar.
- **Kota:** Analiz sırasında `about.storageQuota` okunur; yer yetmiyorsa uyarı verilir ve onay istenir.
- Yükleme sırasında değişen dosya kaydedilmez, bir sonraki çalıştırmada tekrar gönderilir.
- Kilitli/okunamayan dosyalar atlanır ve özetle bildirilir.

## Hesaplar arası kopyalama - yöntem seçimi

**Birincil: paylaşım + sunucu tarafı `files.copy`.** Kaynak hesap öğeyi hedef hesaba bildirimsiz
"Görüntüleyen" olarak paylaşır, hedef hesap klasör yapısını kendi Drive'ında kurup her dosyayı
`files.copy` ile kopyalar, paylaşım `finally` bloğunda kaldırılır.

Neden: veri Google sunucuları arasında kopyalanır - bilgisayara inmez, ev internetinin yükleme
hızına bağlı değildir (100 GB'lık bir klasörde saatler yerine dakikalar), Google Dokümanlar /
E-Tablolar dönüştürülmeden kopyalanır ve kopyanın sahibi hedef hesap olur.

**Yedek: akış halinde indir-yükle.** `files.copy` başarısız olursa (ör. sahibi kopyalamayı
kısıtlamışsa) dosya kaynaktan `alt=media` ile parça parça indirilir ve aynı anda hedefe resumable
upload ile yüklenir (`StreamingUpload`, bellekte en fazla ~1 parça; diske hiç yazılmaz).

**Taşıma** = kopyalama + kopyalama hatasız biterse kaynağın çöp kutusuna taşınması. Geri alma
kopyaları çöpe taşır ve kaynağı çöpten geri getirir.

## Testler

```
python -m pytest -q
```

Kapsam: dışlama desenleri, kategori sınıflandırma ve kural doğrulama, kopya gruplama ve korunacak
önerisi, büyük/eski filtreleri, artımlı yedek karar mantığı (md5'in yalnızca gerektiğinde
hesaplandığı dahil), tarama + durum DB döngüsü, yükleme motoru (sahte Drive ile yeni/atla/güncelle),
kaydedilmiş resumable oturumdan devam, kota kontrolü, ilerleme/ETA, önizlemenin yan etkisiz olması,
günlük + geri alma (taşıma, çöp, klasör oluşturma, kısmi hata), hesaplar arası kopya/taşıma ve
paylaşımın her durumda kaldırılması, akış tamponu, üstel geri çekilme, token'ların düz dosyaya
yazılmaması, yol doğrulama. Gerçek Google'a hiçbir istek atılmaz; testler kullanıcı klasörlerine
dokunmaz (geçici sahte klasörler ve `DRIVE_YONETICI_HOME` yönlendirmesi kullanılır).

## Bilinen sınırlamalar

- OAuth uygulaması "Testing" modunda olduğundan Google oturumları 7 günde bir sona erer
  (uygulama bunu algılayıp hesabı yeniden eklemenizi ister). Kalıcı oturum için uygulamanın Google
  doğrulamasından geçmesi gerekir; `auth/drive` kısıtlı kapsam olduğu için bu kişisel kullanımda pratik değildir.
- Yedekleme yalnızca ekler/günceller; bilgisayarda silinen dosyalar Drive'daki yedekten silinmez (bilinçli tercih).
- Paylaşılan Drive'lar (Shared Drives) ve "Benimle paylaşılanlar" kopya/büyük dosya taramasına dahil edilmez
  (yalnızca sahibi olduğunuz dosyalar).
- Akış yöntemiyle Google yerel türleri (Doküman/E-Tablo) aktarılamaz; bunlar yalnızca sunucu tarafı kopyayla aktarılır.
- Exe imzasız olduğundan ilk açılışta Windows SmartScreen uyarısı çıkabilir.
