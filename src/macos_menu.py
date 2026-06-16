"""Đặt tên app trên menu bar macOS (thay «Python») khi chạy từ source."""

from __future__ import annotations

import logging
import sys

logger = logging.getLogger(__name__)


def prime_macos_app_name(app_name: str) -> None:
    """Cập nhật CFBundleName nếu có PyObjC — gọi trước khi tạo QApplication."""
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
