"""Đặt tên app trên menu bar macOS (thay «Python») và hộp thoại About."""

from __future__ import annotations

import logging
import sys
import tkinter as tk
from typing import Callable, Optional

from src.about_dialog import show_about_dialog

logger = logging.getLogger(__name__)


def prime_macos_app_name(app_name: str) -> None:
    """Gọi trước khi import Tk — cập nhật CFBundleName nếu có PyObjC."""
    if sys.platform != "darwin":
        return
    try:
        from Foundation import NSBundle

        bundle = NSBundle.mainBundle()
        if not bundle:
            return
        info = bundle.localizedInfoDictionary() or bundle.infoDictionary()
        if info is not None:
            info["CFBundleName"] = app_name
            info["CFBundleDisplayName"] = app_name
    except Exception as exc:
        logger.debug("prime_macos_app_name: %s", exc)


def register_about_handler(
    root: tk.Misc,
    app_name: str,
    *,
    about_credits: str,
    app_version: str,
) -> Callable[[], None]:
    """Đăng ký tkAboutDialog và trả về callback cho menu apple."""
    credits = about_credits.strip()

    def _show_about() -> None:
        show_about_dialog(root, app_name, app_version, credits)

    for cmd in ("tkAboutDialog", "tk::mac::ShowAbout", "::tk::mac::ShowAbout"):
        try:
            root.createcommand(cmd, _show_about)
        except tk.TclError:
            continue

    root._taoden_show_about = _show_about  # type: ignore[attr-defined]
    return _show_about


def apply_macos_menu_branding(
    root: tk.Misc,
    app_name: str,
    *,
    quit_command: Optional[Callable[[], None]] = None,
) -> None:
    """Đổi tên menu ứng dụng và lệnh Quit."""
    if sys.platform != "darwin":
        return

    prime_macos_app_name(app_name)

    if quit_command is not None:
        for cmd in ("tk::mac::Quit", "::tk::mac::Quit"):
            try:
                root.createcommand(cmd, quit_command)
            except tk.TclError:
                continue

    def _rename_ns_menu() -> None:
        try:
            from AppKit import NSApp

            menu = NSApp().mainMenu()
            if menu is not None and menu.numberOfItems() > 0:
                menu.itemAtIndex_(0).setTitle_(app_name)
        except Exception as exc:
            logger.debug("NSApp mainMenu rename: %s", exc)

    root.after_idle(_rename_ns_menu)
