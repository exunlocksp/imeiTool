"""Hộp thoại Check Lock Quốc Tế Miễn Phí (PySide6)."""

from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.api_client import SimlockQuotaResult, fetch_simlock_quota
from src.api_config import load_api_config
from src.theme import mark_primary

logger = logging.getLogger(__name__)

OnCheckFn = Callable[[], None]
PostToMainFn = Callable[[Callable[[], None]], None]

REQUIREMENTS_NOTE = (
    "Ghi chú: Mỗi dòng cần IMEI 1, Serial Number và IMEI 2 (nếu máy có). "
    "Thiếu IMEI 1 hoặc Serial sẽ bỏ qua dòng đó."
)
QUOTA_HINT_OK = (
    "Kết quả không xác định không trừ lượt. "
    "Hết lượt → dùng dịch vụ Check tốn phí (Dịch vụ khác) hoặc liên hệ admin để tăng hạn mức."
)
QUOTA_HINT_EXCEEDED = (
    "Đã hết lượt check miễn phí. Vui lòng dùng dịch vụ có phí "
    "(menu Dịch vụ → Dịch vụ khác) hoặc liên hệ admin để tăng hạn mức."
)


class _QuotaBridge(QObject):
    loaded = Signal(object)


class FreeSimlockDialog(QDialog):
    def __init__(
        self,
        parent: Optional[QWidget],
        *,
        on_check_checked: OnCheckFn,
        on_check_all: OnCheckFn,
        post_to_main: Optional[PostToMainFn] = None,
    ) -> None:
        super().__init__(parent)
        self._on_check_checked = on_check_checked
        self._on_check_all = on_check_all
        self._post_to_main = post_to_main
        self._quota: Optional[SimlockQuotaResult] = None
        self._quota_loading = False

        self.setWindowTitle("Check Lock Quốc Tế Miễn Phí")
        self.setMinimumSize(440, 340)
        self.resize(500, 400)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        title = QLabel("Check Lock Quốc Tế Miễn Phí")
        title.setStyleSheet("font-size: 15px; font-weight: bold;")
        root.addWidget(title)

        # intro = QLabel(
        #     "Kiểm tra simlock (Lock / Quốc tế) qua Apple Albert — "
        #     "không trừ VNĐ. Mỗi kết quả Locked/Unlocked tính 1 lượt check free."
        # )
        # intro.setWordWrap(True)
        # intro.setStyleSheet("color: gray; font-size: 12px;")
        # root.addWidget(intro)

        requirements = QLabel(REQUIREMENTS_NOTE)
        requirements.setWordWrap(True)
        requirements.setStyleSheet("font-size: 12px; color: #1565C0;")
        root.addWidget(requirements)

        quota_row = QHBoxLayout()
        quota_row.setSpacing(8)
        self._quota_label = QLabel("Đang tải hạn mức từ server…")
        self._quota_label.setWordWrap(True)
        self._quota_label.setStyleSheet("font-size: 13px;")
        quota_row.addWidget(self._quota_label, 1)
        self._refresh_quota_btn = QPushButton("Làm mới")
        self._refresh_quota_btn.setFixedHeight(28)
        self._refresh_quota_btn.clicked.connect(self._load_quota)
        quota_row.addWidget(self._refresh_quota_btn, 0)
        root.addLayout(quota_row)

        self._hint_label = QLabel()
        self._hint_label.setWordWrap(True)
        self._hint_label.setStyleSheet("color: gray; font-size: 12px;")
        root.addWidget(self._hint_label)

        root.addStretch(1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)

        self._check_checked_btn = QPushButton("Check đã tick")
        self._check_checked_btn.clicked.connect(self._run_checked)
        btn_row.addWidget(self._check_checked_btn)

        self._check_all_btn = QPushButton("Check tất cả")
        self._check_all_btn.clicked.connect(self._run_all)
        btn_row.addWidget(self._check_all_btn)

        close_btn = QPushButton("Đóng")
        close_btn.clicked.connect(self.reject)
        btn_row.addWidget(close_btn)

        root.addLayout(btn_row)

        mark_primary(self._check_checked_btn)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._load_quota()

    def _set_loading(self, loading: bool) -> None:
        self._quota_loading = loading
        self._refresh_quota_btn.setEnabled(not loading)
        quota = self._quota
        busy = loading or quota is None or not quota.ok or quota.simlock_remaining <= 0
        self._check_checked_btn.setEnabled(not busy)
        self._check_all_btn.setEnabled(not busy)

    def _load_quota(self) -> None:
        if self._quota_loading:
            return

        self._quota_label.setText("Đang tải hạn mức từ server…")
        self._quota_label.setStyleSheet("font-size: 13px; color: gray;")
        self._hint_label.clear()
        self._set_loading(True)

        if not load_api_config().enabled:
            self._apply_quota(
                SimlockQuotaResult(
                    ok=False,
                    message="Chưa cấu hình email và API token (Cài đặt → Tài khoản API).",
                )
            )
            return

        bridge = _QuotaBridge()
        bridge.loaded.connect(self._apply_quota)

        def work() -> None:
            try:
                result = fetch_simlock_quota()
            except Exception as exc:
                logger.warning("Load simlock quota failed: %s", exc)
                result = SimlockQuotaResult(ok=False, message=str(exc))

            if self._post_to_main is not None:
                self._post_to_main(lambda: bridge.loaded.emit(result))
            else:
                bridge.loaded.emit(result)

        threading.Thread(target=work, daemon=True, name="simlock-quota").start()

    def _apply_quota(self, result: SimlockQuotaResult) -> None:
        self._quota = result
        self._set_loading(False)

        if not result.ok:
            self._quota_label.setText(f"Không tải được hạn mức: {result.message}")
            self._hint_label.setText(
                "Kiểm tra kết nối và đăng nhập API, rồi mở lại hộp thoại."
            )
            self._check_checked_btn.setEnabled(False)
            self._check_all_btn.setEnabled(False)
            return

        self._quota_label.setText(
            f"Hạn mức mặc định (server): {result.simlock_count} lần\n"
            f"Đã check free: {result.simlock_used} · "
            f"Còn lại: {result.simlock_remaining}"
        )

        if result.simlock_remaining <= 0:
            self._quota_label.setStyleSheet("font-size: 13px; color: #C62828; font-weight: bold;")
            self._hint_label.setText(QUOTA_HINT_EXCEEDED)
            self._check_checked_btn.setEnabled(False)
            self._check_all_btn.setEnabled(False)
        else:
            self._quota_label.setStyleSheet("font-size: 13px; color: #2E7D32; font-weight: bold;")
            self._hint_label.setText(QUOTA_HINT_OK)

    def _run_checked(self) -> None:
        if self._quota is not None and self._quota.simlock_remaining <= 0:
            QMessageBox.warning(self, self.windowTitle(), self._hint_label.text())
            return
        self.accept()
        self._on_check_checked()

    def _run_all(self) -> None:
        if self._quota is not None and self._quota.simlock_remaining <= 0:
            QMessageBox.warning(self, self.windowTitle(), self._hint_label.text())
            return
        self.accept()
        self._on_check_all()


def open_free_simlock_dialog(
    parent: Optional[QWidget],
    *,
    on_check_checked: OnCheckFn,
    on_check_all: OnCheckFn,
    post_to_main: Optional[PostToMainFn] = None,
) -> None:
    FreeSimlockDialog(
        parent,
        on_check_checked=on_check_checked,
        on_check_all=on_check_all,
        post_to_main=post_to_main,
    ).exec()
