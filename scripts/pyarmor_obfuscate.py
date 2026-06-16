#!/usr/bin/env python3
"""Mã hóa mã nguồn bằng Pyarmor (cần pyarmor-regfile-*.zip + internet)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OBF_DIR = PROJECT_ROOT / "build" / "obf"

# Toàn bộ app — basic license không hỗ trợ --private/--restrict.
OBF_TARGETS = ("main.py", "src/")


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


def _run(cmd: list[str], *, cwd: Path) -> None:
    try:
        subprocess.run(cmd, check=True, cwd=str(cwd))
    except subprocess.CalledProcessError as exc:
        if exc.returncode == 2:
            print(
                "\nGợi ý: license Pyarmor basic cần **internet** khi obfuscate.\n"
                "  - Kiểm tra mạng / firewall\n"
                "  - pyarmor reg pyarmor-regfile-9722.zip\n"
                "  - Thử lại: python scripts/pyarmor_obfuscate.py\n"
                "  - Build tạm không obfuscate: SKIP_PYARMOR=1 ./build_mac.sh\n",
                file=sys.stderr,
            )
        raise


def obfuscate(*, platform: str | None = None, reuse: bool = False) -> Path:
    regfile = _find_regfile()
    pyarmor = _pyarmor_exe()
    if regfile is None:
        raise FileNotFoundError(
            "Thiếu pyarmor-regfile-*.zip trong thư mục dự án.\n"
            "Kích hoạt lần đầu: pyarmor reg -p \"Taoden IMEI Tool\" pyarmor-regcode-9722.txt"
        )

    plat = platform or os.environ.get("PYARMOR_PLATFORM", _default_platform())

    if reuse and (OBF_DIR / "main.py").is_file():
        runtime = next(OBF_DIR.glob("pyarmor_runtime_*"), None)
        if runtime is not None:
            print(f"==> Dùng lại obf có sẵn: {OBF_DIR} (REUSE_OBF=1)")
            return OBF_DIR

    print(f"==> Pyarmor register ({regfile.name})")
    _run([pyarmor, "reg", str(regfile)], cwd=PROJECT_ROOT)

    if OBF_DIR.exists():
        shutil.rmtree(OBF_DIR)
    OBF_DIR.mkdir(parents=True, exist_ok=True)

    print(f"==> Pyarmor gen -> {OBF_DIR} (platform: {plat})")
    cmd = [
        pyarmor,
        "gen",
        "-O",
        str(OBF_DIR),
        "--platform",
        plat,
        "-r",
        *OBF_TARGETS,
    ]
    _run(cmd, cwd=PROJECT_ROOT)
    print(f"PYARMOR_OBF_DIR={OBF_DIR}")
    return OBF_DIR


def main() -> int:
    reuse = os.environ.get("REUSE_OBF", "").strip() in ("1", "true", "yes")
    try:
        obfuscate(reuse=reuse)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
