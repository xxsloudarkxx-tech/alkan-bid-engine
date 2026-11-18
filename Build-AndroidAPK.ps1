$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$MobileDir = Join-Path $Root "mobile_app"
$TargetApk = Join-Path $Root "ALKAN-BidEngine-v1.0.0.apk"

if (-not (Get-Command flutter -ErrorAction SilentlyContinue)) {
    Write-Host "Flutter SDK no esta instalado en esta maquina." -ForegroundColor Yellow
    Write-Host "Instala Flutter + Android SDK en Windows ejecutando:" -ForegroundColor Cyan
    Write-Host "  winget install -e --id Google.Flutter" -ForegroundColor White
    Write-Host "O sube este repositorio a GitHub: el workflow .github/workflows/build-android-apk.yml genera el .apk automaticamente en la nube." -ForegroundColor Cyan
    exit 1
}

Push-Location $MobileDir
try {
    flutter pub get
    flutter build apk --release
    $BuiltApk = Join-Path $MobileDir "build\app\outputs\flutter-apk\app-release.apk"
    if (-not (Test-Path $BuiltApk)) {
        throw "No se encontro el APK compilado en $BuiltApk"
    }
    Copy-Item -Path $BuiltApk -Destination $TargetApk -Force
    Write-Host "APK listo en: $TargetApk" -ForegroundColor Green
} finally {
    Pop-Location
}
