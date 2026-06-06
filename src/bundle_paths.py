"""Paths for dev vs PyInstaller-frozen bundle (Tesseract OCR)."""

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


def _tesseract_roots() -> list[Path]:
    project = Path(__file__).resolve().parent.parent
    roots: list[Path] = []
    seen: set[Path] = set()

    def add(path: Path) -> None:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            roots.append(resolved)

    add(bundle_root())
    if not is_frozen():
        add(project / "tesseract")
        add(project / "build" / "tesseract_bundle")
    return roots


def _tesseract_bin_names() -> tuple[str, ...]:
    if sys.platform == "win32":
        return ("tesseract.exe", "tesseract")
    return ("tesseract",)


def _tessdata_dirs(root: Path, bin_dir: Path) -> tuple[Path, ...]:
    return (
        root / "tesseract" / "share" / "tessdata",
        root / "tesseract" / "tessdata",
        root / "share" / "tessdata",
        root / "tessdata",
        bin_dir / "tessdata",
    )


def configure_tesseract() -> bool:
    """Point pytesseract at bundled Tesseract (dev copy or PyInstaller bundle)."""
    try:
        import pytesseract
    except ImportError:
        return False

    for root in _tesseract_roots():
        for name in _tesseract_bin_names():
            for rel in ("bin", ""):
                tess_bin = root / rel / name if rel else root / name
                if not tess_bin.is_file():
                    continue

                bin_dir = tess_bin.parent
                pytesseract.pytesseract.tesseract_cmd = str(tess_bin)

                for data_dir in _tessdata_dirs(root, bin_dir):
                    if data_dir.is_dir() and any(data_dir.glob("*.traineddata")):
                        # Tesseract expects TESSDATA_PREFIX = folder containing *.traineddata
                        os.environ["TESSDATA_PREFIX"] = str(data_dir)
                        break

                if sys.platform == "win32":
                    prev = os.environ.get("PATH", "")
                    if str(bin_dir) not in prev.split(os.pathsep):
                        os.environ["PATH"] = f"{bin_dir}{os.pathsep}{prev}"
                elif sys.platform == "darwin":
                    lib_dir = root / "tesseract" / "lib"
                    if not lib_dir.is_dir():
                        lib_dir = root / "lib"
                    if lib_dir.is_dir():
                        prev = os.environ.get("DYLD_LIBRARY_PATH", "")
                        os.environ["DYLD_LIBRARY_PATH"] = (
                            f"{lib_dir}{os.pathsep}{prev}" if prev else str(lib_dir)
                        )
                return True
    return False
