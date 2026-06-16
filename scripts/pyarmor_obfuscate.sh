#!/bin/bash
# Mã hóa mã nguồn bằng Pyarmor (cần pyarmor-regfile-*.zip + internet).
# KHÔNG commit pyarmor-regcode*.txt / pyarmor-regfile-*.zip lên git.
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ -z "${VIRTUAL_ENV:-}" ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

pip install -q -U pyarmor

export PYARMOR_PLATFORM="${PYARMOR_PLATFORM:-darwin.arm64}"
case "$PYARMOR_PLATFORM" in
  darwin.arm64|darwin.x86_64|windows.x86_64|linux.x86_64) ;;
  *)
    echo "ERROR: PYARMOR_PLATFORM không hợp lệ: $PYARMOR_PLATFORM" >&2
    exit 1
    ;;
esac

python scripts/pyarmor_obfuscate.py
