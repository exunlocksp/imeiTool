"""Cửa sổ chính Taoden IMEI Tool (PySide6)."""

from __future__ import annotations

import logging
import subprocess
import sys
import threading
from io import BytesIO
from pathlib import Path
from typing import Callable, Optional

from PIL import Image
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QIcon,
    QKeySequence,
    QPixmap,
    QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.app_branding import ABOUT_CREDITS, APP_NAME, APP_VERSION, app_icon_path
from src.about_dialog import show_about_dialog
from src.activity_log import log_action, log_done, log_error, log_start, set_log_handler
from src.theme import (
    ACCENT,
    BG_DEEP,
    BORDER,
    DANGER,
    SIMLOCK_COLORS,
    TEXT_MUTED,
    WARNING,
    apply_theme,
    mark_primary,
)
from src.clipboard_image import clipboard_image
from src.database import DeviceDatabase
from src.excel_export import export_records
from src.export_fields_dialog import pick_export_fields
from src.text_export import export_records_text
from src.models import DeviceRecord
from src.line_import import LINE_IMPORT_HINT, parse_bulk_lines
from src.app_settings import AppSettings
from src.auto_services import (
    AutoServicesResult,
    apply_parsed_check_fields_from_note,
    apply_parsed_fields_to_record,
    apply_server_parsed_to_records,
    merge_notes,
    run_auto_services,
)
from src.order_sync import OrderSyncEngine
from src.print_labels import open_print_labels
from src.free_simlock_dialog import open_free_simlock_dialog
from src.services_dialog import open_services_dialog
from src.services_store import find_service_by_id, load_auto_service_prefs
from src.settings_dialog import open_settings_dialog
from src.ocr_parser import (
    ocr_available,
    ocr_engine_name,
    ocr_missing_hint,
    parse_image,
    parse_text_to_record,
)
from src.license import (
    license_status_color,
    license_status_message,
    refresh_license_status,
)
from src.license_dialog import open_license_dialog, show_login_dialog
from src.api_client import get_simlock_quota
from src.api_config import load_api_config
from src.simlock_sync import SIMLOCK_PENDING_LABEL, SIMLOCK_UNKNOWN_LABEL, fetch_simlock
from src.usb_reader import UsbDeviceMonitor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CHECK_ON = "☑"
CHECK_OFF = "☐"

COLUMNS = (
    "check",
    "time",
    "source",
    "imei1",
    "imei2",
    "serial",
    "model",
    "ios_version",
    "color",
    "storage",
    "condition",
    "simlock",
    "fmi",
    "active",
    "carrier",
    "mdm",
    "battery_health",
    "cycle_count",
)
COLUMN_LABELS = {
    "check": CHECK_OFF,
    "time": "Thời gian",
    "source": "Nguồn",
    "imei1": "IMEI 1",
    "imei2": "IMEI 2",
    "serial": "Serial",
    "model": "Model",
    "ios_version": "iOS",
    "color": "Màu",
    "storage": "Bộ nhớ",
    "condition": "Hình thức",
    "simlock": "Simlock",
    "fmi": "FMI",
    "active": "Active",
    "carrier": "Nhà mạng",
    "mdm": "MDM",
    "battery_health": "% Pin",
    "cycle_count": "Lần sạc",
}
COLUMN_ATTR: dict[str, str] = {
    col: (
        "captured_at"
        if col == "time"
        else "storage_capacity"
        if col == "storage"
        else col
    )
    for col in COLUMNS
    if col != "check"
}
# Cột co giãn theo nội dung; user kéo header để chỉnh rộng (scroll ngang khi cần).
STRETCH_COLUMNS: frozenset[str] = frozenset()

FILTER_ALL = "Tất cả"
SIMLOCK_FILTER_VALUES = (FILTER_ALL, "Locked", "Unlocked", SIMLOCK_PENDING_LABEL, SIMLOCK_UNKNOWN_LABEL)
FMI_FILTER_VALUES = (FILTER_ALL, "On", "Off")
ACTIVE_FILTER_VALUES = (FILTER_ALL, "Yes", "No", "replaced")

# Màu trạng thái: (giá trị → màu chữ) cho cột FMI, Active và MDM
FMI_COLORS = {"On": DANGER, "Off": ACCENT}
MDM_COLORS = {"On": DANGER, "Off": ACCENT}
ACTIVE_COLORS = {"Yes": ACCENT, "No": DANGER, "replaced": DANGER}
IMEI_COLUMNS = ("imei1", "imei2")
CHECK_COL_WIDTH = 44

STATUS_FLASH_MS = 450
STATUS_FLASH_MAX_TICKS = 40
ROW_SIMLOCK_FLASH_MS = 450

FLASH_BG_HI = QColor("#4A3F10")
FLASH_FG_HI = QColor("#FFE566")
FLASH_FG_LO = QColor("#CCAA33")

# (tiêu đề nhóm, [(nhãn, attr, mono?)…]) — hiển thị trong panel chi tiết
DETAIL_SECTIONS: tuple[tuple[str, tuple[tuple[str, str, bool], ...]], ...] = (
    (
        "Định danh",
        (
            ("IMEI 1", "imei1", True),
            ("IMEI 2", "imei2", True),
            ("Serial", "serial", True),
            ("UDID", "device_udid", True),
        ),
    ),
    (
        "Cấu hình",
        (
            ("Model", "model", False),
            ("iOS", "ios_version", False),
            ("Màu", "color", False),
            ("Bộ nhớ", "storage_capacity", False),
        ),
    ),
    (
        "Tình trạng",
        (
            ("Hình thức", "condition", False),
            ("Simlock", "simlock", False),
            ("FMI (iCloud)", "fmi", False),
            ("Active", "active", False),
            ("Nhà mạng", "carrier", False),
            ("MDM", "mdm", False),
            ("% Pin", "battery_health", False),
            ("Lần sạc", "cycle_count", False),
        ),
    ),
    (
        "Khác",
        (
            ("Thời gian", "captured_at", False),
            ("Nguồn", "source", False),
            ("Ghi chú", "note", False),
        ),
    ),
)

COPYABLE_DETAIL_ATTRS = {"imei1", "imei2", "serial"}
DETAIL_READONLY_ATTRS = frozenset({"imei1", "note"})
OPTIONAL_DETAIL_ATTRS = {"device_udid", "note", "imei2"}
MONO_TABLE_COLUMNS = {"imei1", "imei2", "serial"}
DETAIL_ATTR_LABELS = {
    attr: label
    for _section, fields in DETAIL_SECTIONS
    for label, attr, _mono in fields
}


def _open_file(path: Path) -> None:
    if sys.platform == "darwin":
        subprocess.run(["open", str(path)], check=False)
    elif sys.platform == "win32":
        import os

        os.startfile(path)  # type: ignore[attr-defined]
    else:
        subprocess.run(["xdg-open", str(path)], check=False)


def _pil_to_pixmap(image: Image.Image) -> QPixmap:
    buf = BytesIO()
    image.save(buf, format="PNG")
    pixmap = QPixmap()
    pixmap.loadFromData(buf.getvalue(), "PNG")
    return pixmap


class ImeiToolWindow(QMainWindow):
    """Cửa sổ chính — bảng thiết bị, panel chi tiết, menu, USB monitor."""

    _invoke = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(1024, 640)

        self.db = DeviceDatabase()
        self.records: list[DeviceRecord] = []
        self._dedupe_keys: set[str] = set()
        self._checked_rows: set[int] = set()
        self._check_anchor_row: Optional[int] = None
        self._prev_selected_rows: set[int] = set()
        self._selected_row: Optional[int] = None
        self._updating_table = False
        self._search_text = ""
        self._filter_simlock = FILTER_ALL
        self._filter_fmi = FILTER_ALL
        self._filter_active = FILTER_ALL
        self._sort_section: Optional[int] = None
        self._sort_ascending = True
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(200)
        self._search_timer.timeout.connect(self._apply_table_filter)
        self.settings = AppSettings.load()

        self._usb_stop = threading.Event()
        self._usb_thread: Optional[threading.Thread] = None

        self._status_flash_timer = QTimer(self)
        self._status_flash_timer.setInterval(STATUS_FLASH_MS)
        self._status_flash_timer.timeout.connect(self._flash_status_tick)
        self._status_flash_ticks = 0
        self._status_flash_bright = True
        self._status_highlight_active = False

        self._simlock_flash_rows: dict[int, bool] = {}
        self._simlock_flash_timer = QTimer(self)
        self._simlock_flash_timer.setInterval(ROW_SIMLOCK_FLASH_MS)
        self._simlock_flash_timer.timeout.connect(self._simlock_flash_tick)

        # Gọi hàm bất kỳ trên main thread từ worker thread (queued connection).
        self._invoke.connect(lambda fn: fn())

        self.monitor = UsbDeviceMonitor(
            on_status=lambda msg: self._post(lambda: self._set_status(msg)),
            on_record=lambda rec: self._post(lambda: self._on_usb_record(rec)),
            on_unplug=lambda udid: self._post(lambda: self._on_usb_unplug(udid)),
            on_dismiss_lift=lambda udid: self._post(lambda: self._undismiss_usb(udid)),
        )

        icon = app_icon_path()
        if icon is not None:
            self.setWindowIcon(QIcon(str(icon)))

        self._build_ui()
        self._build_menu()
        set_log_handler(lambda line: self._post(lambda: self._append_activity_log(line)))
        log_action("Ứng dụng khởi động")
        self._refresh_license_badge()
        for udid in self.db.load_dismissed_usb():
            self.monitor.dismiss_udid(udid)
        self._load_from_database()
        self._order_sync = self._build_order_sync()
        self._start_order_sync()
        self._start_usb_monitor()

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 8, 12, 8)
        root.setSpacing(8)

        self._h_split = QSplitter(Qt.Horizontal)
        self._h_split.addWidget(self._build_table_area())
        detail_panel = self._build_detail_panel()
        self._h_split.addWidget(detail_panel)
        self._h_split.setStretchFactor(0, 1)
        self._h_split.setStretchFactor(1, 0)
        self._h_split.setSizes([900, 300])

        h_split = self._h_split

        v_split = QSplitter(Qt.Vertical)
        v_split.addWidget(h_split)
        v_split.addWidget(self._build_log_panel())
        v_split.setStretchFactor(0, 4)
        v_split.setStretchFactor(1, 1)
        v_split.setSizes([520, 140])

        root.addWidget(v_split)
        self.setCentralWidget(central)

        self._status_label = QLabel("Sẵn sàng")
        self.statusBar().addWidget(self._status_label, 1)

        if ocr_available():
            name = ocr_engine_name()
            ocr_hint = f"OCR: {name}" if name else "OCR: sẵn sàng"
        elif __import__("src.bundle_paths", fromlist=["is_frozen"]).is_frozen():
            ocr_hint = "OCR: không khả dụng trong bản build"
        else:
            ocr_hint = "OCR: cần macOS 10.15+"
        ocr_label = QLabel(ocr_hint)
        ocr_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        self.statusBar().addPermanentWidget(ocr_label)

        self._license_badge = QLabel(license_status_message())
        self._license_badge.setStyleSheet("font-weight: bold; font-size: 12px;")
        self.statusBar().addPermanentWidget(self._license_badge)

    def _build_table_area(self) -> QWidget:
        area = QWidget()
        layout = QVBoxLayout(area)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self._build_table_toolbar())
        self._build_table()
        layout.addWidget(self.table, 1)
        return area

    def _build_table_toolbar(self) -> QWidget:
        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        search_label = QLabel("Tìm")
        search_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        row.addWidget(search_label)

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("IMEI, serial, model, nhà mạng, ghi chú…")
        self._search_input.setClearButtonEnabled(True)
        self._search_input.textChanged.connect(self._on_search_text_changed)
        row.addWidget(self._search_input, 1)

        def add_filter(label: str, values: tuple[str, ...]) -> QComboBox:
            row.addWidget(QLabel(label))
            combo = QComboBox()
            combo.addItems(list(values))
            combo.setMinimumWidth(96)
            row.addWidget(combo)
            return combo

        self._filter_simlock_combo = add_filter("Simlock", SIMLOCK_FILTER_VALUES)
        self._filter_simlock_combo.currentTextChanged.connect(self._on_simlock_filter_changed)

        self._filter_fmi_combo = add_filter("FMI", FMI_FILTER_VALUES)
        self._filter_fmi_combo.currentTextChanged.connect(self._on_fmi_filter_changed)

        self._filter_active_combo = add_filter("Active", ACTIVE_FILTER_VALUES)
        self._filter_active_combo.currentTextChanged.connect(self._on_active_filter_changed)

        clear_btn = QPushButton("Xóa lọc")
        clear_btn.clicked.connect(self._clear_table_filters)
        row.addWidget(clear_btn)

        self._filter_count_label = QLabel("")
        self._filter_count_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        row.addWidget(self._filter_count_label)

        hint = QLabel("Shift+click: chọn dải · Ctrl/⌘+click: tick từng dòng")
        hint.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        row.addWidget(hint)
        return bar

    def _build_table(self) -> None:
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels([COLUMN_LABELS[c] for c in COLUMNS])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.ExtendedSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setWordWrap(True)
        self.table.setTextElideMode(Qt.ElideNone)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._mono_font = QFont("Menlo" if sys.platform == "darwin" else "Consolas", 12)
        self.table.setEditTriggers(
            QTableWidget.DoubleClicked
            | QTableWidget.EditKeyPressed
            | QTableWidget.AnyKeyPressed
        )

        header = self.table.horizontalHeader()
        header.setMinimumSectionSize(40)
        header.setStretchLastSection(False)
        header.setSectionsClickable(True)
        header.sectionClicked.connect(self._on_header_clicked)

        self.table.itemChanged.connect(self._on_item_changed)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)

        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_table_menu)

        delete_sc = QShortcut(QKeySequence(Qt.Key_Backspace), self.table)
        delete_sc.activated.connect(self._delete_checked)
        delete_sc2 = QShortcut(QKeySequence.Delete, self.table)
        delete_sc2.activated.connect(self._delete_checked)

        self._apply_table_columns()
        self._update_table_headers()

    def _build_log_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        header = QHBoxLayout()
        title = QLabel("Nhật ký")
        title.setStyleSheet("font-size: 12px; font-weight: bold;")
        header.addWidget(title)
        header.addStretch(1)
        clear_btn = QPushButton("Xóa log")
        clear_btn.setFixedHeight(24)
        clear_btn.clicked.connect(self._clear_activity_log)
        header.addWidget(clear_btn)
        layout.addLayout(header)

        self._log_view = QPlainTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setMaximumBlockCount(500)
        self._log_view.setPlaceholderText("GET/POST, tiến trình và thao tác sẽ hiển thị tại đây…")
        self._log_view.setFont(QFont("Menlo" if sys.platform == "darwin" else "Consolas", 11))
        self._log_view.setStyleSheet(
            f"QPlainTextEdit {{ background: {BG_DEEP}; border: 1px solid {BORDER}; "
            f"border-radius: 6px; color: {TEXT_MUTED}; padding: 4px; }}"
        )
        layout.addWidget(self._log_view)
        return panel

    def _append_activity_log(self, line: str) -> None:
        if not hasattr(self, "_log_view"):
            return
        self._log_view.appendPlainText(line)
        bar = self._log_view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _clear_activity_log(self) -> None:
        if hasattr(self, "_log_view"):
            self._log_view.clear()
            log_action("Đã xóa nhật ký")

    def _build_detail_panel(self) -> QWidget:
        panel = QWidget()
        panel.setMinimumWidth(280)
        panel.setMaximumWidth(360)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        title = QLabel("Chi tiết dòng chọn")
        title.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(title)

        self._detail_scroll = QScrollArea()
        self._detail_scroll.setWidgetResizable(True)
        self._detail_scroll.setFrameShape(QFrame.StyledPanel)
        self._detail_scroll.setProperty("card", True)

        self._detail_body = QWidget()
        detail_root = QVBoxLayout(self._detail_body)
        detail_root.setContentsMargins(12, 10, 12, 10)
        detail_root.setSpacing(5)

        self._detail_hint = QLabel("Chọn một dòng trong bảng.")
        self._detail_hint.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        self._detail_hint.setWordWrap(True)
        detail_root.addWidget(self._detail_hint)

        self._detail_form = QWidget()
        form_layout = QVBoxLayout(self._detail_form)
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.setSpacing(5)
        self._detail_inputs: dict[str, QWidget] = {}
        self._detail_copy_btns: dict[str, QPushButton] = {}
        self._detail_record: Optional[DeviceRecord] = None
        self._detail_syncing = False

        first_section = True
        for section_title, fields in DETAIL_SECTIONS:
            header = QLabel(section_title.upper())
            header.setStyleSheet(
                f"color: {TEXT_MUTED}; font-size: 10px; font-weight: bold;"
                " letter-spacing: 1px;"
            )
            header.setContentsMargins(0, 0 if first_section else 10, 0, 2)
            form_layout.addWidget(header)
            first_section = False

            for label, attr, mono in fields:
                row_widget = QWidget()
                row = QHBoxLayout(row_widget)
                row.setContentsMargins(0, 0, 0, 0)
                row.setSpacing(6)

                key_label = QLabel(label)
                key_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
                key_label.setFixedWidth(72)
                key_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
                row.addWidget(key_label)

                if attr == "note":
                    editor: QWidget = QPlainTextEdit()
                    editor.setReadOnly(True)
                    editor.setMaximumHeight(120)
                    editor.setPlaceholderText("—")
                elif attr in DETAIL_READONLY_ATTRS:
                    editor = QLineEdit()
                    editor.setReadOnly(True)
                else:
                    editor = QLineEdit()
                    editor.setPlaceholderText("—")
                    editor.editingFinished.connect(
                        lambda a=attr: self._commit_detail_field(a)
                    )

                if mono and isinstance(editor, QLineEdit):
                    editor.setFont(self._mono_font)
                self._detail_inputs[attr] = editor
                row.addWidget(editor, 1)

                if attr in COPYABLE_DETAIL_ATTRS:
                    copy_btn = QPushButton("⧉")
                    copy_btn.setFixedSize(24, 22)
                    copy_btn.setToolTip(f"Copy {label}")
                    copy_btn.setStyleSheet("QPushButton { padding: 0; font-size: 12px; }")
                    copy_btn.clicked.connect(
                        lambda _checked=False, a=attr: self._copy_detail_attr(a)
                    )
                    self._detail_copy_btns[attr] = copy_btn
                    row.addWidget(copy_btn)

                form_layout.addWidget(row_widget)

        form_layout.addStretch(1)
        detail_root.addWidget(self._detail_form, 1)
        self._detail_scroll.setWidget(self._detail_body)
        layout.addWidget(self._detail_scroll, 1)

        self._detail_print_btn = QPushButton("In nhãn")
        mark_primary(self._detail_print_btn)
        self._detail_print_btn.clicked.connect(self._print_selected_detail)
        layout.addWidget(self._detail_print_btn)

        self._show_record_detail(None)
        return panel

    def _detail_field_style(self, attr: str, value: str) -> str:
        style = "font-size: 12px;"
        if attr in MONO_TABLE_COLUMNS and attr != "note":
            style = "font-family: Menlo, monospace; font-size: 12px;"
        if attr == "simlock" and value in SIMLOCK_COLORS:
            style += f" color: {SIMLOCK_COLORS[value]}; font-weight: bold;"
        elif attr == "simlock" and value == SIMLOCK_PENDING_LABEL:
            style += f" color: {WARNING};"
        elif attr == "fmi" and value in FMI_COLORS:
            style += f" color: {FMI_COLORS[value]}; font-weight: bold;"
        elif attr == "active" and value in ACTIVE_COLORS:
            style += f" color: {ACTIVE_COLORS[value]}; font-weight: bold;"
        elif attr == "mdm" and value in MDM_COLORS:
            style += f" color: {MDM_COLORS[value]}; font-weight: bold;"
        return style

    def _set_detail_widget_value(self, attr: str, value: str) -> None:
        widget = self._detail_inputs.get(attr)
        if widget is None:
            return
        if isinstance(widget, QPlainTextEdit):
            widget.setPlainText(value)
            widget.setStyleSheet(self._detail_field_style(attr, value))
        elif isinstance(widget, QLineEdit):
            widget.setText(value)
            widget.setStyleSheet(self._detail_field_style(attr, value))
        copy_btn = self._detail_copy_btns.get(attr)
        if copy_btn is not None:
            copy_btn.setEnabled(bool(value))

    def _copy_detail_value(self, label: str, value: str) -> None:
        QApplication.clipboard().setText(value)
        self._set_status(f"Đã copy ({label}): {value}")

    def _copy_detail_attr(self, attr: str) -> None:
        if self._detail_record is None:
            return
        value = str(getattr(self._detail_record, attr, "") or "").strip()
        if not value:
            return
        self._copy_detail_value(DETAIL_ATTR_LABELS.get(attr, attr), value)

    def _commit_detail_field(self, attr: str) -> None:
        if self._detail_syncing or self._detail_record is None:
            return
        if attr in DETAIL_READONLY_ATTRS:
            return
        widget = self._detail_inputs.get(attr)
        if not isinstance(widget, QLineEdit) or widget.isReadOnly():
            return
        record = self._detail_record
        if record not in self.records:
            return
        new_value = widget.text().strip()
        old_value = str(getattr(record, attr, "") or "")
        if new_value == old_value:
            return

        if attr == "serial" and new_value:
            new_value = new_value.upper()
        setattr(record, attr, new_value)
        widget.setStyleSheet(self._detail_field_style(attr, new_value))

        row_index = self.records.index(record)
        if attr == "serial" and old_value:
            snap = DeviceRecord(serial=old_value, imei1=record.imei1, device_udid=record.device_udid)
            self._unregister_record(snap, keep_usb_seen=True)
            self._register_record(record)
        self._db_save_record(record)
        self._update_row(row_index, record, refresh_detail=False)

        self._set_status(f"Đã cập nhật {DETAIL_ATTR_LABELS.get(attr, attr)}")

    def _show_record_detail(self, record: Optional[DeviceRecord]) -> None:
        self._detail_record = record
        self._detail_syncing = True
        try:
            if record is None:
                self._detail_hint.setVisible(True)
                self._detail_form.setVisible(False)
                self._detail_print_btn.setEnabled(False)
                return

            self._detail_hint.setVisible(False)
            self._detail_form.setVisible(True)
            self._detail_print_btn.setEnabled(True)

            for _section, fields in DETAIL_SECTIONS:
                for _label, attr, _mono in fields:
                    raw = getattr(record, attr, None)
                    value = str(raw).strip() if raw is not None else ""
                    self._set_detail_widget_value(attr, value)
        finally:
            self._detail_syncing = False

    def _build_menu(self) -> None:
        menubar = self.menuBar()

        file_menu = menubar.addMenu("Tệp")
        about_action = QAction(f"Về {APP_NAME}…", self)
        about_action.setMenuRole(QAction.AboutRole)
        about_action.triggered.connect(self._show_about)
        file_menu.addAction(about_action)
        file_menu.addSeparator()
        export_text_action = QAction("Xuất Text…", self)
        export_text_action.triggered.connect(self._export_text)
        file_menu.addAction(export_text_action)
        export_action = QAction("Xuất Excel…", self)
        export_action.setShortcut(QKeySequence("Ctrl+E"))
        export_action.triggered.connect(self._export_excel)
        file_menu.addAction(export_action)
        print_action = QAction("In đã tick…", self)
        print_action.setShortcut(QKeySequence("Ctrl+P"))
        print_action.triggered.connect(self._print_checked)
        file_menu.addAction(print_action)
        print_settings_action = QAction("Tùy chọn in nhãn…", self)
        print_settings_action.triggered.connect(self._open_settings)
        file_menu.addAction(print_settings_action)
        file_menu.addSeparator()
        quit_action = QAction("Thoát", self)
        quit_action.setMenuRole(QAction.QuitRole)
        quit_action.setShortcut(QKeySequence("Ctrl+Q"))
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        import_menu = menubar.addMenu("Nhập liệu")
        lines_action = QAction("Thêm theo dòng…", self)
        lines_action.setShortcut(QKeySequence("Ctrl+L"))
        lines_action.triggered.connect(self._open_add_lines_dialog)
        import_menu.addAction(lines_action)
        image_action = QAction("Đọc từ ảnh…", self)
        image_action.setShortcut(QKeySequence("Ctrl+I"))
        image_action.triggered.connect(self._open_image_dialog)
        import_menu.addAction(image_action)
        text_action = QAction("Phân tích văn bản…", self)
        text_action.setShortcut(QKeySequence("Ctrl+T"))
        text_action.triggered.connect(self._open_text_dialog)
        import_menu.addAction(text_action)

        services_menu = menubar.addMenu("Dịch vụ")
        services_open = QAction("Dịch vụ khác", self)
        services_open.triggered.connect(self._open_services)
        services_menu.addAction(services_open)
        free_simlock_action = QAction("Check Lock Quốc Tế Miễn Free", self)
        free_simlock_action.triggered.connect(self._open_free_simlock_dialog)
        services_menu.addAction(free_simlock_action)

        table_menu = menubar.addMenu("Bảng")
        display_action = QAction("Cột bảng & in nhãn…", self)
        display_action.triggered.connect(self._open_settings)
        table_menu.addAction(display_action)
        table_menu.addSeparator()
        delete_action = QAction("Xóa dòng đã tick", self)
        delete_action.triggered.connect(self._delete_checked)
        table_menu.addAction(delete_action)
        clear_action = QAction("Xóa tất cả", self)
        clear_action.triggered.connect(self._clear_all)
        table_menu.addAction(clear_action)

        settings_menu = menubar.addMenu("Cài đặt")
        prefs_action = QAction("Bảng & in nhãn…", self)
        prefs_action.triggered.connect(self._open_settings)
        settings_menu.addAction(prefs_action)
        license_action = QAction("Tài khoản API…", self)
        license_action.triggered.connect(self._open_license)
        settings_menu.addAction(license_action)

    def _show_about(self) -> None:
        show_about_dialog(self, APP_NAME, APP_VERSION, ABOUT_CREDITS)

    # ------------------------------------------------------- thread bridge

    def _post(self, fn: Callable[[], None]) -> None:
        """Chạy fn trên main thread (an toàn khi gọi từ worker thread)."""
        self._invoke.emit(fn)

    # ------------------------------------------------------------- status

    def _set_status(self, message: str) -> None:
        self._status_highlight_active = False
        self._stop_status_flash()
        self._status_label.setText(message)

    def _show_server_sync_status(self, message: str) -> None:
        self._status_highlight_active = True
        self._status_label.setText(message)
        self._status_label.setStyleSheet("font-size: 17px; font-weight: bold;")
        self._status_flash_ticks = 0
        self._status_flash_bright = True
        self._status_flash_timer.start()

    def _flash_status_tick(self) -> None:
        if self._status_flash_ticks >= STATUS_FLASH_MAX_TICKS:
            self._status_highlight_active = False
            self._stop_status_flash()
            return
        self._status_flash_bright = not self._status_flash_bright
        color = "#FFEA00" if self._status_flash_bright else "#FF8F00"
        self._status_label.setStyleSheet(
            f"font-size: 17px; font-weight: bold; color: {color};"
        )
        self._status_flash_ticks += 1

    def _stop_status_flash(self) -> None:
        self._status_flash_timer.stop()
        self._status_label.setStyleSheet("")

    def _refresh_license_badge(self) -> None:
        """Cập nhật badge credit — gọi API trên background thread, không block UI."""

        def work() -> None:
            refresh_license_status()

            def apply() -> None:
                _light, dark = license_status_color()
                self._license_badge.setText(license_status_message())
                self._license_badge.setStyleSheet(
                    f"font-weight: bold; font-size: 12px; color: {dark};"
                )

            self._post(apply)

        threading.Thread(target=work, daemon=True, name="license-refresh").start()

    # ------------------------------------------------------------- columns

    def _apply_table_columns(self) -> None:
        visible = {"check", *self.settings.visible_table_columns()}
        for i, col in enumerate(COLUMNS):
            self.table.setColumnHidden(i, col not in visible)
        self._configure_table_columns()
        if self.table.rowCount() > 0:
            self._resize_all_columns_to_contents()

    def _imei_column_width(self) -> int:
        cached = getattr(self, "_imei_col_width", None)
        if cached is not None:
            return cached
        metrics = QFontMetrics(self.table.font())
        width = metrics.horizontalAdvance("9" * 15) + 24
        self._imei_col_width = max(width, 148)
        return self._imei_col_width

    def _column_min_width(self, col: str) -> int:
        widths = getattr(self, "_col_min_widths", None)
        if widths is None:
            metrics = QFontMetrics(self.table.font())
            mono = QFontMetrics(self._mono_font)
            computed: dict[str, int] = {}
            samples = {
                "time": "12/06 23:59",
                "source": "USB",
                "serial": "C02XK0XXXXXX",
                "model": "iPhone 14 Pro Max",
                "ios_version": "18.4.1",
                "color": "Deep Purple",
                "storage": "256 GB",
                "condition": "Like New",
                "simlock": "Unlocked",
                "fmi": "Off",
                "active": "Yes",
                "carrier": "US Sprint/T-Mobile",
                "mdm": "Off",
                "battery_health": "100%",
                "cycle_count": "999",
            }
            for c in COLUMNS:
                if c == "check":
                    continue
                label_w = metrics.horizontalAdvance(COLUMN_LABELS.get(c, c))
                sample = samples.get(c, COLUMN_LABELS.get(c, c))
                font_metrics = mono if c in MONO_TABLE_COLUMNS else metrics
                content_w = font_metrics.horizontalAdvance(sample)
                computed[c] = max(label_w, content_w) + 24
            self._col_min_widths = computed
            widths = computed
        return widths.get(col, 56)

    def _configure_table_columns(self) -> None:
        header = self.table.horizontalHeader()
        imei_w = self._imei_column_width()

        for i, col in enumerate(COLUMNS):
            if self.table.isColumnHidden(i):
                continue
            if col == "check":
                header.setSectionResizeMode(i, QHeaderView.Fixed)
                self.table.setColumnWidth(i, CHECK_COL_WIDTH)
            else:
                header.setSectionResizeMode(i, QHeaderView.Interactive)
                default_w = imei_w if col in IMEI_COLUMNS else self._column_min_width(col)
                self.table.setColumnWidth(i, default_w)

    def _resize_all_columns_to_contents(self) -> None:
        """Đo nội dung + cho phép kéo dãn; bật wrap để luôn thấy đủ chữ."""
        if self.table.rowCount() == 0:
            return
        header = self.table.horizontalHeader()
        saved: dict[int, int] = {}
        for i, col in enumerate(COLUMNS):
            if self.table.isColumnHidden(i) or col == "check":
                continue
            saved[i] = self.table.columnWidth(i)
            header.setSectionResizeMode(i, QHeaderView.ResizeToContents)

        self.table.resizeColumnsToContents()

        for i, col in enumerate(COLUMNS):
            if self.table.isColumnHidden(i):
                continue
            if col == "check":
                header.setSectionResizeMode(i, QHeaderView.Fixed)
                self.table.setColumnWidth(i, CHECK_COL_WIDTH)
            else:
                header.setSectionResizeMode(i, QHeaderView.Interactive)
                min_w = self._imei_column_width() if col in IMEI_COLUMNS else self._column_min_width(col)
                self.table.setColumnWidth(i, max(self.table.columnWidth(i), min_w, saved.get(i, 0)))

        for row in range(self.table.rowCount()):
            self.table.resizeRowToContents(row)

    def _resize_row_to_contents(self, row: int) -> None:
        if 0 <= row < self.table.rowCount():
            self.table.resizeRowToContents(row)

    # ------------------------------------------------------------ rows

    def _record_at_index(self, index: int) -> Optional[DeviceRecord]:
        if 0 <= index < len(self.records):
            return self.records[index]
        return None

    def _set_row_items(self, row: int, record: DeviceRecord) -> None:
        self._updating_table = True
        try:
            check_item = QTableWidgetItem()
            check_item.setFlags(
                Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable
            )
            check_item.setCheckState(
                Qt.Checked if row in self._checked_rows else Qt.Unchecked
            )
            check_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 0, check_item)

            for i, col in enumerate(COLUMNS[1:], start=1):
                attr = COLUMN_ATTR[col]
                value = str(getattr(record, attr, "") or "")
                item = QTableWidgetItem(value)
                item.setFlags(
                    Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable
                )
                item.setToolTip(value)
                item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                if col in MONO_TABLE_COLUMNS:
                    item.setFont(self._mono_font)
                elif col == "simlock" and value:
                    if value == SIMLOCK_PENDING_LABEL:
                        item.setForeground(QBrush(QColor(WARNING)))
                    elif value in SIMLOCK_COLORS:
                        item.setForeground(QBrush(QColor(SIMLOCK_COLORS[value])))
                    else:
                        item.setForeground(QBrush(QColor(DANGER)))
                elif col == "fmi" and value:
                    if value in FMI_COLORS:
                        item.setForeground(QBrush(QColor(FMI_COLORS[value])))
                    else:
                        item.setForeground(QBrush(QColor(DANGER)))
                elif col == "active" and value:
                    if value in ACTIVE_COLORS:
                        item.setForeground(QBrush(QColor(ACTIVE_COLORS[value])))
                    else:
                        item.setForeground(QBrush(QColor(DANGER)))
                elif col == "mdm" and value:
                    item.setForeground(
                        QBrush(QColor(MDM_COLORS.get(value, DANGER)))
                    )
                self.table.setItem(row, i, item)
        finally:
            self._updating_table = False
        self._resize_row_to_contents(row)

    def _append_row(self, record: DeviceRecord) -> int:
        row = self.table.rowCount()
        self._updating_table = True
        try:
            self.table.insertRow(row)
        finally:
            self._updating_table = False
        self._set_row_items(row, record)
        return row

    def _update_row(
        self, row: int, record: DeviceRecord, *, refresh_detail: bool = True
    ) -> None:
        if 0 <= row < self.table.rowCount():
            self._set_row_items(row, record)
            self._resize_row_to_contents(row)
            self.table.viewport().update()
        if (
            refresh_detail
            and self._selected_row == row
            and self._detail_record is record
        ):
            self._show_record_detail(record)

    def _update_table_headers(self) -> None:
        all_checked = bool(self.records) and len(self._checked_rows) >= len(self.records)
        for i, col in enumerate(COLUMNS):
            if col == "check":
                text = CHECK_ON if all_checked else CHECK_OFF
            else:
                text = COLUMN_LABELS[col]
                if self._sort_section == i:
                    text += " ▲" if self._sort_ascending else " ▼"
            item = self.table.horizontalHeaderItem(i)
            if item is None:
                item = QTableWidgetItem(text)
                self.table.setHorizontalHeaderItem(i, item)
            else:
                item.setText(text)

    def _update_check_header(self) -> None:
        self._update_table_headers()

    def _record_row_key(self, record: DeviceRecord) -> int | str:
        return record.id if record.id is not None else id(record)

    def _record_search_blob(self, record: DeviceRecord) -> str:
        parts: list[str] = []
        for col in COLUMNS:
            if col == "check":
                continue
            attr = COLUMN_ATTR[col]
            parts.append(str(getattr(record, attr, "") or ""))
        if record.note:
            parts.append(record.note)
        return " ".join(parts).lower()

    def _record_matches_filters(self, record: DeviceRecord) -> bool:
        if self._search_text:
            if self._search_text not in self._record_search_blob(record):
                return False
        if self._filter_simlock != FILTER_ALL and (record.simlock or "") != self._filter_simlock:
            return False
        if self._filter_fmi != FILTER_ALL and (record.fmi or "") != self._filter_fmi:
            return False
        if self._filter_active != FILTER_ALL and (record.active or "") != self._filter_active:
            return False
        return True

    def _apply_table_filter(self) -> None:
        visible = 0
        for row, record in enumerate(self.records):
            show = self._record_matches_filters(record)
            self.table.setRowHidden(row, not show)
            if show:
                visible += 1
        total = len(self.records)
        if hasattr(self, "_filter_count_label"):
            if (
                self._search_text
                or self._filter_simlock != FILTER_ALL
                or self._filter_fmi != FILTER_ALL
                or self._filter_active != FILTER_ALL
            ):
                self._filter_count_label.setText(f"{visible}/{total} dòng")
            else:
                self._filter_count_label.setText(f"{total} dòng" if total else "")

    def _on_search_text_changed(self, text: str) -> None:
        self._search_text = text.strip().lower()
        self._search_timer.start()

    def _on_simlock_filter_changed(self, value: str) -> None:
        self._filter_simlock = value
        self._apply_table_filter()

    def _on_fmi_filter_changed(self, value: str) -> None:
        self._filter_fmi = value
        self._apply_table_filter()

    def _on_active_filter_changed(self, value: str) -> None:
        self._filter_active = value
        self._apply_table_filter()

    def _clear_table_filters(self) -> None:
        self._search_text = ""
        self._filter_simlock = FILTER_ALL
        self._filter_fmi = FILTER_ALL
        self._filter_active = FILTER_ALL
        self._search_input.blockSignals(True)
        self._search_input.clear()
        self._search_input.blockSignals(False)
        self._filter_simlock_combo.setCurrentText(FILTER_ALL)
        self._filter_fmi_combo.setCurrentText(FILTER_ALL)
        self._filter_active_combo.setCurrentText(FILTER_ALL)
        self._apply_table_filter()

    def _sort_value(self, record: DeviceRecord, col: str) -> str:
        attr = COLUMN_ATTR[col]
        return str(getattr(record, attr, "") or "").lower()

    def _sort_table_by_section(self, section: int) -> None:
        col = COLUMNS[section]
        if col == "check":
            return
        if self._sort_section == section:
            self._sort_ascending = not self._sort_ascending
        else:
            self._sort_section = section
            self._sort_ascending = True

        checked_keys = {
            self._record_row_key(self.records[i])
            for i in self._checked_rows
            if 0 <= i < len(self.records)
        }
        selected_key: int | str | None = None
        if self._selected_row is not None and 0 <= self._selected_row < len(self.records):
            selected_key = self._record_row_key(self.records[self._selected_row])

        reverse = not self._sort_ascending
        self.records.sort(key=lambda rec: self._sort_value(rec, col), reverse=reverse)

        self._updating_table = True
        try:
            self.table.setRowCount(0)
            self._checked_rows.clear()
            for record in self.records:
                row = self._append_row(record)
                if self._record_row_key(record) in checked_keys:
                    self._checked_rows.add(row)
                    item = self.table.item(row, 0)
                    if item is not None:
                        item.setCheckState(Qt.Checked)
        finally:
            self._updating_table = False

        if selected_key is not None:
            for i, record in enumerate(self.records):
                if self._record_row_key(record) == selected_key:
                    self.table.selectRow(i)
                    self._selected_row = i
                    self._show_record_detail(record)
                    break

        self._update_table_headers()
        self._resize_all_columns_to_contents()
        self._apply_table_filter()

    # -------------------------------------------------------- interactions

    def _on_header_clicked(self, section: int) -> None:
        if section == 0:
            if not self.records:
                return
            select_all = len(self._checked_rows) < len(self.records)
            self._checked_rows = set(range(len(self.records))) if select_all else set()
            self._updating_table = True
            try:
                for row in range(self.table.rowCount()):
                    item = self.table.item(row, 0)
                    if item is not None:
                        item.setCheckState(Qt.Checked if select_all else Qt.Unchecked)
            finally:
                self._updating_table = False
            self._update_table_headers()
            self._db_persist_all_checked(select_all)
            n = len(self._checked_rows)
            self._set_status(f"Đã chọn tất cả ({n})" if n else "Đã bỏ chọn tất cả")
            return
        self._sort_table_by_section(section)

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._updating_table:
            return
        row, col = item.row(), item.column()
        record = self._record_at_index(row)
        if record is None:
            return

        if col == 0:
            modifiers = QApplication.keyboardModifiers()
            if modifiers & (Qt.ShiftModifier | Qt.ControlModifier | Qt.MetaModifier):
                # Qt tự toggle ô ☑ trước — hoàn tác; _on_selection_changed xử lý tick.
                self._updating_table = True
                try:
                    revert = (
                        Qt.Unchecked
                        if item.checkState() == Qt.Checked
                        else Qt.Checked
                    )
                    item.setCheckState(revert)
                finally:
                    self._updating_table = False
                return
            checked = item.checkState() == Qt.Checked
            if checked:
                self._checked_rows.add(row)
            else:
                self._checked_rows.discard(row)
            self._check_anchor_row = row
            self._update_check_header()
            if record.id is not None:
                self._db_persist_checked(record.id, checked)
            n = len(self._checked_rows)
            self._set_status(f"Đã chọn {n} dòng" if n else "Đã bỏ chọn")
            return

        col_key = COLUMNS[col]
        attr = COLUMN_ATTR[col_key]
        new_value = item.text().strip()
        old_value = str(getattr(record, attr, "") or "")
        if new_value == old_value:
            return
        setattr(record, attr, new_value)
        if item.text() != new_value:
            self._updating_table = True
            try:
                item.setText(new_value)
            finally:
                self._updating_table = False
        if self._selected_row == row:
            self._show_record_detail(record)
        self._db_save_record(record)
        self._set_status(f"Đã cập nhật {COLUMN_LABELS.get(col_key, col_key)}")

    def _on_selection_changed(self) -> None:
        modifiers = QApplication.keyboardModifiers()
        shift = bool(modifiers & Qt.ShiftModifier)
        ctrl = bool(modifiers & (Qt.ControlModifier | Qt.MetaModifier))

        rows = {index.row() for index in self.table.selectedIndexes()}

        if ctrl:
            added = rows - self._prev_selected_rows
            removed = self._prev_selected_rows - rows
            if added or removed:
                for row in added:
                    self._apply_row_checked(row, True)
                for row in removed:
                    self._apply_row_checked(row, False)
                self._update_check_header()
                n = len(self._checked_rows)
                self._set_status(f"Đã chọn {n} dòng" if n else "Đã bỏ chọn")
            if rows:
                self._check_anchor_row = min(rows)
        elif shift and rows:
            anchor = self._check_anchor_for_range()
            end = max(rows)
            self._apply_checked_range(min(anchor, end), max(anchor, end), True)
        elif rows:
            self._check_anchor_row = min(rows)

        self._prev_selected_rows = set(rows)

        if not rows:
            self._selected_row = None
            self._show_record_detail(None)
            return
        self._selected_row = min(rows)
        self._show_record_detail(self._record_at_index(self._selected_row))

    def _apply_row_checked(self, row: int, checked: bool, *, persist: bool = True) -> None:
        if not (0 <= row < self.table.rowCount()):
            return
        if checked:
            self._checked_rows.add(row)
        else:
            self._checked_rows.discard(row)
        item = self.table.item(row, 0)
        if item is not None and (item.checkState() == Qt.Checked) != checked:
            self._updating_table = True
            try:
                item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
            finally:
                self._updating_table = False
        if persist:
            record = self._record_at_index(row)
            if record is not None and record.id is not None:
                self._db_persist_checked(record.id, checked)

    def _apply_checked_range(self, start: int, end: int, checked: bool) -> None:
        lo, hi = min(start, end), max(start, end)
        self._updating_table = True
        try:
            for r in range(lo, hi + 1):
                if checked:
                    self._checked_rows.add(r)
                else:
                    self._checked_rows.discard(r)
                item = self.table.item(r, 0)
                if item is not None:
                    item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        finally:
            self._updating_table = False
        for r in range(lo, hi + 1):
            record = self._record_at_index(r)
            if record is not None and record.id is not None:
                self._db_persist_checked(record.id, checked)
        self._update_check_header()
        span = hi - lo + 1
        state = "tick" if checked else "bỏ tick"
        self._set_status(f"Đã {state} {span} dòng ({lo + 1}–{hi + 1})")

    def _check_anchor_for_range(self) -> int:
        if self._check_anchor_row is not None:
            return self._check_anchor_row
        if self._prev_selected_rows:
            return min(self._prev_selected_rows)
        if self._selected_row is not None:
            return self._selected_row
        return 0

    def _checked_records(self) -> list[DeviceRecord]:
        return [
            self.records[i]
            for i in sorted(self._checked_rows)
            if 0 <= i < len(self.records)
        ]

    # ------------------------------------------------------- settings/license

    def _open_settings(self) -> None:
        self.settings = AppSettings.load()
        open_settings_dialog(self, self.settings, self._on_settings_saved)

    def _on_settings_saved(self, settings: AppSettings) -> None:
        self.settings = settings
        self._apply_table_columns()
        self._set_status("Đã lưu cài đặt")

    def _open_license(self) -> None:
        open_license_dialog(
            self,
            on_changed=self._refresh_license_badge,
            on_logout=self._handle_account_logout,
        )

    def _handle_account_logout(self) -> None:
        """Sau đăng xuất: đóng phiên làm việc, bắt đăng nhập lại hoặc thoát app."""
        self._refresh_license_badge()
        self.hide()
        if not show_login_dialog(None):
            QApplication.instance().quit()
            return
        self._refresh_license_badge()
        self.showMaximized()
        self.raise_()
        self.activateWindow()

    def _open_free_simlock_dialog(self) -> None:
        open_free_simlock_dialog(
            self,
            on_check_checked=self._check_simlock_checked,
            on_check_all=self._check_simlock_all,
            post_to_main=self._post,
        )

    def _open_services(self) -> None:
        open_services_dialog(
            self,
            on_synced=self._refresh_license_badge,
            get_checked_records=self._checked_records,
            on_run_started=self._on_services_run_started,
            on_run_finished=self._on_services_run_finished,
            on_record_result=self._on_batch_record_done,
            on_run_complete=self._refresh_license_badge,
            on_analyze=self._analyze_active_records,
            enqueue_orders=self._enqueue_orders,
            post_to_main=self._post,
        )

    def _build_order_sync(self) -> OrderSyncEngine:
        """Engine nền: gửi đơn chờ + lấy kết quả mỗi 5 giây. App chỉ get/post server."""
        return OrderSyncEngine(
            records_provider=lambda: list(self.records),
            on_record_result=lambda record: self._post(
                lambda r=record: self._on_order_result(r)
            ),
            on_progress=lambda message: self._post(
                lambda m=message: self._set_status(m)
            ),
        )

    def _start_order_sync(self) -> None:
        """Khởi động engine khi mở app — tự resume đơn status 1 (gửi) và 2 (lấy về)."""
        if not load_api_config().enabled:
            return
        pending = self.db.load_app_orders(statuses=(1, 2))
        if pending:
            log_start("Tiếp tục đơn IMEI", f"{len(pending)} đơn chưa xong")
            self._set_status(
                f"Đang tiếp tục {len(pending)} đơn IMEI chưa xong…"
            )
        self._order_sync.start()

    def _on_order_result(self, record: DeviceRecord) -> None:
        """Một đơn đã có kết quả từ server (done/denied) — cập nhật bảng + DB."""
        self._on_batch_record_done(record)
        self._refresh_license_badge()

    def _enqueue_orders(
        self,
        records: list[DeviceRecord],
        service_ids: list[int],
        service_names: dict[int, str],
    ) -> int:
        """Đẩy đơn IMEI vào engine nền (dùng bởi hộp thoại Dịch vụ)."""
        return self._order_sync.enqueue(
            records, service_ids, service_names=service_names
        )

    def _record_has_pending_orders(self, record: DeviceRecord) -> bool:
        """Còn đơn status 1/2 cho dòng này → giữ nhấp nháy."""
        if record.id is None:
            return False
        pending = self.db.load_app_orders(statuses=(1, 2))
        return any(row.device_record_id == record.id for row in pending)

    def _on_batch_record_done(self, record: DeviceRecord) -> None:
        if record not in self.records:
            return
        row_index = self.records.index(record)
        self._db_save_record(record)
        self._update_row(row_index, record)
        if not self._record_has_pending_orders(record):
            self._stop_simlock_row_flash(row_index)

    def _apply_note_analysis(self, record: DeviceRecord) -> bool:
        """Sau run dịch vụ: chỉ cập nhật cột check từ ghi chú."""
        return apply_parsed_check_fields_from_note(record)

    def _analyze_active_records(self, records: list[DeviceRecord]) -> int:
        updated = 0
        active = [r for r in records if r in self.records]
        if not active:
            self._set_status("Phân tích: không có dòng hợp lệ")
            return 0

        server_changed = apply_server_parsed_to_records(active)
        for record in active:
            old_serial = (record.serial or "").strip()
            old_imei2 = (record.imei2 or "").strip()
            local_changed = apply_parsed_fields_to_record(record)
            if not (local_changed or id(record) in server_changed):
                continue
            row_index = self.records.index(record)
            if (
                (record.serial or "").strip() != old_serial
                or (record.imei2 or "").strip() != old_imei2
            ):
                snap = DeviceRecord(
                    serial=old_serial,
                    imei1=record.imei1,
                    imei2=old_imei2,
                    device_udid=record.device_udid,
                )
                self._unregister_record(snap, keep_usb_seen=True)
                self._register_record(record)
            self._db_save_record(record)
            self._update_row(row_index, record)
            updated += 1
        if updated:
            log_action(
                f"Phân tích: cập nhật từ server + ghi chú — {updated} dòng"
            )
            self._set_status(
                f"Phân tích: đã cập nhật {updated} dòng (server parsed + ghi chú)"
            )
        else:
            self._set_status(
                "Phân tích: không có trường mới (chưa có đơn xong trên server?)"
            )
        return updated

    def _on_services_run_started(self, records: list[DeviceRecord]) -> None:
        for record in records:
            if record not in self.records:
                continue
            self._start_simlock_row_flash(self.records.index(record))

    def _on_services_run_finished(
        self,
        results: list[tuple[DeviceRecord, AutoServicesResult]],
    ) -> None:
        if not results:
            self._set_status("Run dịch vụ: không có kết quả")
            return

        total_lines = 0
        total_ok = 0
        for record, outcome in results:
            if record not in self.records:
                continue
            row_index = self.records.index(record)
            self._stop_simlock_row_flash(row_index)
            if outcome.lines:
                self._db_save_record(record)
                self._update_row(row_index, record)
                total_lines += len(outcome.lines)
                total_ok += sum(1 for line in outcome.lines if line.ok)

        self._set_status(f"Run dịch vụ: {total_ok}/{total_lines} thành công")

    # ------------------------------------------------------------- USB

    def _on_usb_unplug(self, udid: str) -> None:
        log_action("USB: đã rút thiết bị")
        self._set_status(
            "Đã rút thiết bị — dữ liệu giữ trong bảng. Cắm lại để cập nhật."
        )

    def _start_usb_monitor(self) -> None:
        log_start("Giám sát USB")

        def loop() -> None:
            while not self._usb_stop.is_set():
                try:
                    self.monitor.poll_once()
                except Exception:
                    logger.exception("USB poll error")
                self._usb_stop.wait(1.5)

        self._usb_thread = threading.Thread(target=loop, name="usb-monitor", daemon=True)
        self._usb_thread.start()

    def _undismiss_usb(self, udid: str) -> None:
        try:
            self.db.undismiss_usb(udid)
        except Exception:
            logger.exception("Bỏ dismiss USB thất bại")

    def _on_usb_record(self, record: DeviceRecord) -> None:
        if not self._add_record(record):
            return
        label = record.model or record.serial or record.imei1 or "thiết bị"
        log_done("Đọc USB", label)
        if self.settings.auto_check_simlock:
            self._auto_simlock_on_usb_plug(record)
        self._auto_services_on_usb_plug(record)

    def _auto_services_on_usb_plug(self, record: DeviceRecord) -> None:
        prefs = load_auto_service_prefs()
        if not prefs.enabled or not prefs.service_ids:
            return
        if record.source != "USB":
            return
        if not load_api_config().enabled:
            return
        if not (record.imei1 or record.imei2 or record.serial):
            return
        row_index = self._find_usb_row_index(record.device_udid or "")
        if row_index is None and record in self.records:
            row_index = self.records.index(record)
        if row_index is None:
            return

        label = record.model or record.serial or record.imei1 or "thiết bị"

        # Tách simlock (endpoint riêng, chạy đồng bộ) khỏi đơn IMEI (qua engine nền).
        simlock_ids: list[int] = []
        order_ids: list[int] = []
        service_names: dict[int, str] = {}
        for sid in prefs.service_ids:
            svc = find_service_by_id(sid)
            if svc is not None:
                if svc.is_save_imei:
                    continue
                service_names[sid] = svc.name
                if svc.is_simlock:
                    simlock_ids.append(sid)
                    continue
            order_ids.append(sid)

        if not simlock_ids and not order_ids:
            return

        self._start_simlock_row_flash(row_index)
        log_start("Dịch vụ tự động USB", label)
        self._show_server_sync_status(
            f"Đang chạy {len(simlock_ids) + len(order_ids)} dịch vụ cho {label}…"
        )

        if order_ids:
            self._order_sync.enqueue(
                [record], order_ids, service_names=service_names
            )

        if not simlock_ids:
            return

        def work() -> None:
            try:
                outcome = run_auto_services(record, list(simlock_ids))
            except Exception:
                logger.exception("Auto services failed")
                outcome = None

            def apply() -> None:
                if outcome is None:
                    self._stop_simlock_row_flash(row_index)
                    self._show_server_sync_status(f"Dịch vụ tự động {label}: lỗi không xác định")
                    return
                self._on_services_run_finished([(record, outcome)])
                self._refresh_license_badge()
                if outcome.lines:
                    ok_count = sum(1 for line in outcome.lines if line.ok)
                    log_done(
                        "Dịch vụ tự động USB",
                        f"{label} — {ok_count}/{len(outcome.lines)} OK",
                    )
                    self._show_server_sync_status(
                        f"Dịch vụ {label}: {ok_count}/{len(outcome.lines)} xong — xem Ghi chú"
                    )

            self._post(apply)

        threading.Thread(
            target=work,
            daemon=True,
            name=f"auto-services-{row_index}",
        ).start()

    def _auto_simlock_on_usb_plug(self, record: DeviceRecord) -> None:
        if record.source != "USB" or not self._simlock_eligible(record):
            return
        if not load_api_config().enabled:
            return
        if get_simlock_quota()[2] <= 0:
            return
        record.simlock = ""
        row_index = self._find_usb_row_index(record.device_udid or "")
        if row_index is None and record in self.records:
            row_index = self.records.index(record)
        if row_index is not None:
            self._update_row(row_index, record)
            self._run_simlock_check(row_index, record)

    # ----------------------------------------------------------- simlock

    def _start_simlock_row_flash(self, row: int) -> None:
        if 0 <= row < len(self.records):
            self._update_row(row, self.records[row])
        self._simlock_flash_rows[row] = True
        if not self._simlock_flash_timer.isActive():
            self._simlock_flash_timer.start()
        self._paint_simlock_row(row, bright=True)

    def _simlock_flash_tick(self) -> None:
        if not self._simlock_flash_rows:
            self._simlock_flash_timer.stop()
            return
        for row in list(self._simlock_flash_rows):
            bright = not self._simlock_flash_rows[row]
            self._simlock_flash_rows[row] = bright
            self._paint_simlock_row(row, bright=bright)

    def _paint_simlock_row(self, row: int, *, bright: bool) -> None:
        if row < 0 or row >= self.table.rowCount():
            return
        self._updating_table = True
        try:
            for col in range(self.table.columnCount()):
                item = self.table.item(row, col)
                if item is None:
                    continue
                if bright:
                    item.setBackground(QBrush(FLASH_BG_HI))
                else:
                    item.setBackground(QBrush())
        finally:
            self._updating_table = False

    def _stop_simlock_row_flash(self, row: int) -> None:
        self._simlock_flash_rows.pop(row, None)
        if not self._simlock_flash_rows:
            self._simlock_flash_timer.stop()
        if 0 <= row < len(self.records):
            self._update_row(row, self.records[row])

    def _stop_all_simlock_flash(self) -> None:
        for row in list(self._simlock_flash_rows):
            self._stop_simlock_row_flash(row)

    def _begin_simlock_pending_ui(self, row: int, record: DeviceRecord) -> None:
        record.simlock = SIMLOCK_PENDING_LABEL
        self._update_row(row, record)
        self._start_simlock_row_flash(row)

    def _simlock_eligible(self, record: DeviceRecord) -> bool:
        return bool(record.serial.strip() and record.imei1.strip())

    def _check_simlock_checked(self) -> None:
        pairs = [
            (i, self.records[i])
            for i in sorted(self._checked_rows)
            if 0 <= i < len(self.records)
        ]
        if not pairs:
            QMessageBox.information(
                self,
                "Check Lock Quốc Tế Miễn Free",
                "Chưa tick dòng nào. Tick ☑ rồi chọn lại.",
            )
            return
        self._start_simlock_checks(pairs)

    def _check_simlock_all(self) -> None:
        if not self.records:
            QMessageBox.information(
                self, "Check Lock Quốc Tế Miễn Free", "Bảng đang trống."
            )
            return
        self._start_simlock_checks(list(enumerate(self.records)))

    def _start_simlock_checks(
        self, indexed_records: list[tuple[int, DeviceRecord]]
    ) -> None:
        if not load_api_config().enabled:
            QMessageBox.warning(
                self,
                "Check Lock Quốc Tế Miễn Free",
                "Chưa cấu hình email và API token (Cài đặt → Tài khoản API).",
            )
            return

        eligible = [(i, r) for i, r in indexed_records if self._simlock_eligible(r)]
        skipped = len(indexed_records) - len(eligible)

        if not eligible:
            QMessageBox.warning(
                self,
                "Check Lock Quốc Tế Miễn Free",
                "Không có dòng hợp lệ. Cần đủ IMEI 1 và Serial Number "
                "(nên có thêm IMEI 2 nếu máy có).",
            )
            return

        _limit, _used, remaining = get_simlock_quota()
        if remaining <= 0:
            QMessageBox.warning(
                self,
                "Check Lock Quốc Tế Miễn Free",
                f"Hết lượt check miễn phí ({_used}/{_limit}).\n"
                "Dùng dịch vụ có phí (Dịch vụ → Dịch vụ khác) hoặc liên hệ admin.",
            )
            return

        if skipped:
            self._set_status(
                f"Check simlock: {len(eligible)} dòng, "
                f"bỏ qua {skipped} dòng thiếu IMEI 1/Serial"
            )

        log_start("Check simlock", f"{len(eligible)} dòng")
        for row_index, record in eligible:
            self._run_simlock_check(row_index, record)

    def _run_simlock_check(self, row_index: int, record: DeviceRecord) -> None:
        self._begin_simlock_pending_ui(row_index, record)
        label = record.serial or record.imei1 or f"dòng {row_index + 1}"
        log_start("Check simlock", label)

        def work() -> None:
            result = None
            try:
                result = fetch_simlock(record)
            except Exception:
                logger.exception("Kiểm tra simlock thất bại")

            def apply() -> None:
                if record not in self.records:
                    return
                current_index = self.records.index(record)
                self._stop_simlock_row_flash(current_index)
                label = record.model or record.serial or record.imei1 or "thiết bị"

                if result is None:
                    if record.simlock == SIMLOCK_PENDING_LABEL:
                        record.simlock = ""
                        self._update_row(current_index, record)
                    log_error(f"Check simlock {label}: lỗi không xác định")
                    return

                if not result.ok:
                    record.simlock = ""
                    self._update_row(current_index, record)
                    log_done("Check simlock", f"{label} — {result.message}")
                    self._show_server_sync_status(f"Simlock {label}: {result.message}")
                    return

                simlock_value = (result.simlock or "").strip() or SIMLOCK_UNKNOWN_LABEL
                record.simlock = simlock_value
                self._db_save_record(record)
                self._update_row(current_index, record)

                self._refresh_license_badge()
                quota = (
                    f"{result.simlock_used}/{result.simlock_count}"
                    if result.simlock_count
                    else ""
                )
                log_done("Check simlock", f"{label} — {simlock_value}")
                extra = f" — còn {result.simlock_remaining} lượt" if quota else ""
                self._show_server_sync_status(
                    f"Simlock {label}: {simlock_value} (Albert {quota}{extra})"
                )

            self._post(apply)

        threading.Thread(
            target=work,
            daemon=True,
            name=f"simlock-check-{row_index}",
        ).start()

    # ----------------------------------------------------------- database

    def _db_save_record(
        self,
        record: DeviceRecord,
        *,
        is_checked: Optional[bool] = None,
    ) -> None:
        try:
            if record.id is None:
                self.db.insert(
                    record,
                    sort_order=len(self.records) - 1,
                    is_checked=bool(is_checked),
                )
            else:
                self.db.update(record, is_checked=is_checked)
        except Exception:
            logger.exception("Lưu SQLite thất bại")

    def _db_persist_checked(self, record_id: int, is_checked: bool) -> None:
        try:
            self.db.update_checked(record_id, is_checked)
        except Exception:
            logger.exception("Lưu trạng thái tick SQLite thất bại")

    def _db_persist_all_checked(self, is_checked: bool) -> None:
        try:
            self.db.update_all_checked(is_checked)
        except Exception:
            logger.exception("Lưu tick tất cả SQLite thất bại")

    def _load_from_database(self) -> None:
        try:
            rows = self.db.load_all()
        except Exception:
            logger.exception("Đọc SQLite thất bại")
            QMessageBox.warning(
                self,
                "Dữ liệu cục bộ",
                "Không đọc được dữ liệu đã lưu. Bảng bắt đầu trống.",
            )
            return

        if not rows:
            return

        dismissed = self.db.load_dismissed_usb()
        loaded = 0

        for record, checked in rows:
            if not record.has_data():
                continue

            udid = (record.device_udid or "").strip()
            if udid and udid in dismissed:
                continue

            self._register_record(record)
            idx = len(self.records)
            self.records.append(record)
            if checked:
                self._checked_rows.add(idx)
            loaded += 1

        for i, record in enumerate(self.records):
            self._append_row(record)

        self._update_check_header()
        if loaded:
            self._resize_all_columns_to_contents()
            self._apply_table_filter()
            self._set_status(f"Đã tải {loaded} dòng từ bộ nhớ cục bộ")

    # ------------------------------------------------------------- dedupe

    def _is_duplicate(self, record: DeviceRecord) -> bool:
        if record.dedupe_key in self._dedupe_keys:
            return True
        if record.serial and f"serial:{record.serial.upper()}" in self._dedupe_keys:
            return True
        return False

    def _register_record(self, record: DeviceRecord) -> None:
        self._dedupe_keys.add(record.dedupe_key)
        if record.serial:
            key = record.serial.upper()
            self._dedupe_keys.add(f"serial:{key}")
            self.monitor._completed_serials.add(key)
            if record.device_udid:
                self.monitor._udid_serial[record.device_udid] = key
        if record.imei1:
            self._dedupe_keys.add(f"imei:{record.imei1}")
        if record.device_udid:
            self.monitor._completed_udids.add(record.device_udid)

    def _unregister_record(self, record: DeviceRecord, *, keep_usb_seen: bool = False) -> None:
        """Bỏ khóa trùng lặp. Giữ USB đã đọc khi user xóa dòng — tránh tự đọc lại."""
        self._dedupe_keys.discard(record.dedupe_key)
        if record.serial:
            key = record.serial.upper()
            self._dedupe_keys.discard(f"serial:{key}")
            if not keep_usb_seen:
                self.monitor._completed_serials.discard(key)
        if record.imei1:
            self._dedupe_keys.discard(f"imei:{record.imei1}")
        if record.device_udid:
            if not keep_usb_seen:
                self.monitor._completed_udids.discard(record.device_udid)
                self.monitor._udid_serial.pop(record.device_udid, None)

    def _find_usb_row_index(self, udid: str) -> Optional[int]:
        if not udid:
            return None
        for i, row in enumerate(self.records):
            if row.device_udid == udid:
                return i
        return None

    # ---------------------------------------------------------- add/remove

    def _add_record(self, record: DeviceRecord, *, force: bool = False) -> bool:
        if not record.has_data():
            QMessageBox.warning(
                self, "Không có dữ liệu", "Không tìm thấy IMEI/Serial/Model."
            )
            return False

        # USB cắm lại: cập nhật dòng cũ (cùng UDID), không xóa khi rút cáp
        if record.source == "USB" and record.device_udid:
            existing = self._find_usb_row_index(record.device_udid)
            if existing is None:
                stored = self.db.find_record_by_udid(record.device_udid)
                if stored is not None:
                    old_record, _old_checked = stored
                    record.id = old_record.id
                    if old_record.condition:
                        record.condition = old_record.condition
                    record.simlock = old_record.simlock
                    record.fmi = record.fmi or old_record.fmi
                    record.active = record.active or old_record.active
                    record.carrier = record.carrier or old_record.carrier

            if existing is not None:
                old = self.records[existing]
                self._dedupe_keys.discard(old.dedupe_key)
                if old.serial:
                    self._dedupe_keys.discard(f"serial:{old.serial.upper()}")
                if old.imei1:
                    self._dedupe_keys.discard(f"imei:{old.imei1}")
                record.id = old.id
                record.condition = old.condition
                record.simlock = old.simlock
                record.note = merge_notes(old.note, record.note)
                record.fmi = record.fmi or old.fmi
                record.active = record.active or old.active
                record.carrier = record.carrier or old.carrier
                self.records[existing] = record
                self._register_record(record)
                self._db_save_record(record)
                self._update_row(existing, record)
                self.table.selectRow(existing)
                self._selected_row = existing
                self._show_record_detail(record)
                label = record.model or record.serial or record.imei1
                self._set_status(f"Đã cập nhật: {label}")
                return True

        if not force and self._is_duplicate(record):
            self._set_status(f"Bỏ qua trùng: {record.serial or record.imei1}")
            return False

        self._register_record(record)
        self.records.append(record)
        self._db_save_record(record)
        row = self._append_row(record)
        self._apply_table_filter()
        self.table.selectRow(row)
        self.table.scrollToItem(self.table.item(row, 1))
        self._selected_row = row
        self._show_record_detail(record)
        label = record.model or record.serial or record.imei1
        self._set_status(f"Đã thêm: {label}")
        return True

    def _remove_rows_at_indices(self, indices: list[int]) -> int:
        if not indices:
            return 0
        deleted_count = 0
        self._stop_all_simlock_flash()
        for idx in sorted(indices, reverse=True):
            if 0 <= idx < self.table.rowCount():
                self._updating_table = True
                try:
                    self.table.removeRow(idx)
                finally:
                    self._updating_table = False
            if 0 <= idx < len(self.records):
                removed = self.records.pop(idx)
                if removed.id is not None:
                    try:
                        self.db.delete(removed.id)
                        deleted_count += 1
                    except Exception:
                        logger.exception("Xóa SQLite thất bại")
                else:
                    deleted_count += 1
                self._unregister_record(removed, keep_usb_seen=bool(removed.device_udid))
                if removed.device_udid:
                    self.monitor.dismiss_udid(removed.device_udid)
                    try:
                        self.db.dismiss_usb(removed.device_udid)
                    except Exception:
                        logger.exception("Lưu dismiss USB thất bại")
                    self.monitor._tracked.pop(removed.device_udid, None)

        remaining_checks: set[int] = set()
        for old_idx in self._checked_rows:
            if old_idx in indices:
                continue
            shift = sum(1 for d in indices if d < old_idx)
            remaining_checks.add(old_idx - shift)
        self._checked_rows = remaining_checks
        self._update_check_header()

        self._selected_row = None
        rows = {index.row() for index in self.table.selectedIndexes()}
        if rows:
            self._selected_row = min(rows)
            self._show_record_detail(self._record_at_index(self._selected_row))
        else:
            self._show_record_detail(None)

        return deleted_count

    def _show_table_menu(self, pos) -> None:
        menu = QMenu(self.table)
        delete_action = menu.addAction(f"Xóa dòng đã tick ({len(self._checked_rows)})")
        delete_action.setEnabled(bool(self._checked_rows))
        delete_action.triggered.connect(self._delete_checked)
        clear_action = menu.addAction("Xóa tất cả")
        clear_action.setEnabled(bool(self.records))
        clear_action.triggered.connect(self._clear_all)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _delete_checked(self) -> None:
        indices = sorted(self._checked_rows)
        if not indices:
            QMessageBox.information(self, "Xóa", "Tick chọn ít nhất một dòng cần xóa.")
            return
        answer = QMessageBox.question(
            self, "Xác nhận", f"Xóa {len(indices)} dòng đã tick?"
        )
        if answer != QMessageBox.Yes:
            return
        deleted_count = self._remove_rows_at_indices(indices)
        log_action(f"Xóa {len(indices)} dòng đã tick")
        self._set_status(f"Đã xóa {deleted_count} dòng")

    def _clear_all(self) -> None:
        if not self.records:
            return
        answer = QMessageBox.question(self, "Xác nhận", "Xóa toàn bộ danh sách?")
        if answer != QMessageBox.Yes:
            return
        indices = list(range(len(self.records)))
        deleted_count = self._remove_rows_at_indices(indices)
        self._stop_all_simlock_flash()
        self._update_check_header()
        self._selected_row = None
        self._show_record_detail(None)
        log_action("Xóa toàn bộ danh sách")
        self._set_status(f"Đã xóa {deleted_count} dòng")

    # ----------------------------------------------------------- import

    def _open_image_dialog(self) -> None:
        existing = getattr(self, "_image_dialog", None)
        if existing is not None and existing.isVisible():
            existing.raise_()
            existing.activateWindow()
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Đọc từ ảnh (OCR)")
        dialog.setMinimumSize(480, 360)
        dialog.resize(560, 420)
        self._image_dialog = dialog
        ocr_image: list[Optional[Image.Image]] = [None]

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        hint = QLabel(
            "Chọn ảnh hoặc dán (⌘V) màn hình Cài đặt → Giới thiệu, rồi bấm «Thêm vào bảng»."
        )
        hint.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        pick_row = QHBoxLayout()
        pick_btn = QPushButton("Chọn ảnh…")
        pick_row.addWidget(pick_btn)
        multi_hint = QLabel("(nhiều file → OCR hết và đóng)")
        multi_hint.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        pick_row.addWidget(multi_hint)
        paste_btn = QPushButton("Dán ảnh (⌘V)")
        pick_row.addWidget(paste_btn)
        pick_row.addStretch(1)
        layout.addLayout(pick_row)

        preview = QLabel("(Chưa có ảnh)")
        preview.setAlignment(Qt.AlignCenter)
        preview.setFrameShape(QFrame.StyledPanel)
        preview.setMinimumHeight(200)
        layout.addWidget(preview, 1)

        action_row = QHBoxLayout()
        action_row.addStretch(1)
        submit_btn = QPushButton("Thêm vào bảng")
        mark_primary(submit_btn)
        submit_btn.setDefault(True)
        action_row.addWidget(submit_btn)
        cancel_btn = QPushButton("Hủy")
        action_row.addWidget(cancel_btn)
        layout.addLayout(action_row)

        def _update_preview() -> None:
            if ocr_image[0] is None:
                preview.setText("(Chưa có ảnh)")
                preview.setPixmap(QPixmap())
                return
            display = ocr_image[0].copy()
            display.thumbnail((960, 240), Image.Resampling.LANCZOS)
            preview.setPixmap(_pil_to_pixmap(display))

        def _pick() -> None:
            paths, _filter = QFileDialog.getOpenFileNames(
                dialog,
                "Chọn ảnh (⌘ để chọn nhiều)",
                "",
                "Ảnh (*.png *.jpg *.jpeg *.webp *.bmp);;Tất cả (*)",
            )
            if not paths:
                return
            added = self._process_image_paths(paths, parent=dialog)
            if added > 0:
                dialog.accept()

        def _paste() -> None:
            try:
                img = clipboard_image()
            except Exception as exc:
                QMessageBox.critical(dialog, "Dán ảnh", str(exc))
                return
            if img is None:
                return
            ocr_image[0] = img.convert("RGB").copy()
            _update_preview()

        def _submit() -> None:
            if ocr_image[0] is None:
                QMessageBox.information(dialog, "Ảnh", "Chọn hoặc dán ảnh trước.")
                return
            if not ocr_available():
                QMessageBox.warning(dialog, "Thiếu OCR", ocr_missing_hint())
                return
            self._set_status("Đang đọc ảnh…")
            QApplication.processEvents()
            try:
                ok, reason = self._ocr_and_add_record(ocr_image[0].copy())
            except Exception as exc:
                QMessageBox.critical(dialog, "OCR lỗi", str(exc))
                return
            if ok:
                self._set_status(f"Đã thêm từ ảnh: {reason}")
                dialog.accept()
                return
            if reason == "duplicate":
                QMessageBox.information(dialog, "Trùng", "Dữ liệu đã có trong bảng.")
                dialog.accept()
                return
            QMessageBox.warning(
                dialog,
                "Không nhận dạng được",
                "Gợi ý: file PNG/JPG gốc, crop sát vùng Cài đặt → Giới thiệu.",
            )

        pick_btn.clicked.connect(_pick)
        paste_btn.clicked.connect(_paste)
        submit_btn.clicked.connect(_submit)
        cancel_btn.clicked.connect(dialog.reject)
        QShortcut(QKeySequence.Paste, dialog, activated=_paste)

        dialog.exec()
        self._image_dialog = None

    def _open_text_dialog(self) -> None:
        existing = getattr(self, "_text_dialog", None)
        if existing is not None and existing.isVisible():
            existing.raise_()
            existing.activateWindow()
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Phân tích văn bản")
        dialog.setMinimumSize(440, 320)
        dialog.resize(560, 400)
        self._text_dialog = dialog

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        hint = QLabel(
            "Dán văn bản từ Cài đặt → Cài đặt chung → Giới thiệu (IMEI, Serial, Model…)."
        )
        hint.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        textbox = QPlainTextEdit()
        textbox.setStyleSheet("font-family: Menlo, monospace; font-size: 12px;")
        layout.addWidget(textbox, 1)
        textbox.setFocus()

        action_row = QHBoxLayout()
        action_row.addStretch(1)
        submit_btn = QPushButton("Thêm vào bảng")
        mark_primary(submit_btn)
        submit_btn.setDefault(True)
        action_row.addWidget(submit_btn)
        cancel_btn = QPushButton("Hủy")
        action_row.addWidget(cancel_btn)
        layout.addLayout(action_row)

        def _submit() -> None:
            text = textbox.toPlainText().strip()
            if not text:
                QMessageBox.information(
                    dialog,
                    "Văn bản",
                    "Dán nội dung từ Cài đặt > Cài đặt chung > Giới thiệu.",
                )
                return
            record = parse_text_to_record(text, source="Dán")
            if not record.has_data():
                QMessageBox.warning(
                    dialog,
                    "Không nhận dạng được",
                    record.note or "Không tìm thấy IMEI/Serial/Model trong văn bản.",
                )
                return
            if self._add_record(record):
                label = record.model or record.serial or record.imei1
                self._set_status(f"Đã thêm từ văn bản: {label}")
            else:
                QMessageBox.information(dialog, "Trùng", "Dữ liệu đã có trong bảng.")
            dialog.accept()

        submit_btn.clicked.connect(_submit)
        cancel_btn.clicked.connect(dialog.reject)

        dialog.exec()
        self._text_dialog = None

    def _open_add_lines_dialog(self) -> None:
        existing = getattr(self, "_add_lines_dialog", None)
        if existing is not None and existing.isVisible():
            existing.raise_()
            existing.activateWindow()
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Thêm theo từng dòng")
        dialog.setMinimumSize(480, 360)
        dialog.resize(580, 460)
        self._add_lines_dialog = dialog

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        hint = QLabel(LINE_IMPORT_HINT)
        hint.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        textbox = QPlainTextEdit()
        textbox.setStyleSheet("font-family: Menlo, monospace; font-size: 12px;")
        layout.addWidget(textbox, 1)
        textbox.setFocus()

        action_row = QHBoxLayout()
        action_row.addStretch(1)
        submit_btn = QPushButton("Thêm vào bảng")
        mark_primary(submit_btn)
        submit_btn.setDefault(True)
        action_row.addWidget(submit_btn)
        cancel_btn = QPushButton("Hủy")
        action_row.addWidget(cancel_btn)
        layout.addLayout(action_row)

        def _submit() -> None:
            text = textbox.toPlainText().strip()
            if not text:
                QMessageBox.information(
                    dialog,
                    "Thêm dòng",
                    "Nhập mỗi dòng theo dạng:\n  IMEI1  IMEI2  Serial\n"
                    "(các trường cách nhau bằng dấu cách)",
                )
                return
            added = self._commit_bulk_lines(text, parent=dialog)
            if added > 0:
                dialog.accept()

        submit_btn.clicked.connect(_submit)
        cancel_btn.clicked.connect(dialog.reject)

        dialog.exec()
        self._add_lines_dialog = None

    def _commit_bulk_lines(self, text: str, *, parent: Optional[QWidget] = None) -> int:
        """Parse và thêm các dòng; trả số dòng đã thêm thành công."""
        parsed = parse_bulk_lines(text)
        if not parsed:
            QMessageBox.information(
                parent or self,
                "Thêm dòng",
                "Không có dòng hợp lệ (bỏ qua dòng trống và dòng bắt đầu bằng #).",
            )
            return 0

        added = 0
        duplicate = 0
        failed: list[str] = []
        for item in parsed:
            if item.record is None:
                failed.append(f"Dòng {item.line_no}: {item.error}")
                continue
            if self._add_record(item.record):
                added += 1
            else:
                duplicate += 1

        parts = [f"Đã thêm {added} dòng"]
        if duplicate:
            parts.append(f"{duplicate} trùng")
        if failed:
            parts.append(f"{len(failed)} lỗi")
        if added:
            log_action(" · ".join(parts))
        self._set_status(" · ".join(parts))

        if failed and added == 0:
            QMessageBox.warning(
                parent or self,
                "Thêm dòng",
                "Không thêm được dòng nào.\n\n" + "\n".join(failed[:12]),
            )
        elif failed:
            QMessageBox.warning(
                parent or self,
                "Thêm dòng",
                "\n".join(failed[:12]) + ("\n…" if len(failed) > 12 else ""),
            )
        return added

    def _process_image_paths(
        self, paths: list[str], *, parent: Optional[QWidget] = None
    ) -> int:
        if not paths:
            return 0
        if not ocr_available():
            QMessageBox.warning(parent or self, "Thiếu OCR", ocr_missing_hint())
            return 0

        total = len(paths)
        added = 0
        no_data = 0
        duplicate = 0
        load_errors: list[str] = []
        ocr_errors: list[str] = []

        for i, path in enumerate(paths, start=1):
            name = Path(path).name
            self._set_status(f"Đang OCR ảnh {i}/{total}: {name}…")
            QApplication.processEvents()
            try:
                image = Image.open(path).convert("RGB")
            except Exception as exc:
                load_errors.append(f"{name}: {exc}")
                continue

            try:
                ok, reason = self._ocr_and_add_record(image)
            except Exception as exc:
                ocr_errors.append(f"{name}: {exc}")
                continue

            if ok:
                added += 1
            elif reason == "duplicate":
                duplicate += 1
            else:
                no_data += 1

        parts = [f"Đã thêm {added}/{total} ảnh"]
        if duplicate:
            parts.append(f"{duplicate} trùng")
        if no_data:
            parts.append(f"{no_data} không đọc được")
        if load_errors:
            parts.append(f"{len(load_errors)} lỗi mở file")
        self._set_status(" · ".join(parts))

        if total == 1 and added == 0 and not load_errors and not ocr_errors:
            QMessageBox.warning(
                parent or self,
                "Không nhận dạng được",
                "Không đọc được IMEI/Serial/Model từ ảnh.\n\n"
                "Gợi ý: file PNG/JPG gốc, crop sát vùng Cài đặt → Giới thiệu.",
            )

        issues: list[str] = []
        if load_errors:
            issues.append("Lỗi mở file:\n" + "\n".join(load_errors[:8]))
        if ocr_errors:
            issues.append("Lỗi OCR:\n" + "\n".join(ocr_errors[:8]))
        if added == 0 and (no_data or duplicate) and not load_errors and not ocr_errors and total > 1:
            issues.append("Không ảnh nào thêm được (không đọc được hoặc trùng dữ liệu).")
        if issues and (added < total or load_errors or ocr_errors):
            extra = ""
            if len(load_errors) + len(ocr_errors) > 8:
                extra = "\n\n(…)"
            QMessageBox.warning(
                parent or self, "Kết quả chọn ảnh", "\n\n".join(issues) + extra
            )

        return added

    def _ocr_and_add_record(self, image: Image.Image) -> tuple[bool, str]:
        """OCR một ảnh và thêm bảng. Trả (thành công, lý do nếu thất bại)."""
        record = parse_image(image, source="Ảnh")
        if not record.has_data():
            return False, "no_data"
        if self._add_record(record):
            return True, record.model or record.serial or record.imei1
        return False, "duplicate"

    # ------------------------------------------------------------- export

    def _pick_export_fields(self, title: str) -> Optional[list[str]]:
        return pick_export_fields(self, title=title)

    def _export_text(self) -> None:
        if not self.records:
            QMessageBox.information(self, "Xuất Text", "Chưa có dữ liệu để xuất.")
            return
        fields = self._pick_export_fields("Xuất Text")
        if not fields:
            return
        default_name = (
            "apple_devices_"
            + self.records[-1].captured_at.replace(":", "-").replace(" ", "_")
            + ".txt"
        )
        path, _filter = QFileDialog.getSaveFileName(
            self, "Lưu file Text", default_name, "Text (*.txt);;Tất cả (*.*)"
        )
        if not path:
            return
        try:
            out = export_records_text(Path(path), self.records, fields)
            log_action(f"Xuất Text: {len(self.records)} dòng, {len(fields)} cột → {out.name}")
            self._set_status(f"Đã xuất Text: {out}")
            _open_file(out)
        except Exception as exc:
            log_error(f"Xuất Text thất bại: {exc}")
            QMessageBox.critical(self, "Xuất Text", str(exc))

    def _export_excel(self) -> None:
        if not self.records:
            QMessageBox.information(self, "Xuất Excel", "Chưa có dữ liệu để xuất.")
            return
        fields = self._pick_export_fields("Xuất Excel")
        if not fields:
            return
        default_name = (
            "apple_devices_"
            + self.records[-1].captured_at.replace(":", "-").replace(" ", "_")
            + ".xlsx"
        )
        path, _filter = QFileDialog.getSaveFileName(
            self, "Lưu file Excel", default_name, "Excel (*.xlsx)"
        )
        if not path:
            return
        try:
            out = export_records(Path(path), self.records, fields)
            log_action(f"Xuất Excel: {len(self.records)} dòng, {len(fields)} cột → {out.name}")
            self._set_status(f"Đã xuất và mở: {out}")
            _open_file(out)
        except Exception as exc:
            log_error(f"Xuất Excel thất bại: {exc}")
            QMessageBox.critical(self, "Xuất Excel", str(exc))

    # -------------------------------------------------------------- print

    def _print_row(self, row_index: int) -> None:
        record = self._record_at_index(row_index)
        if record is None:
            return
        pdf_path = open_print_labels(
            self,
            [record],
            print_fields=self.settings.enabled_print_fields(),
        )
        if pdf_path is not None:
            label = record.imei1 or record.serial or f"dòng {row_index + 1}"
            self._set_status(f"Đã mở PDF nhãn: {label}")

    def _print_selected_detail(self) -> None:
        if self._selected_row is None:
            return
        self._print_row(self._selected_row)

    def _print_checked(self) -> None:
        records = self._checked_records()
        if not records:
            QMessageBox.information(self, "In", "Tick chọn ít nhất một dòng cần in.")
            return
        pdf_path = open_print_labels(
            self,
            records,
            print_fields=self.settings.enabled_print_fields(),
        )
        if pdf_path is not None:
            self._set_status(f"Đã mở PDF ({len(records)} nhãn): {pdf_path}")

    # -------------------------------------------------------------- close

    def closeEvent(self, event) -> None:
        self._usb_stop.set()
        self._status_flash_timer.stop()
        self._simlock_flash_timer.stop()
        try:
            self.db.close()
        except Exception:
            logger.debug("Đóng SQLite", exc_info=True)
        super().closeEvent(event)


def run_app() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    apply_theme(app)
    icon = app_icon_path()
    if icon is not None:
        app.setWindowIcon(QIcon(str(icon)))

    if not show_login_dialog(None):
        return

    window = ImeiToolWindow()
    window.showMaximized()
    app.exec()
