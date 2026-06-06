#!/usr/bin/env python3
"""Download and bundle Tesseract OCR for Windows (portable, no system install)."""

from __future__ import annotations

import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT = PROJECT_ROOT / "tesseract"
STAGING = PROJECT_ROOT / "build" / "_tesseract_extract"

INSTALLER_URL = (
    "https://github.com/UB-Mannheim/tesseract/releases/download/"
    "v5.4.0.20240606/tesseract-ocr-w64-setup-5.4.0.20240606.exe"
)
TESSDATA_BASE = "https://github.com/tesseract-ocr/tessdata/raw/main"
KEEP_LANGS = ("eng", "vie", "osd")
SEVEN_ZIP_CANDIDATES = (
    Path(r"C:\Program Files\7-Zip\7z.exe"),
    Path(r"C:\Program Files (x86)\7-Zip\7z.exe"),
)


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  download {url}")
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=600) as response, dest.open("wb") as out:
        shutil.copyfileobj(response, out)


def _find_7z() -> Path | None:
    for candidate in SEVEN_ZIP_CANDIDATES:
        if candidate.is_file():
            return candidate
    return shutil.which("7z") and Path(shutil.which("7z") or "")


def _extract_installer(installer: Path, target: Path, seven_zip: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    print(f"  extract to {target}")
    subprocess.run(
        [str(seven_zip), "x", str(installer), f"-o{target}", "-y"],
        check=True,
        timeout=600,
    )
    if not (target / "tesseract.exe").is_file():
        raise RuntimeError("tesseract.exe not found after extraction")


def _copy_bundle(src_dir: Path, out: Path) -> None:
    bin_out = out / "bin"
    data_out = out / "share" / "tessdata"
    if out.exists():
        shutil.rmtree(out)
    bin_out.mkdir(parents=True)
    data_out.mkdir(parents=True)

    shutil.copy2(src_dir / "tesseract.exe", bin_out / "tesseract.exe")
    for dll in src_dir.glob("*.dll"):
        shutil.copy2(dll, bin_out / dll.name)

    src_data = src_dir / "tessdata"
    if src_data.is_dir():
        for item in src_data.glob("*.traineddata"):
            shutil.copy2(item, data_out / item.name)

    for lang in KEEP_LANGS:
        dest = data_out / f"{lang}.traineddata"
        if dest.is_file():
            continue
        _download(f"{TESSDATA_BASE}/{lang}.traineddata", dest)


def main() -> int:
    if sys.platform != "win32":
        print("This script is for Windows only.", file=sys.stderr)
        return 1

    seven_zip = _find_7z()
    if seven_zip is None:
        print(
            "ERROR: Can not find 7-Zip (7z.exe).\n"
            "  Install from https://www.7-zip.org/ then run again.",
            file=sys.stderr,
        )
        return 1

    cache = PROJECT_ROOT / "build" / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    installer = cache / Path(INSTALLER_URL).name

    print("==> Tesseract OCR for Windows -> tesseract/")
    if not installer.is_file():
        _download(INSTALLER_URL, installer)

    _extract_installer(installer, STAGING, seven_zip)
    _copy_bundle(STAGING, OUT)
    shutil.rmtree(STAGING, ignore_errors=True)

    langs = sorted(p.stem for p in (OUT / "share" / "tessdata").glob("*.traineddata"))
    print(f"OK: {OUT}")
    print(f"     languages: {', '.join(langs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
