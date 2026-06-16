"""Hộp thoại chọn cột xuất Text / Excel."""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.export_common import EXPORT_FIELD_KEYS, EXPORT_FIELD_LABELS
from src.theme import mark_primary


class ExportFieldsDialog(QDialog):
    def __init__(self, parent: Optional[QWidget], *, title: str) -> None:
        super().__init__(parent)
        self._checks: dict[str, QCheckBox] = {}

        self.setWindowTitle(title)
        self.setMinimumSize(360, 420)
        self.resize(400, 480)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        hint = QLabel("Chọn mục cần xuất — mỗi dòng thiết bị chỉ gồm các mục đã tick.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray;")
        root.addWidget(hint)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(4)

        frame = QFrame()
        frame.setFrameShape(QFrame.StyledPanel)
        frame.setProperty("card", True)
        checks_layout = QVBoxLayout(frame)
        checks_layout.setContentsMargins(12, 8, 12, 8)
        checks_layout.setSpacing(4)

        for key in EXPORT_FIELD_KEYS:
            check = QCheckBox(EXPORT_FIELD_LABELS[key])
            check.setChecked(True)
            self._checks[key] = check
            checks_layout.addWidget(check)

        layout.addWidget(frame)
        scroll.setWidget(body)
        root.addWidget(scroll, stretch=1)

        quick = QHBoxLayout()
        select_all = QPushButton("Chọn tất cả")
        select_all.clicked.connect(self._select_all)
        quick.addWidget(select_all)
        clear_all = QPushButton("Bỏ chọn")
        clear_all.clicked.connect(self._clear_all)
        quick.addWidget(clear_all)
        quick.addStretch()
        root.addLayout(quick)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        mark_primary(buttons.button(QDialogButtonBox.Ok))
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _select_all(self) -> None:
        for check in self._checks.values():
            check.setChecked(True)

    def _clear_all(self) -> None:
        for check in self._checks.values():
            check.setChecked(False)

    def _accept(self) -> None:
        if not self.selected_fields():
            QMessageBox.warning(self, self.windowTitle(), "Tick ít nhất một mục cần xuất.")
            return
        self.accept()

    def selected_fields(self) -> list[str]:
        return [key for key in EXPORT_FIELD_KEYS if self._checks[key].isChecked()]


def pick_export_fields(parent: Optional[QWidget], *, title: str) -> Optional[list[str]]:
    dialog = ExportFieldsDialog(parent, title=title)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return dialog.selected_fields()
