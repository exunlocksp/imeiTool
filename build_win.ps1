# Build Windows: Pyarmor + PyInstaller -> dist\Taoden IMEI Tool\
# Usage:
#   .\build_win.ps1
#   .\build_win.ps1 -SkipPyarmor    # khi chua co pyarmor-regfile-*.zip
param(
    [switch]$SkipPyarmor,
    [switch]$ReuseObf
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "==> Clean build / dist / obf"
if ($ReuseObf -and (Test-Path "build\obf\main.py")) {
    if (Test-Path dist) { Remove-Item dist -Recurse -Force -ErrorAction SilentlyContinue }
    if (Test-Path .pyarmor) { Remove-Item .pyarmor -Recurse -Force -ErrorAction SilentlyContinue }
    Write-Host "    (giu build\obf — ReuseObf)"
} else {
    if (Test-Path build) { Remove-Item build -Recurse -Force -ErrorAction SilentlyContinue }
    if (Test-Path dist) { Remove-Item dist -Recurse -Force -ErrorAction SilentlyContinue }
    if (Test-Path .pyarmor) { Remove-Item .pyarmor -Recurse -Force -ErrorAction SilentlyContinue }
}

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
}
if (-not (Test-Path $python)) {
    throw "Khong tim thay Python. Tao .venv hoac cai Python 3.12+."
}

Write-Host "==> Dependencies"
& $python -m pip install -q -U pip
& $python -m pip install -q -r requirements.txt pyinstaller pyarmor pywin32

Write-Host "==> Logo / icon"
& $python scripts\generate_app_icon.py

Write-Host "==> OCR bundle (Tesseract)"
if (-not (Test-Path "tesseract\bin\tesseract.exe")) {
    & $python scripts\prepare_tesseract_bundle_win.py
    if ($LASTEXITCODE -ne 0) { throw "Tesseract bundle failed" }
}

Write-Host "==> Pyarmor obfuscate"
if ($SkipPyarmor) {
    Write-Host "    (bo qua -SkipPyarmor)"
    Remove-Item Env:PYARMOR_OBF_DIR -ErrorAction SilentlyContinue
} else {
    if ($ReuseObf) { $env:REUSE_OBF = "1" }
    & $python scripts\pyarmor_obfuscate.py
    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "Pyarmor that bai. Dat pyarmor-regfile-*.zip vao thu muc project roi chay lai."
        Write-Host "Hoac build tam khong ma hoa: .\build_win.ps1 -SkipPyarmor"
        exit $LASTEXITCODE
    }
    $env:PYARMOR_OBF_DIR = (Resolve-Path "build\obf").Path
}

Write-Host "==> PyInstaller"
& $python -m PyInstaller imei_tool.spec --noconfirm --clean
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

Write-Host "==> Huong dan PDF -> dist\"
& $python scripts\generate_user_guide_pdf.py
Copy-Item -Force docs\Huong-dan-su-dung.pdf dist\

$out = Join-Path $PSScriptRoot "dist\Taoden IMEI Tool"
if (-not (Test-Path $out)) {
    throw "Khong tim thay output: $out"
}

Write-Host ""
Write-Host "=============================================="
Write-Host "  Build xong: $out"
Write-Host "  Huong dan:  dist\Huong-dan-su-dung.pdf"
Write-Host "  Chay: .\dist\Taoden IMEI Tool\Taoden IMEI Tool.exe"
Write-Host "=============================================="
