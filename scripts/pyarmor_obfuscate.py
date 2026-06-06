#!/usr/bin/env python3
"""Mã hóa mã nguồn bằng Pyarmor (cần pyarmor-regfile-*.zip)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OBF_DIR = PROJECT_ROOT / "build" / "obf"


def _pyarmor_exe() -> str:
    scripts = Path(sys.executable).parent / "pyarmor.exe"
    if scripts.is_file():
        return str(scripts)
    return "pyarmor"


def _default_platform() -> str:
    if sys.platform == "win32":
        return "windows.x86_64"
    if sys.platform == "darwin":
        import platform

        return "darwin.arm64" if platform.machine() == "arm64" else "darwin.x86_64"
    return "linux.x86_64"


def _find_regfile() -> Path | None:
    matches = sorted(PROJECT_ROOT.glob("pyarmor-regfile*.zip"))
    return matches[0] if matches else None


def main() -> int:
    regfile = _find_regfile()
    pyarmor = _pyarmor_exe()
    if regfile is None:
        print(
            "ERROR: Missing pyarmor-regfile-*.zip in project root.\n"
            "\n"
            "First-time activation:\n"
            '  1. Save Pyarmor email attachment as pyarmor-regcode-9722.txt\n'
            '  2. pyarmor reg -p "Taoden IMEI Tool" pyarmor-regcode-9722.txt\n'
            "  3. Keep pyarmor-regfile-9722.zip for future builds:\n"
            "     pyarmor reg pyarmor-regfile-9722.zip",
            file=sys.stderr,
        )
        return 1

    platform = os.environ.get("PYARMOR_PLATFORM", _default_platform())
    print(f"==> Pyarmor register ({regfile.name})")
    subprocess.run([pyarmor, "reg", str(regfile)], check=True, cwd=str(PROJECT_ROOT))

    if OBF_DIR.exists():
        import shutil

        shutil.rmtree(OBF_DIR)
    OBF_DIR.mkdir(parents=True, exist_ok=True)

    print(f"==> Pyarmor gen -> {OBF_DIR} (platform: {platform})")
    subprocess.run(
        [
            pyarmor,
            "gen",
            "-O",
            str(OBF_DIR),
            "--platform",
            platform,
            "-r",
            "main.py",
            "src/",
        ],
        cwd=str(PROJECT_ROOT),
        check=True,
    )

    print(f"PYARMOR_OBF_DIR={OBF_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
