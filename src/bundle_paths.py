"""Paths for dev vs PyInstaller-frozen macOS bundle."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def bundle_root() -> Path:
    if is_frozen():
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent


def configure_tesseract() -> bool:
    """Point pytesseract at bundled Tesseract when running as a frozen app."""
    try:
        import pytesseract
    except ImportError:
        return False

    root = bundle_root()
    candidates = [
        root / "tesseract" / "bin" / "tesseract",
        root / "tesseract" / "tesseract",
        root / "bin" / "tesseract",
    ]
    for tess_bin in candidates:
        if tess_bin.is_file():
            pytesseract.pytesseract.tesseract_cmd = str(tess_bin)
            for data_dir in (
                root / "tesseract" / "share" / "tessdata",
                root / "tesseract" / "tessdata",
                root / "tessdata",
            ):
                if data_dir.is_dir():
                    os.environ["TESSDATA_PREFIX"] = str(data_dir)
                    break
            lib_dir = root / "tesseract" / "lib"
            if lib_dir.is_dir():
                prev = os.environ.get("DYLD_LIBRARY_PATH", "")
                os.environ["DYLD_LIBRARY_PATH"] = (
                    f"{lib_dir}{os.pathsep}{prev}" if prev else str(lib_dir)
                )
            return True
    return False
