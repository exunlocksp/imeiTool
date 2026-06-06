#!/usr/bin/env python3
"""Taoden IMEI Tool — entry point."""

import multiprocessing
import sys
from pathlib import Path

# PyInstaller one-file: ensure project root is importable when frozen.
if getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(sys._MEIPASS)))  # type: ignore[attr-defined]
else:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.app_branding import APP_NAME  # noqa: E402

if sys.platform == "darwin":
    from src.macos_menu import prime_macos_app_name  # noqa: E402

    prime_macos_app_name(APP_NAME)

from src.gui import run_app  # noqa: E402

def _log_fatal(exc: BaseException) -> None:
    import traceback
    from datetime import datetime

    lines = [
        f"=== Taoden IMEI Tool crash {datetime.now().isoformat()} ===",
        "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
    ]
    text = "\n".join(lines)
    for path in (
        Path.home() / "Library" / "Logs" / "IMEI-Tool-crash.log",
        Path.cwd() / "IMEI-Tool-crash.log",
    ):
        try:
            path.write_text(text, encoding="utf-8")
            break
        except OSError:
            continue


if __name__ == "__main__":
    multiprocessing.freeze_support()
    try:
        run_app()
    except Exception as exc:
        if getattr(sys, "frozen", False):
            _log_fatal(exc)
        raise
