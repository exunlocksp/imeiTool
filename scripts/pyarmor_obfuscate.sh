#!/bin/bash
# Mã hóa mã nguồn bằng Pyarmor (cần license đã kích hoạt).
# KHÔNG commit pyarmor-regcode*.txt / pyarmor-regfile-9722.zip lên git.
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ -z "${VIRTUAL_ENV:-}" ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

pip install -q -U pyarmor

REGFILE="pyarmor-regfile-9722.zip"
if [[ ! -f "$REGFILE" ]]; then
  echo "ERROR: Thiếu $REGFILE trong thư mục dự án." >&2
  echo "" >&2
  echo "Kích hoạt lần đầu (một lần, cần internet):" >&2
  echo "  1. Lưu file đính kèm email Pyarmor thành pyarmor-regcode-9722.txt" >&2
  echo "  2. pyarmor reg -p \"Taoden IMEI Tool\" pyarmor-regcode-9722.txt" >&2
  echo "  3. Sao lưu pyarmor-regfile-9722.zip — dùng file zip cho các lần sau:" >&2
  echo "     pyarmor reg pyarmor-regfile-9722.zip" >&2
  exit 1
fi

PLATFORM="${PYARMOR_PLATFORM:-darwin.arm64}"
case "$PLATFORM" in
  darwin.arm64|darwin.x86_64) ;;
  *)
    echo "ERROR: PYARMOR_PLATFORM không hợp lệ: $PLATFORM" >&2
    exit 1
    ;;
esac

echo "==> Pyarmor register (regfile)"
pyarmor reg "$REGFILE"

OBF_DIR="build/obf"
rm -rf "$OBF_DIR"
mkdir -p "$OBF_DIR"

echo "==> Pyarmor gen -> $OBF_DIR (platform: $PLATFORM)"
pyarmor gen -O "$OBF_DIR" --platform "$PLATFORM" -r main.py src/

export PYARMOR_OBF_DIR="$(pwd)/$OBF_DIR"
echo "PYARMOR_OBF_DIR=$PYARMOR_OBF_DIR"
