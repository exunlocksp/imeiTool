"""Theme tối Táo Đen — đồng bộ màu với website (style.css)."""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

BG = "#0f1420"
BG_DEEP = "#0a0e17"
BG_CARD = "#121826"
BG_ELEVATED = "#1a2234"
BG_HOVER = "#232e45"
BORDER = "#243044"
TEXT = "#e6ebf5"
TEXT_MUTED = "#9fb0c9"
PRIMARY = "#3b8ed0"
PRIMARY_HOVER = "#2d7ab8"
ACCENT = "#22c55e"
WARNING = "#facc15"
DANGER = "#ef5350"

SIMLOCK_COLORS = {
    "Unlocked": ACCENT,
    "Locked": DANGER,
}

_QSS = f"""
QWidget {{
    color: {TEXT};
    font-size: 13px;
}}
QMainWindow, QDialog {{
    background-color: {BG};
}}

/* ---------- Bảng ---------- */
QTableWidget {{
    background-color: {BG_CARD};
    alternate-background-color: #151c2b;
    gridline-color: #1d2638;
    border: 1px solid {BORDER};
    border-radius: 8px;
    selection-background-color: {PRIMARY};
    selection-color: #ffffff;
    show-decoration-selected: 0;
}}
QTableWidget::item {{
    padding: 2px 6px;
}}
QHeaderView::section {{
    background-color: {BG_DEEP};
    color: {TEXT_MUTED};
    font-weight: bold;
    border: none;
    border-bottom: 2px solid {PRIMARY};
    padding: 7px 8px;
}}
QTableCornerButton::section {{
    background-color: {BG_DEEP};
    border: none;
}}
QTableWidget::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid #3a4a66;
    border-radius: 4px;
    background-color: {BG_CARD};
}}
QTableWidget::indicator:checked {{
    background-color: {PRIMARY};
    border-color: {PRIMARY};
}}

/* ---------- Nút ---------- */
QPushButton {{
    background-color: {BG_ELEVATED};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 6px 16px;
}}
QPushButton:hover {{
    background-color: {BG_HOVER};
}}
QPushButton:pressed {{
    background-color: {BG_CARD};
}}
QPushButton:disabled {{
    color: #56627a;
    background-color: {BG_CARD};
}}
QPushButton[primary="true"] {{
    background-color: {PRIMARY};
    border: none;
    color: #ffffff;
    font-weight: bold;
}}
QPushButton[primary="true"]:hover {{
    background-color: {PRIMARY_HOVER};
}}
QPushButton[primary="true"]:disabled {{
    background-color: {BG_ELEVATED};
    color: #56627a;
}}

/* ---------- Ô nhập ---------- */
QLineEdit, QPlainTextEdit, QTextEdit {{
    background-color: {BG_CARD};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 6px 8px;
    selection-background-color: {PRIMARY};
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{
    border-color: {PRIMARY};
}}

/* ---------- Khung / card ---------- */
QLabel {{
    background: transparent;
}}
QFrame[card="true"] {{
    background-color: {BG_CARD};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}
QScrollArea {{
    border: none;
    background: transparent;
}}
QScrollArea > QWidget > QWidget {{
    background: transparent;
}}
QScrollArea[card="true"] {{
    background-color: {BG_CARD};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}
QSplitter::handle {{
    background: transparent;
}}

/* ---------- Checkbox ---------- */
QCheckBox {{
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid #3a4a66;
    border-radius: 4px;
    background-color: {BG_CARD};
}}
QCheckBox::indicator:checked {{
    background-color: {PRIMARY};
    border-color: {PRIMARY};
}}
QCheckBox::indicator:hover {{
    border-color: {PRIMARY};
}}

/* ---------- Menu, status bar ---------- */
QMenu {{
    background-color: {BG_ELEVATED};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 4px;
}}
QMenu::item {{
    padding: 5px 24px 5px 12px;
    border-radius: 4px;
}}
QMenu::item:selected {{
    background-color: {PRIMARY};
    color: #ffffff;
}}
QStatusBar {{
    background-color: {BG_DEEP};
    border-top: 1px solid {BORDER};
}}
QStatusBar::item {{
    border: none;
}}

/* ---------- Scrollbar ---------- */
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: #2c3a55;
    border-radius: 4px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: #3a4a66;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: #2c3a55;
    border-radius: 4px;
    min-width: 30px;
}}
QScrollBar::handle:horizontal:hover {{
    background: #3a4a66;
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    width: 0;
    height: 0;
}}
QScrollBar::add-page, QScrollBar::sub-page {{
    background: transparent;
}}

/* ---------- MessageBox ---------- */
QMessageBox {{
    background-color: {BG_ELEVATED};
}}
"""


def apply_theme(app: QApplication) -> None:
    """Fusion + palette tối + QSS thương hiệu — gọi ngay sau khi tạo QApplication."""
    app.setStyle("Fusion")

    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(BG))
    palette.setColor(QPalette.WindowText, QColor(TEXT))
    palette.setColor(QPalette.Base, QColor(BG_CARD))
    palette.setColor(QPalette.AlternateBase, QColor("#151c2b"))
    palette.setColor(QPalette.Text, QColor(TEXT))
    palette.setColor(QPalette.PlaceholderText, QColor("#56627a"))
    palette.setColor(QPalette.Button, QColor(BG_ELEVATED))
    palette.setColor(QPalette.ButtonText, QColor(TEXT))
    palette.setColor(QPalette.Highlight, QColor(PRIMARY))
    palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ToolTipBase, QColor(BG_ELEVATED))
    palette.setColor(QPalette.ToolTipText, QColor(TEXT))
    palette.setColor(QPalette.Link, QColor(PRIMARY))
    app.setPalette(palette)

    app.setStyleSheet(_QSS)


def mark_primary(button) -> None:
    """Đánh dấu nút hành động chính (nền xanh thương hiệu)."""
    button.setProperty("primary", True)
