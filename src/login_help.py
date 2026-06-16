"""Hướng dẫn đăng nhập app và lấy API token từ website (PySide6)."""

from __future__ import annotations

import os
import urllib.parse
import webbrowser

from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.app_branding import ZALO_CHAT_URL

LOGIN_GUIDE_LINES = (
    "Cách nhanh: bấm «Đăng nhập bằng trình duyệt» → Google → app tự nhận token.",
    "",
    "Hoặc nhập tay (mã kích hoạt từ web /tai-khoan):",
    "1. Đăng nhập Google trên website.",
    "2. Copy email + mã kích hoạt → nhập vào app.",
    "",
    "Quản lý thiết bị: mỗi máy = 1 token Sanctum. Hết slot → thu hồi trên web hoặc liên hệ admin.",
    "",
    "Gửi IMEI/dịch vụ có phí cần VNĐ > 0. Chưa có tài khoản — chat Zalo.",
)


def web_base_from_api_url(api_base_url: str) -> str:
    url = (api_base_url or "").strip().rstrip("/")
    if not url:
        return os.environ.get("TAODEN_WEB_URL", "https://tool.taoden.vn").rstrip("/")

    parsed = urllib.parse.urlparse(url)
    path = parsed.path.rstrip("/")
    for suffix in ("/api/v1", "/api"):
        if path.endswith(suffix):
            path = path[: -len(suffix)]
            break

    return urllib.parse.urlunparse(
        (parsed.scheme or "https", parsed.netloc, path or "", "", "", "")
    ).rstrip("/")


def login_page_url(api_base_url: str = "") -> str:
    return f"{web_base_from_api_url(api_base_url)}/dang-nhap"


def account_page_url(api_base_url: str = "") -> str:
    return f"{web_base_from_api_url(api_base_url)}/tai-khoan"


def account_devices_page_url(api_base_url: str = "") -> str:
    return f"{web_base_from_api_url(api_base_url)}/tai-khoan/quan-ly-thiet-bi"


def account_ips_page_url(api_base_url: str = "") -> str:
    return account_devices_page_url(api_base_url)


def open_login_page(api_base_url: str = "") -> None:
    webbrowser.open(login_page_url(api_base_url))


def open_account_page(api_base_url: str = "") -> None:
    webbrowser.open(account_page_url(api_base_url))


def open_account_devices_page(api_base_url: str = "") -> None:
    webbrowser.open(account_devices_page_url(api_base_url))


def open_account_ips_page(api_base_url: str = "") -> None:
    open_account_devices_page(api_base_url)


def build_login_guide(
    *,
    api_base_url: str = "",
    title: str = "Cách lấy API token",
) -> QWidget:
    frame = QFrame()
    frame.setFrameShape(QFrame.StyledPanel)
    frame.setProperty("card", True)

    layout = QVBoxLayout(frame)
    layout.setContentsMargins(12, 10, 12, 10)
    layout.setSpacing(6)

    title_label = QLabel(title)
    title_label.setStyleSheet("font-size: 13px; font-weight: bold;")
    layout.addWidget(title_label)

    guide = QLabel("\n".join(LOGIN_GUIDE_LINES))
    guide.setStyleSheet("font-size: 12px; color: gray;")
    guide.setWordWrap(True)
    layout.addWidget(guide)

    links = QHBoxLayout()
    links.setSpacing(6)

    login_btn = QPushButton("Mở trang đăng nhập")
    login_btn.clicked.connect(lambda: open_login_page(api_base_url))
    links.addWidget(login_btn)

    account_btn = QPushButton("Mở trang tài khoản")
    account_btn.clicked.connect(lambda: open_account_page(api_base_url))
    links.addWidget(account_btn)

    zalo_btn = QPushButton("Chat Zalo")
    zalo_btn.setStyleSheet(
        "QPushButton { background-color: #0068FF; color: white; border-radius: 4px;"
        " padding: 4px 12px; } QPushButton:hover { background-color: #0052CC; }"
    )
    zalo_btn.clicked.connect(lambda: webbrowser.open(ZALO_CHAT_URL))
    links.addWidget(zalo_btn)

    links.addStretch(1)
    layout.addLayout(links)
    return frame
