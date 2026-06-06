#!/bin/bash
# Build macOS (Pyarmor + PyInstaller): dist/Taoden IMEI Tool.app
#
# Mặc định: clean toàn bộ → pyarmor → đóng gói
#
#   ./build_mac.sh                    — Apple Silicon (arm64)
#   TARGET_ARCH=x86_64 ./build_mac.sh — Mac Intel
#   BUILD_ALL=1 ./build_mac.sh        — cả arm64 + Intel (2 file .app trong dist/)
#
#   SKIP_CLEAN=1 ./build_mac.sh       — bỏ bước clean (khi BUILD_ALL lần 2)
set -euo pipefail
export HOMEBREW_NO_AUTO_UPDATE=1
cd "$(dirname "$0")"

if [[ "${BUILD_ALL:-0}" == "1" && "${SKIP_CLEAN:-0}" != "1" ]]; then
  echo "==> BUILD_ALL=1 — build arm64 rồi Intel"
  BUILD_ALL=0 SKIP_CLEAN=0 TARGET_ARCH=arm64 "$0"
  STASH="dist/.Taoden-IMEI-Tool-arm64.app"
  rm -rf "$STASH"
  mv "dist/Taoden IMEI Tool.app" "$STASH"
  BUILD_ALL=0 SKIP_CLEAN=1 TARGET_ARCH=x86_64 "$0"
  mv "$STASH" "dist/Taoden IMEI Tool.app"
  echo ""
  echo "=============================================="
  echo "  Xong cả hai bản trong dist/:"
  echo "    dist/Taoden IMEI Tool.app       (arm64)"
  echo "    dist/Taoden IMEI Tool Intel.app (x86_64)"
  echo "=============================================="
  exit 0
fi

TARGET_ARCH="${TARGET_ARCH:-arm64}"
export TARGET_ARCH
case "$TARGET_ARCH" in
  arm64)
    VENV_DIR=".venv"
    VENV_CREATE=(python3 -m venv .venv)
    export PYARMOR_PLATFORM=darwin.arm64
    APP_SUFFIX=""
    PYTHON=(python)
    PIP=(pip)
    ;;
  x86_64)
    VENV_DIR=".venv-x86"
    VENV_CREATE=(arch -x86_64 python3 -m venv .venv-x86)
    export PYARMOR_PLATFORM=darwin.x86_64
    APP_SUFFIX=" Intel"
    PYTHON=(arch -x86_64 python)
    PIP=(arch -x86_64 pip)
    ;;
  *)
    echo "ERROR: TARGET_ARCH phải là arm64 hoặc x86_64 (hiện tại: $TARGET_ARCH)" >&2
    exit 1
    ;;
esac

if [[ "${SKIP_CLEAN:-0}" == "1" ]]; then
  echo "==> Bỏ clean (SKIP_CLEAN=1)"
else
  echo "==> Clean build / dist / pyarmor"
  chmod -R u+w build dist 2>/dev/null || true
  rm -rf build dist .pyarmor build/obf
fi

echo "==> Kiến trúc: $TARGET_ARCH"

echo "==> Python venv ($VENV_DIR)"
if [[ ! -d "$VENV_DIR" ]]; then
  "${VENV_CREATE[@]}"
fi
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

echo "==> Dependencies"
"${PIP[@]}" install -q -r requirements.txt pyinstaller pyarmor

echo "==> Logo / icon"
"${PYTHON[@]}" scripts/generate_app_icon.py

echo "==> OCR: macOS Vision (có sẵn trên hệ thống, không nhúng Tesseract)"
"${PIP[@]}" install -q 'ocrmac>=1.0.0'
rm -rf build/tesseract_bundle
if [[ "${BUNDLE_TESSERACT:-0}" == "1" ]]; then
  echo "    BUNDLE_TESSERACT=1 — nhúng thêm Tesseract dự phòng..."
  if ! command -v tesseract &>/dev/null && command -v brew &>/dev/null; then
    brew install tesseract tesseract-lang
  fi
  if command -v tesseract &>/dev/null; then
    "${PYTHON[@]}" scripts/prepare_tesseract_bundle.py
  fi
fi

echo "==> Pyarmor obfuscate"
bash scripts/pyarmor_obfuscate.sh
export PYARMOR_OBF_DIR="$(pwd)/build/obf"

echo "==> PyInstaller"
"${PYTHON[@]}" -m PyInstaller imei_tool.spec --noconfirm --clean

APP="dist/Taoden IMEI Tool${APP_SUFFIX}.app"
BUILT="dist/Taoden IMEI Tool.app"
if [[ -d "$BUILT" && -n "$APP_SUFFIX" ]]; then
  rm -rf "$APP"
  mv "$BUILT" "$APP"
fi
if [[ -d "$APP" ]]; then
  rm -f "dist/Taoden IMEI Tool" 2>/dev/null || true
  echo ""
  echo "=============================================="
  echo "  Build xong: $APP"
  echo "  Mở: open \"$APP\""
  echo "=============================================="
  echo ""
  echo "Kiến trúc: $TARGET_ARCH | Pyarmor + PyInstaller | macOS 11+"
  echo "Lần đầu mở: Chuột phải → Open (Gatekeeper)."
  echo "Nếu lỗi: xem ~/Library/Logs/IMEI-Tool-crash.log"
  echo "USB: cần usbmuxd (có sẵn trên macOS / brew install libimobiledevice)."
else
  echo "ERROR: Không tìm thấy $APP" >&2
  exit 1
fi
