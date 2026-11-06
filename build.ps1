# Drive Yönetici - tek dosyalık DriveYonetici.exe derleme betiği
# Kullanım (PowerShell, proje klasöründe):   .\build.ps1          (testler + derleme)
#                                            .\build.ps1 -SkipTests
param([switch]$SkipTests)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$py = "python"
& $py --version
& $py -m pip install --disable-pip-version-check -q -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) {
    # Yönetici izni olmayan sistem Python'unda kullanıcı klasörüne kur
    & $py -m pip install --disable-pip-version-check -q --user -r requirements-dev.txt
    if ($LASTEXITCODE -ne 0) { throw "Bağımlılıklar kurulamadı" }
}

if (-not $SkipTests) {
    & $py -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw "Testler başarısız; derleme durduruldu" }
}

if (Test-Path build) { Remove-Item -Recurse -Force build }
if (Test-Path dist\DriveYonetici.exe) { Remove-Item -Force dist\DriveYonetici.exe }

# Güvenlik: credentials.json yanlışlıkla pakete girmesin
if (Test-Path credentials.json) { Write-Warning "credentials.json proje klasöründe; pakete EKLENMEYECEK." }

& $py -m PyInstaller --noconfirm --clean --onefile --windowed `
    --name DriveYonetici `
    --collect-data customtkinter `
    --collect-data googleapiclient `
    --hidden-import keyring.backends.Windows `
    --hidden-import win32ctypes.core `
    --add-data "KURULUM.md;." `
    --exclude-module pytest `
    main.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller başarısız" }

$exe = Join-Path $PSScriptRoot "dist\DriveYonetici.exe"
"{0}  ({1:N1} MB)" -f $exe, ((Get-Item $exe).Length / 1MB)
