# Drive Yönetici - Kurulum Rehberi

Bu rehber **bir kez** yapılır, yaklaşık 10-15 dakika sürer. Sonunda bilgisayarınıza
`credentials.json` adlı küçük bir dosya inecek ve onu uygulamaya göstereceksiniz.

> **Neden bu kadar adım var?** Drive Yönetici bir şirketin sunucusuna bağlanmaz. Google
> hesabınıza, **sizin** Google Cloud projenizde **sizin** oluşturduğunuz bir anahtar ile
> erişir. Böylece verileriniz yalnızca sizin bilgisayarınız ile Google arasında kalır.
> Şifreniz bu uygulamaya hiçbir zaman yazılmaz; giriş her zaman Google'ın kendi sayfasında yapılır.

Google Cloud Console arayüzü zaman zaman değişir ve diliniz Türkçe ise menü adları
çevrilmiş görünebilir. Aşağıda her adımda **İngilizce ekran metni** ve yanında
(parantez içinde) Türkçe karşılığı verilmiştir.

---

## Adım 1 - Proje oluşturun

1. Tarayıcıda **https://console.cloud.google.com** adresine gidin ve yedeklemek
   istediğiniz Gmail hesaplarından **biriyle** giriş yapın.
2. İlk kez giriyorsanız hizmet şartlarını kabul edin (ülke: Türkiye).
3. Sayfanın üstündeki proje seçiciye tıklayın (*"Select a project"* / *"Proje seçin"*).
4. Açılan pencerede sağ üstteki **"NEW PROJECT"** (*"YENİ PROJE"*) düğmesine basın.
5. **Project name** (*Proje adı*) alanına `Drive Yonetici` yazın.
   *Location* (*Konum*) alanını **No organization** olarak bırakın.
6. **"CREATE"** (*"OLUŞTUR"*) düğmesine basın. Birkaç saniye sonra bildirim gelir;
   **"SELECT PROJECT"** (*"PROJE SEÇ"*) ile projeye geçin.

## Adım 2 - Google Drive API'yi etkinleştirin

1. Üstteki arama kutusuna `Google Drive API` yazın ve sonuçlardan **Google Drive API**'yi seçin.
2. **"ENABLE"** (*"ETKİNLEŞTİR"*) düğmesine basın.

## Adım 3 - OAuth izin ekranını ayarlayın

1. Sol menüden **APIs & Services → OAuth consent screen**
   (*API'ler ve Hizmetler → OAuth izin ekranı*) yolunu izleyin. Yeni arayüzde bu sayfa
   **Google Auth Platform** adıyla açılır.
2. **"GET STARTED"** (*"BAŞLAYIN"*) düğmesine basın.
3. **App Information** (*Uygulama bilgileri*):
   - **App name** (*Uygulama adı*): `Drive Yönetici`
   - **User support email** (*Kullanıcı destek e-postası*): kendi Gmail adresiniz
   - **"NEXT"** (*"İLERİ"*)
4. **Audience** (*Kitle*): **External** (*Harici*) seçin → **"NEXT"**.
   (Gmail hesapları için "Internal / Dahili" seçeneği kullanılamaz.)
5. **Contact Information** (*İletişim bilgileri*): kendi e-postanızı yazın → **"NEXT"**.
6. **Finish** (*Bitir*): Google API Hizmetleri Kullanıcı Verileri Politikası'nı kabul eden
   kutuyu işaretleyin → **"CONTINUE"** → **"CREATE"** (*"OLUŞTUR"*).

### Test kullanıcılarını ekleyin (önemli)

Uygulamanız **"Testing"** (*"Test"*) modunda kalacak. Bu modda yalnızca sizin eklediğiniz
Gmail adresleri giriş yapabilir - bu, güvenlik için istediğimiz şey.

1. Sol menüden **Audience** (*Kitle*) sayfasını açın.
2. **Publishing status** (*Yayınlama durumu*) değerinin **Testing** olduğunu doğrulayın.
   **"PUBLISH APP"** düğmesine **basmayın**.
3. **Test users** (*Test kullanıcıları*) bölümünde **"+ ADD USERS"** (*"+ KULLANICI EKLE"*)
   düğmesine basın.
4. Drive Yönetici'ye ekleyeceğiniz **tüm Gmail adreslerini** (ör. `ali@gmail.com`,
   `ali.is@gmail.com`) her satıra bir tane olacak şekilde yazın → **"SAVE"** (*"KAYDET"*).

> Bir Gmail adresini burada eklemeyi unutursanız, o hesapla giriş yaparken
> *"Access blocked: Drive Yönetici has not completed the Google verification process"*
> (*Erişim engellendi*) hatası alırsınız. Çözüm: adresi buraya ekleyip tekrar deneyin.

## Adım 4 - (İsteğe bağlı) Drive iznini listeye ekleyin

Test modunda bu adım zorunlu değildir; uygulama izni giriş sırasında zaten ister.
Yine de görmek isterseniz: **Data Access** (*Veri erişimi*) → **"ADD OR REMOVE SCOPES"**
→ listede `.../auth/drive` satırını işaretleyin → **"UPDATE"** → **"SAVE"**.

## Adım 5 - "Masaüstü uygulaması" OAuth istemcisi oluşturun

1. Sol menüden **Clients** (*İstemciler*) sayfasını açın
   (eski arayüzde: **APIs & Services → Credentials → + CREATE CREDENTIALS → OAuth client ID**).
2. **"+ CREATE CLIENT"** (*"+ İSTEMCİ OLUŞTUR"*) düğmesine basın.
3. **Application type** (*Uygulama türü*) listesinden **Desktop app**
   (*Masaüstü uygulaması*) seçin. **"Web application" seçmeyin** - uygulama bunu reddeder.
4. **Name** (*Ad*): `Drive Yonetici Masaustu` → **"CREATE"** (*"OLUŞTUR"*).
5. Açılan pencerede **"DOWNLOAD JSON"** (*"JSON'U İNDİR"*) bağlantısına tıklayın.
   (Pencereyi kapattıysanız: istemci listesinde satırın sonundaki indirme simgesine basın.)
6. İnen dosyanın adı `client_secret_XXXX.apps.googleusercontent.com.json` gibidir.
   İsterseniz adını `credentials.json` yapın (zorunlu değil).

> **Bu dosyayı kimseyle paylaşmayın, e-postayla göndermeyin, GitHub'a yüklemeyin.**
> Drive Yönetici dosyanın bir kopyasını yalnızca sizin kullanıcı klasörünüze
> (`%APPDATA%\DriveYonetici`) kaydeder.

## Adım 6 - Uygulamaya tanıtın

1. `DriveYonetici.exe`'yi çalıştırın. İlk açılışta **Kurulum** ekranı gelir.
2. **"credentials.json dosyasını seç"** düğmesine basıp az önce indirdiğiniz dosyayı seçin.
   *"Anahtar dosyası kaydedildi"* mesajını görmelisiniz.

> Windows SmartScreen *"Windows bilgisayarınızı korudu"* uyarısı gösterirse: bu, imzasız
> ve yeni derlenmiş her programda çıkar. **"Ek bilgi" → "Yine de çalıştır"** seçin.

## Adım 7 - Hesap ekleyin (her Gmail için tekrarlayın)

1. Sol menüde **"Hesap ekle"** düğmesine basın. Varsayılan tarayıcınızda Google giriş sayfası açılır.
2. Eklemek istediğiniz hesabı seçin / giriş yapın.
3. *"Google hasn't verified this app"* (*"Google bu uygulamayı doğrulamadı"*) uyarısı gelir.
   Bu normaldir; uygulamayı siz oluşturdunuz. **"Advanced"** (*"Gelişmiş"*) →
   **"Go to Drive Yönetici (unsafe)"** (*"Drive Yönetici'ye git (güvenli değil)"*) seçin.
4. İzin ekranında *"See, edit, create, and delete all of your Google Drive files"*
   (*"Google Drive dosyalarınızın tümünü görme, düzenleme, oluşturma ve silme"*) kutusunu
   **işaretleyin** → **"Continue"** (*"Devam"*).
5. Tarayıcıda *"Drive Yönetici hesabınıza bağlandı"* yazısını görünce sekmeyi kapatıp
   uygulamaya dönün. Hesap sol menüde listelenir.
6. Diğer Gmail hesaplarınız için 1-5. adımları tekrarlayın.

---

## Neden "tüm Drive" izni (`auth/drive`) gerekiyor?

Google'ın daha dar bir izni (`drive.file`) vardır, ama o izinle uygulama **yalnızca kendi
oluşturduğu dosyaları** görebilir. Drive Yönetici'nin işleri ise sizin **mevcut** dosyalarınız üzerinde:

| Özellik | Neden geniş izin gerekir |
|---|---|
| Kopya dosya bulucu | Drive'daki tüm dosyaların içerik özetini (md5) okuması gerekir |
| Büyük/eski dosyalar | Tüm dosyaların boyut ve tarihlerini listeler |
| Türüne göre ayırma | Var olan dosyaları klasörler arasında taşır |
| Hesaplar arası taşıma | Seçtiğiniz dosyayı diğer hesapla geçici olarak paylaşır ve kopyalatır |
| Bilgisayar yedeği | Dosya yükler, değişenleri aynı dosyanın yeni sürümü yapar |

Uygulamanın kendi kuralları: **kalıcı silme yapmaz** (silinecek her şey Drive çöp kutusuna
gider, 30 gün geri alınabilir), her toplu değişiklikten önce **önizleme** gösterir ve
sizin onayınızı bekler, her işlemi **günlüğe** yazar ve **"Son işlemi geri al"** sunar.

## Bilmeniz gerekenler

- **7 günlük oturum:** Uygulama "Testing" modunda olduğu için Google, giriş izinlerini
  **7 günde bir** sona erdirir. Uygulama bunu fark ettiğinde *"Bu hesabın oturumu sona ermiş"*
  der; sol menüden **"Hesap ekle"** ile aynı hesabı yeniden eklemeniz yeterlidir
  (yedek geçmişi ve ayarlar kaybolmaz).
- **Hesabı çıkarmak:** Sol menüde hesabı seçip **"Çıkar"** deyin. Bilgisayardaki oturum
  anahtarı silinir ve Google'daki erişim iptal edilir. Drive'daki dosyalara dokunulmaz.
  Ayrıca istediğiniz zaman **https://myaccount.google.com/permissions** adresinden
  "Drive Yönetici" erişimini kaldırabilirsiniz.
- **Oturum anahtarları nerede?** Windows'un **Kimlik Bilgileri Yöneticisi**'nde
  (*Denetim Masası → Kimlik Bilgileri Yöneticisi → Windows Kimlik Bilgileri*,
  `DriveYonetici` adıyla), Windows oturumunuza bağlı olarak şifreli saklanır.
  Diskte düz metin token dosyası yoktur.
- **Uygulama verileri:** `%APPDATA%\DriveYonetici` klasöründe: ayarlar, hesap listesi
  (yalnızca e-postalar), yedek durum veritabanı, işlem günlüğü ve hata kaydı.
