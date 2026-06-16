"""Hộp thoại Cài đặt — cột bảng, mục in, simlock (PySide6)."""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.app_settings import (
    PRINT_FIELD_KEYS,
    PRINT_FIELD_LABELS,
    SIMLOCK_PRINT_LABELS,
    TABLE_COLUMN_KEYS,
    TABLE_COLUMN_LABELS,
    AppSettings,
)
from src.theme import mark_primary


def _section_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet("font-size: 15px; font-weight: bold;")
    return label


def _hint_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet("color: gray;")
    label.setWordWrap(True)
    return label


def _check_frame() -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setFrameShape(QFrame.StyledPanel)
    frame.setProperty("card", True)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(12, 8, 12, 8)
    layout.setSpacing(4)
    return frame, layout


class SettingsDialog(QDialog):
    def __init__(
        self,
        parent: Optional[QWidget],
        settings: AppSettings,
        on_save: Callable[[AppSettings], None],
    ) -> None:
        super().__init__(parent)
        self._on_save = on_save
        self._table_checks: dict[str, QCheckBox] = {}
        self._print_checks: dict[str, QCheckBox] = {}

        self.setWindowTitle("Cài đặt")
        self.setMinimumSize(420, 480)
        self.resize(480, 600)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(8)

        layout.addWidget(_section_label("Bảng"))
        layout.addWidget(_hint_label("Cột được tick sẽ hiển thị trên bảng."))
        table_frame, table_layout = _check_frame()
        for key in TABLE_COLUMN_KEYS:
            check = QCheckBox(TABLE_COLUMN_LABELS[key])
            check.setChecked(settings.table_columns.get(key, True))
            self._table_checks[key] = check
            table_layout.addWidget(check)
        layout.addWidget(table_frame)

        layout.addWidget(_section_label("In"))
        layout.addWidget(
            _hint_label(
                "Mục được tick sẽ in trên nhãn "
                "(Màu · Dung lượng một dòng; Ngoại hình riêng trên barcode)."
            )
        )
        print_frame, print_layout = _check_frame()
        for key in PRINT_FIELD_KEYS:
            check = QCheckBox(PRINT_FIELD_LABELS[key])
            check.setChecked(settings.print_fields.get(key, True))
            self._print_checks[key] = check
            print_layout.addWidget(check)
        layout.addWidget(print_frame)

        simlock_hint = " · ".join(
            f"{api} → {label}" for api, label in SIMLOCK_PRINT_LABELS.items()
        )
        layout.addWidget(_hint_label(f"In Simlock: {simlock_hint}"))

        layout.addWidget(_section_label("Simlock"))
        simlock_frame, simlock_layout = _check_frame()
        self._auto_simlock_check = QCheckBox("Tự động Check Simlock khi cắm USB")
        self._auto_simlock_check.setChecked(settings.auto_check_simlock)
        simlock_layout.addWidget(self._auto_simlock_check)
        simlock_layout.addWidget(
            _hint_label(
                "Bật: mỗi lần cắm USB sẽ tự gửi check Lock/Unlocked "
                "(giữ kết quả khi rút cáp)."
            )
        )
        layout.addWidget(simlock_frame)

        layout.addStretch(1)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        actions = QHBoxLayout()
        actions.addStretch(1)
        save_btn = QPushButton("Lưu")
        mark_primary(save_btn)
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._save)
        actions.addWidget(save_btn)
        cancel_btn = QPushButton("Hủy")
        cancel_btn.clicked.connect(self.reject)
        actions.addWidget(cancel_btn)
        root.addLayout(actions)

    def _save(self) -> None:
        settings = AppSettings(
            table_columns={key: check.isChecked() for key, check in self._table_checks.items()},
            print_fields={key: check.isChecked() for key, check in self._print_checks.items()},
            auto_check_simlock=self._auto_simlock_check.isChecked(),
        )
        if not settings.visible_table_columns():
            QMessageBox.warning(
                self, "Cài đặt", "Phải chọn ít nhất một cột hiển thị trên bảng."
            )
            return
        if not settings.has_print_content():
            QMessageBox.warning(self, "Cài đặt", "Phải chọn ít nhất một mục in.")
            return
        try:
            settings.save()
        except OSError as exc:
            QMessageBox.critical(self, "Cài đặt", f"Không lưu được cài đặt:\n{exc}")
            return
        self._on_save(settings)
        self.accept()


def open_settings_dialog(
    parent: Optional[QWidget],
    settings: AppSettings,
    on_save: Callable[[AppSettings], None],
) -> None:
    SettingsDialog(parent, settings, on_save).exec()
