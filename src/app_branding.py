"""Tên app và đường dẫn logo."""

from __future__ import annotations

import sys
from pathlib import Path

APP_NAME = "Taoden IMEI Tool"
APP_SHORT_NAME = "Taoden IMEI"
APP_VERSION = "1.0"
BUNDLE_ID = "com.taoden.imeitool"
ZALO_CHAT_URL = "https://zalo.me/0967609909"

ABOUT_CREDITS = """Mini Tool từ Taoden.vn - Exshop.vn
Chuyên phân phối chính hãng rẻ nhất toàn quốc :
- Bison - Enerziger : Pin iPhone iPad AirPod, Sim ghép, cốc cáp sạc, sạc dự phòng
- Sim ghép, mạch độ sim, CNC.
Chuyên các dịch vụ
- Unlock các dòng điện thoại, mở khoá iCloud
- Check thông tin các dòng điện thoại
- Sửa chữa mọi loại điện thoại."""

ABOUT_MESSAGE = f"{APP_NAME}\nPhiên bản {APP_VERSION}\n{ABOUT_CREDITS}"


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def assets_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "assets"  # type: ignore[attr-defined]
    return _project_root() / "assets"


def app_icon_path() -> Path | None:
    for name in ("AppIcon.icns", "logo_128.png", "icon_1024.png"):
        path = assets_dir() / name
        if path.is_file():
            return path
    return None


def header_logo_path() -> Path | None:
    for name in ("logo_64.png", "logo_48.png", "logo_128.png"):
        path = assets_dir() / name
        if path.is_file():
            return path
    return None
