"""Hộp thoại đăng nhập — đăng nhập Google qua trình duyệt."""

from __future__ import annotations

import threading
import webbrowser
from typing import Callable, Optional

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.api_config import load_api_config
from src.app_branding import ZALO_CHAT_URL
from src.browser_login import BrowserLoginResult, login_via_browser
from src.license import (
    account_info_rows,
    apply_license_result,
    get_license_status,
    logout_license,
    refresh_license_status,
    session_needs_browser_refresh,
)
from src.login_help import open_account_devices_page
from src.services_dialog import sync_services_on_login
from src.theme import mark_primary

_TITLE_PX = 32
_SECTION_PX = 22
_NOTE_PX = 20
_STATUS_PX = 22
_BUTTON_PX = 18
_BUTTON_H = 48
_DIALOG_MIN_W = 620
_DIALOG_MIN_H = 560
_ACTION_GAP = 12

LOGIN_NOTES = (
    "1. Với tài khoản mới đăng nhập sẽ có thể đăng nhập duy nhất trên 1 thiết bị.",
    "2. Cần đăng nhập thêm vui lòng liên hệ.",
)

GOOGLE_LOGIN_LABEL = "Đăng nhập bằng tài khoản Google"
GOOGLE_LOGIN_BUSY_LABEL = "Đang chờ trình duyệt…"

def _btn_style(*, bg: str, color: str, border: str, hover_bg: str, disabled: str = "") -> str:
    base = (
        "QPushButton {"
        "  font-size: {px}px; font-weight: 600; border-radius: 10px;"
        "  padding: 0 18px;"
        f"  background-color: {bg}; color: {color}; border: {border};"
        "}"
        f"QPushButton:hover {{ background-color: {hover_bg}; }}"
    )
    if disabled:
        base += f"QPushButton:disabled {{ {disabled} }}"
    return base


_BTN_GOOGLE = _btn_style(
    bg="#1E88E5",
    color="white",
    border="none",
    hover_bg="#1565C0",
    disabled="background-color: #455A64; color: #B0BEC5;",
)

_BTN_ACCOUNT = _btn_style(
    bg="transparent",
    color="#90CAF9",
    border="2px solid #42A5F5",
    hover_bg="rgba(66, 165, 245, 0.15)",
)

_BTN_ZALO = _btn_style(
    bg="#0068FF",
    color="white",
    border="none",
    hover_bg="#0052CC",
)

_BTN_LOGOUT = _btn_style(
    bg="transparent",
    color="#EF9A9A",
    border="2px solid #E57373",
    hover_bg="rgba(229, 115, 115, 0.15)",
)


def open_license_dialog(
    parent: Optional[QWidget],
    *,
    on_changed: Optional[Callable[[], None]] = None,
    on_logout: Optional[Callable[[], None]] = None,
) -> None:
    dialog = LicenseDialog(parent, on_changed=on_changed)
    dialog.exec()
    if dialog.user_logged_out and on_logout is not None:
        on_logout()


def show_login_dialog(parent: Optional[QWidget] = None) -> bool:
    return LoginDialog.ask(parent)


def show_license_blocked_dialog(parent: Optional[QWidget] = None) -> bool:
    return show_login_dialog(parent)


class _BrowserLoginBridge(QObject):
    finished = Signal(object)


def _is_logged_in() -> bool:
    status = refresh_license_status()
    return bool(status.valid and not status.blocked and status.mode.value != "trial")


def _label(text: str, *, size_px: int, color: str = "", bold: bool = False) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    weight = "bold" if bold else "normal"
    color_css = f" color: {color};" if color else ""
    label.setStyleSheet(f"font-size: {size_px}px; font-weight: {weight};{color_css}")
    return label


def _button_stylesheet(template: str) -> str:
    """Thay {px} — không dùng str.format vì CSS có ngoặc `{}`."""
    return template.replace("{px}", str(_BUTTON_PX))


def _styled_button(text: str, style: str) -> QPushButton:
    btn = QPushButton(text)
    btn.setStyleSheet(_button_stylesheet(style))
    btn.setFixedHeight(_BUTTON_H)
    return btn


def _action_button_box(*buttons: QPushButton) -> QWidget:
    panel = QWidget()
    layout = QVBoxLayout(panel)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(_ACTION_GAP)
    for button in buttons:
        layout.addWidget(button)
    return panel


def _account_table_widget() -> QWidget:
    panel = QWidget()
    grid = QGridLayout(panel)
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setHorizontalSpacing(20)
    grid.setVerticalSpacing(12)
    grid.setColumnStretch(0, 0)
    grid.setColumnStretch(1, 1)

    for row, (label, value) in enumerate(account_info_rows()):
        grid.addWidget(
            _label(f"{label}:", size_px=_STATUS_PX, color="#B0BEC5"),
            row,
            0,
        )
        grid.addWidget(
            _label(value, size_px=_STATUS_PX, color="#81C784", bold=True),
            row,
            1,
        )
    return panel


class _LoginDialogBase(QDialog):
    def __init__(
        self,
        parent: Optional[QWidget],
        *,
        window_title: str,
        heading: str,
        logged_in: bool,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(window_title)
        self.setMinimumSize(_DIALOG_MIN_W, _DIALOG_MIN_H)
        self.resize(_DIALOG_MIN_W, _DIALOG_MIN_H)

        self._heading = heading
        self._logged_in = logged_in
        self._google_login_btn: Optional[QPushButton] = None
        self._cfg = load_api_config()

        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(32, 28, 32, 28)
        self._root.setSpacing(16)

        self._rebuild_body()

    def _clear_body(self) -> None:
        while self._root.count():
            item = self._root.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _rebuild_body(self) -> None:
        self._clear_body()
        self._logged_in = _is_logged_in()

        self._root.addWidget(_label(self._heading, size_px=_TITLE_PX, bold=True))

        if self._logged_in:
            self._root.addWidget(_account_table_widget())
            self._root.addSpacing(16)
            account_btn = _styled_button("Quản lý tài khoản", _BTN_ACCOUNT)
            account_btn.clicked.connect(lambda: open_account_devices_page(self._cfg.api_base_url))
            action_buttons = [account_btn, *self._extra_logged_in_buttons()]
            self._root.addWidget(_action_button_box(*action_buttons))
            hint = self._logged_in_hint()
            if hint:
                self._root.addSpacing(8)
                self._root.addWidget(_label(hint, size_px=_NOTE_PX, color="#90A4AE"))
        else:
            self._root.addWidget(_label("Ghi chú:", size_px=_SECTION_PX, bold=True, color="#B0BEC5"))
            for line in LOGIN_NOTES:
                self._root.addWidget(_label(line, size_px=_NOTE_PX, color="#B0BEC5"))
            self._root.addSpacing(8)
            self._google_login_btn = _styled_button(GOOGLE_LOGIN_LABEL, _BTN_GOOGLE)
            self._google_login_btn.setDefault(True)
            mark_primary(self._google_login_btn)
            self._google_login_btn.clicked.connect(self._start_browser_login)
            self._root.addWidget(self._google_login_btn)

        self._root.addSpacing(8)
        zalo_btn = _styled_button("Chat Zalo", _BTN_ZALO)
        zalo_btn.clicked.connect(lambda: webbrowser.open(ZALO_CHAT_URL))
        self._root.addWidget(zalo_btn)
        self._root.addStretch(1)

    def _extra_logged_in_buttons(self) -> list[QPushButton]:
        return []

    def _logged_in_hint(self) -> str:
        return ""

    def _finish_browser_login(self, result: BrowserLoginResult) -> bool:
        if not result.ok or result.access is None:
            QMessageBox.critical(
                self,
                "Đăng nhập",
                result.message or "Đăng nhập Google thất bại.",
            )
            return False

        apply_license_result(result.access, load_api_config())
        sync_services_on_login(silent=True)
        return True

    def _start_browser_login(self) -> None:
        if self._google_login_btn is not None:
            self._google_login_btn.setEnabled(False)
            self._google_login_btn.setText(GOOGLE_LOGIN_BUSY_LABEL)

        bridge = _BrowserLoginBridge(self)
        bridge.finished.connect(self._on_browser_login_done)

        def work() -> None:
            bridge.finished.emit(login_via_browser(self._cfg))

        threading.Thread(target=work, daemon=True, name="browser-login").start()

    def _reset_google_login_button(self) -> None:
        if self._google_login_btn is not None:
            self._google_login_btn.setEnabled(True)
            self._google_login_btn.setText(GOOGLE_LOGIN_LABEL)

    def _on_browser_login_done(self, result: BrowserLoginResult) -> None:
        self._reset_google_login_button()
        if self._finish_browser_login(result):
            self.accept()


class LicenseDialog(_LoginDialogBase):
    def __init__(
        self,
        parent: Optional[QWidget],
        *,
        on_changed: Optional[Callable[[], None]] = None,
    ) -> None:
        self._on_changed = on_changed
        self.user_logged_out = False
        super().__init__(
            parent,
            window_title="Tài khoản",
            heading="Tài khoản",
            logged_in=_is_logged_in(),
        )

    def _extra_logged_in_buttons(self) -> list[QPushButton]:
        logout_btn = _styled_button("Đăng xuất", _BTN_LOGOUT)
        logout_btn.clicked.connect(self._logout)
        return [logout_btn]

    def _logged_in_hint(self) -> str:
        return "Muốn đổi tài khoản khác: bấm Đăng xuất, sau đó đăng nhập Google lại."

    def _logout(self) -> None:
        answer = QMessageBox.question(
            self,
            "Đăng xuất",
            "Đăng xuất tài khoản hiện tại trên máy này?\n"
            "Bạn có thể đăng nhập Google bằng tài khoản khác ngay sau đó.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        logout_license()
        self._cfg = load_api_config()
        self.user_logged_out = True
        if self._on_changed is not None:
            self._on_changed()
        self.reject()

    def _on_browser_login_done(self, result: BrowserLoginResult) -> None:
        self._reset_google_login_button()
        if not self._finish_browser_login(result):
            return
        status = get_license_status()
        QMessageBox.information(
            self,
            "Đăng nhập",
            f"Kết nối thành công.\n{status.message or status.shop_name}",
        )
        if self._on_changed is not None:
            self._on_changed()
        self._rebuild_body()
        self.accept()


class LoginDialog(_LoginDialogBase):
    def __init__(
        self,
        parent: Optional[QWidget],
        *,
        heading: str = "Đăng nhập để sử dụng app",
    ) -> None:
        super().__init__(
            parent,
            window_title="Đăng nhập",
            heading=heading,
            logged_in=_is_logged_in(),
        )

    @classmethod
    def ask(cls, parent: Optional[QWidget] = None) -> bool:
        refresh_license_status()
        if _is_logged_in():
            return True
        heading = "Đăng nhập để sử dụng app"
        auto_refresh = session_needs_browser_refresh()
        if auto_refresh:
            heading = "Phiên đăng nhập hết hạn — đăng nhập Google lại"
        dialog = cls(parent, heading=heading)
        if auto_refresh:
            QTimer.singleShot(200, dialog._start_browser_login)
        return dialog.exec() == QDialog.Accepted
