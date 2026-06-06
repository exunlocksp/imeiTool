#!/usr/bin/env python3
"""Copy Tesseract + tessdata + Homebrew dylibs for PyInstaller bundling."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT = PROJECT_ROOT / "build" / "tesseract_bundle"


def _run(cmd: list[str]) -> str:
    return subprocess.check_output(cmd, text=True).strip()


def _find_tessdata(tesseract_prefix: Path) -> Path:
    candidates: list[Path] = []
    lang_prefix = _brew_prefix("tesseract-lang")
    if lang_prefix:
        candidates.append(lang_prefix / "share" / "tessdata")
    for path in (
        Path("/opt/homebrew/share/tessdata"),
        Path("/usr/local/share/tessdata"),
        tesseract_prefix / "share" / "tessdata",
    ):
        candidates.append(path)
    for path in candidates:
        if path.is_dir() and len(list(path.glob("*.traineddata"))) >= 3:
            return path
    return tesseract_prefix / "share" / "tessdata"


def _brew_prefix(pkg: str) -> Path | None:
    try:
        return Path(_run(["brew", "--prefix", pkg]))
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def _copy_dylibs(binary: Path, lib_dir: Path) -> None:
    lib_dir.mkdir(parents=True, exist_ok=True)
    try:
        deps = _run(["otool", "-L", str(binary)]).splitlines()[1:]
    except (subprocess.CalledProcessError, FileNotFoundError):
        return

    copied: set[str] = set()
    for line in deps:
        part = line.strip().split(" ", 1)[0]
        if not part.startswith("/"):
            continue
        src = Path(part)
        if not src.is_file() or str(src) in copied:
            continue
        if "/usr/lib/" in str(src) or "/System/" in str(src):
            continue
        dest = lib_dir / src.name
        if not dest.exists():
            shutil.copy2(src, dest)
            copied.add(str(src))
            _copy_dylibs(dest, lib_dir)


def main() -> int:
    tess_bin = shutil.which("tesseract")
    prefix = _brew_prefix("tesseract")

    if not tess_bin and prefix:
        candidate = prefix / "bin" / "tesseract"
        if candidate.is_file():
            tess_bin = str(candidate)

    if not tess_bin:
        print(
            "ERROR: Không tìm thấy Tesseract.\n"
            "  brew install tesseract tesseract-lang",
            file=sys.stderr,
        )
        return 1

    tess_bin_path = Path(tess_bin)
    if prefix is None:
        prefix = tess_bin_path.parent.parent

    tessdata = _find_tessdata(prefix)
    if not tessdata.is_dir():
        print(f"ERROR: Không có tessdata", file=sys.stderr)
        return 1

    # Chỉ nhúng ngôn ngữ cần cho màn Cài đặt (giữ app nhẹ)
    keep_langs = {"eng", "vie", "osd"}

    if OUT.exists():
        shutil.rmtree(OUT)

    bin_out = OUT / "bin"
    data_out = OUT / "share" / "tessdata"
    lib_out = OUT / "lib"
    bin_out.mkdir(parents=True)
    data_out.mkdir(parents=True)

    shutil.copy2(tess_bin_path, bin_out / "tesseract")
    _copy_dylibs(bin_out / "tesseract", lib_out)

    search_dirs = [tessdata, prefix / "share" / "tessdata", Path("/usr/local/share/tessdata")]
    opt_home = Path("/opt/homebrew/share/tessdata")
    if opt_home.is_dir():
        search_dirs.append(opt_home)

    copied: list[str] = []
    for lang in sorted(keep_langs):
        for directory in search_dirs:
            src = directory / f"{lang}.traineddata"
            if src.is_file():
                shutil.copy2(src, data_out / src.name)
                copied.append(lang)
                break
        else:
            print(f"WARNING: missing {lang}.traineddata", file=sys.stderr)

    print(f"OK: bundled Tesseract → {OUT}")
    print(f"     langs: {', '.join(copied)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
