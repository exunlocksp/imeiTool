"""Cửa sổ About riêng (PySide6)."""

from __future__ import annotations

import webbrowser
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.app_branding import ZALO_CHAT_URL, app_icon_path, header_logo_path


def show_about_dialog(
    parent: Optional[QWidget],
    app_name: str,
    app_version: str,
    credits_text: str,
) -> None:
    dialog = QDialog(parent)
    dialog.setWindowTitle(f"Về {app_name}")
    dialog.setMinimumSize(440, 460)
    dialog.resize(500, 520)

    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(24, 20, 24, 18)
    layout.setSpacing(8)

    logo_path = header_logo_path() or app_icon_path()
    if logo_path is not None and logo_path.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
        pixmap = QPixmap(str(logo_path))
        if not pixmap.isNull():
            logo = QLabel()
            logo.setPixmap(
                pixmap.scaled(72, 72, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
            logo.setAlignment(Qt.AlignCenter)
            layout.addWidget(logo)

    title = QLabel(app_name)
    title.setStyleSheet("font-size: 22px; font-weight: bold;")
    title.setAlignment(Qt.AlignCenter)
    layout.addWidget(title)

    version = QLabel(f"Phiên bản {app_version}")
    version.setStyleSheet("font-size: 14px; color: gray;")
    version.setAlignment(Qt.AlignCenter)
    layout.addWidget(version)

    credits = QTextEdit()
    credits.setPlainText(credits_text.strip())
    credits.setReadOnly(True)
    layout.addWidget(credits, 1)

    footer = QLabel("© Taoden.vn · Exshop.vn")
    footer.setStyleSheet("font-size: 12px; color: gray;")
    footer.setAlignment(Qt.AlignCenter)
    layout.addWidget(footer)

    btn_row = QHBoxLayout()
    btn_row.addStretch(1)
    zalo = QPushButton("Chat Zalo")
    zalo.setStyleSheet(
        "QPushButton { background-color: #0068FF; color: white; padding: 6px 24px;"
        " border-radius: 6px; } QPushButton:hover { background-color: #0052CC; }"
    )
    zalo.clicked.connect(lambda: webbrowser.open(ZALO_CHAT_URL))
    btn_row.addWidget(zalo)
    btn_row.addStretch(1)
    layout.addLayout(btn_row)

    dialog.exec()
