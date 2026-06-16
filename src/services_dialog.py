"""Hộp thoại danh sách dịch vụ — đồng bộ từ Laravel (PySide6)."""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.activity_log import log_done, log_start
from src.api_config import load_api_config
from src.auto_services import (
    AutoServicesResult,
    run_auto_services,
)
from src.models import DeviceRecord
from src.vnd_format import VND_LABEL, format_vnd
from src.license import refresh_license_status
from src.services_store import (
    ServiceItem,
    estimate_services_run,
    find_service_by_id,
    load_services_cache,
    save_auto_service_prefs,
    sync_services_from_server,
)
from src.theme import mark_primary

logger = logging.getLogger(__name__)

RUN_MAX_WORKERS = 5

GetCheckedRecordsFn = Callable[[], list[DeviceRecord]]
OnRunStartedFn = Callable[[list[DeviceRecord]], None]
OnRunFinishedFn = Callable[[list[tuple[DeviceRecord, AutoServicesResult]]], None]
OnRecordResultFn = Callable[[DeviceRecord], None]
OnRunCompleteFn = Callable[[], None]
OnAnalyzeFn = Callable[[list[DeviceRecord]], int]
PostToMainFn = Callable[[Callable[[], None]], None]
# Đẩy đơn IMEI vào engine nền (records, service_ids, {service_id: tên}) → số đơn đã thêm
EnqueueOrdersFn = Callable[[list[DeviceRecord], list[int], dict[int, str]], int]


class ServicesDialog(QDialog):
    def __init__(
        self,
        parent: Optional[QWidget],
        *,
        on_synced: Optional[Callable[[], None]] = None,
        get_checked_records: Optional[GetCheckedRecordsFn] = None,
        on_run_started: Optional[OnRunStartedFn] = None,
        on_run_finished: Optional[OnRunFinishedFn] = None,
        on_record_result: Optional[OnRecordResultFn] = None,
        on_run_complete: Optional[OnRunCompleteFn] = None,
        on_analyze: Optional[OnAnalyzeFn] = None,
        enqueue_orders: Optional[EnqueueOrdersFn] = None,
        post_to_main: Optional[PostToMainFn] = None,
    ) -> None:
        super().__init__(parent)
        self._on_synced = on_synced
        self._get_checked_records = get_checked_records
        self._on_run_started = on_run_started
        self._on_run_finished = on_run_finished
        self._on_record_result = on_record_result
        self._on_run_complete = on_run_complete
        self._on_analyze = on_analyze
        self._enqueue_orders = enqueue_orders
        self._post_to_main = post_to_main
        self._credits = 0
        self._selected_ids: set[int] = set()
        self._running = False
        self._refreshing = False

        self.setWindowTitle("Dịch vụ")
        self.setMinimumSize(620, 480)
        self.resize(700, 540)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        title = QLabel("Dịch vụ server")
        title.setStyleSheet("font-size: 15px; font-weight: bold;")
        root.addWidget(title)

        self._status_label = QLabel()
        self._status_label.setStyleSheet("color: gray;")
        self._status_label.setWordWrap(True)
        root.addWidget(self._status_label)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Chạy", "ID", "Tên dịch vụ", VND_LABEL])
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionMode(QTableWidget.NoSelection)
        self._table.setFocusPolicy(Qt.NoFocus)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        self._table.setColumnWidth(0, 44)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        root.addWidget(self._table, 1)

        self._auto_check = QCheckBox(
            "Tự động chạy dịch vụ đã tick khi thêm thiết bị qua USB — kết quả ghi vào Ghi chú"
        )
        root.addWidget(self._auto_check)

        hint = QLabel(
            "Tick dịch vụ ở cột «Chạy», tick IMEI trên bảng chính, rồi bấm Run. "
            "«Phân tích» lấy cột check (nhà mạng, simlock, FMI…) từ đơn đã xong trên server; "
            "model/màu/bộ nhớ/IMEI2/serial thêm từ Ghi chú nếu có. "
            "Dịch «Lưu IMEI» luôn chạy riêng khi cắm USB."
        )
        hint.setStyleSheet("color: gray; font-size: 12px;")
        hint.setWordWrap(True)
        root.addWidget(hint)

        actions = QHBoxLayout()
        self._refresh_btn = _primary_button("Làm mới")
        self._refresh_btn.clicked.connect(lambda: self._refresh(show_error=True))
        actions.addWidget(self._refresh_btn)
        self._run_btn = _primary_button("Run")
        self._run_btn.clicked.connect(self._run_checked)
        actions.addWidget(self._run_btn)
        self._analyze_btn = QPushButton("Phân tích")
        self._analyze_btn.setToolTip(
            "Lấy nhà mạng, simlock, FMI, Active… từ parsed của đơn IMEI trên server; "
            "model/màu/bộ nhớ/IMEI2/serial từ Ghi chú nếu có."
        )
        self._analyze_btn.clicked.connect(self._analyze_checked)
        actions.addWidget(self._analyze_btn)
        actions.addStretch(1)
        close_btn = QPushButton("Đóng")
        close_btn.clicked.connect(self._save_and_close)
        actions.addWidget(close_btn)
        root.addLayout(actions)

        self._load_from_cache()
        QTimer.singleShot(0, lambda: self._refresh(show_error=False))

    def _load_from_cache(self) -> None:
        cache = load_services_cache()
        self._credits = cache.credits
        self._selected_ids = set(cache.auto_service_ids)
        self._auto_check.setChecked(cache.auto_enabled)
        self._populate_table(list(cache.services))
        self._update_status(cache.synced_at_display, len(cache.services))

    def _populate_table(self, services: list[ServiceItem]) -> None:
        self._table.clearContents()
        self._table.setRowCount(len(services))
        for row, item in enumerate(services):
            tick = QTableWidgetItem()
            tick.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            tick.setText("")
            tick.setCheckState(
                Qt.Checked if item.id in self._selected_ids else Qt.Unchecked
            )
            tick.setTextAlignment(Qt.AlignCenter)
            self._table.setItem(row, 0, tick)

            id_cell = QTableWidgetItem(str(item.id))
            id_cell.setTextAlignment(Qt.AlignCenter)
            self._table.setItem(row, 1, id_cell)

            name_cell = QTableWidgetItem(item.name)
            self._table.setItem(row, 2, name_cell)

            credit_cell = QTableWidgetItem(format_vnd(item.credit))
            credit_cell.setTextAlignment(Qt.AlignCenter)
            self._table.setItem(row, 3, credit_cell)

    def _collect_selected_ids(self) -> list[int]:
        selected: list[int] = []
        for row in range(self._table.rowCount()):
            tick = self._table.item(row, 0)
            id_cell = self._table.item(row, 1)
            if tick is None or id_cell is None:
                continue
            if tick.checkState() != Qt.Checked:
                continue
            try:
                selected.append(int(id_cell.text()))
            except ValueError:
                continue
        return selected

    def _save_prefs(self) -> None:
        save_auto_service_prefs(
            enabled=self._auto_check.isChecked(),
            service_ids=self._collect_selected_ids(),
        )

    def _save_and_close(self) -> None:
        self._save_prefs()
        self.accept()

    def _set_running(self, running: bool) -> None:
        self._running = running
        self._run_btn.setEnabled(not running and not self._refreshing)
        self._refresh_btn.setEnabled(not running and not self._refreshing)
        self._run_btn.setText("Đang chạy…" if running else "Run")

    def _analyze_checked(self) -> None:
        if self._on_analyze is None or self._get_checked_records is None:
            QMessageBox.warning(self, "Dịch vụ", "Không kết nối được với bảng IMEI.")
            return

        records = self._get_checked_records()
        if not records:
            QMessageBox.warning(
                self,
                "Dịch vụ",
                "Chưa tick dòng IMEI nào trên bảng chính (cột ☑).",
            )
            return

        updated = self._on_analyze(records)
        self._status_label.setText(
            f"Phân tích: cập nhật từ server + ghi chú — {updated}/{len(records)} dòng."
        )

    def _run_checked(self) -> None:
        if self._running:
            return

        service_ids = self._collect_selected_ids()
        if not service_ids:
            QMessageBox.warning(self, "Dịch vụ", "Chưa tick dịch vụ nào ở cột «Chạy».")
            return

        if self._get_checked_records is None:
            QMessageBox.warning(self, "Dịch vụ", "Không kết nối được với bảng IMEI.")
            return

        records = self._get_checked_records()
        if not records:
            QMessageBox.warning(
                self,
                "Dịch vụ",
                "Chưa tick dòng IMEI nào trên bảng chính (cột ☑).",
            )
            return

        if not load_api_config().enabled:
            QMessageBox.warning(
                self,
                "Dịch vụ",
                "Chưa cấu hình email và API token (Cài đặt → Tài khoản API).",
            )
            return

        self._save_prefs()

        status = refresh_license_status()
        if not status.valid:
            QMessageBox.warning(
                self,
                "Dịch vụ",
                status.message or "Chưa đăng nhập hoặc phiên không hợp lệ.",
            )
            return

        self._credits = int(status.credits)
        estimate = estimate_services_run(service_ids, len(records))

        if estimate.has_payable_orders and estimate.required_vnd > self._credits:
            QMessageBox.warning(
                self,
                "Dịch vụ",
                (
                    f"Không đủ {VND_LABEL} để chạy.\n\n"
                    f"Cần: {format_vnd(estimate.required_vnd)} {VND_LABEL}\n"
                    f"Số dư: {format_vnd(self._credits)} {VND_LABEL}\n\n"
                    f"{estimate.record_count} IMEI × "
                    f"{estimate.paid_service_count} dịch vụ trả phí"
                ),
            )
            return

        if (
            estimate.has_simlock_checks
            and status.simlock_count > 0
            and status.simlock_remaining < estimate.simlock_check_count
        ):
            QMessageBox.warning(
                self,
                "Dịch vụ",
                (
                    "Không đủ lượt check simlock miễn phí.\n\n"
                    f"Cần: {estimate.simlock_check_count} lượt\n"
                    f"Còn: {status.simlock_remaining}/{status.simlock_count}\n\n"
                    "Dùng dịch vụ trả phí khác hoặc liên hệ admin."
                ),
            )
            return

        # Tách dịch vụ simlock (gọi endpoint riêng) khỏi đơn IMEI thường.
        # Đơn IMEI → đẩy vào engine nền: app chỉ gửi/lấy kết quả qua server.
        simlock_ids: list[int] = []
        order_ids: list[int] = []
        service_names: dict[int, str] = {}
        for sid in service_ids:
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
            QMessageBox.warning(self, "Dịch vụ", "Không có dịch vụ phù hợp để chạy.")
            return

        if self._on_run_started is not None:
            self._on_run_started(records)

        n_imei = len(records)
        if order_ids:
            if self._enqueue_orders is None:
                QMessageBox.warning(
                    self, "Dịch vụ", "Không kết nối được luồng xử lý đơn."
                )
            else:
                queued = self._enqueue_orders(records, order_ids, service_names)
                log_start(
                    "Run dịch vụ (dialog)",
                    f"{len(order_ids)} dịch vụ × {n_imei} IMEI",
                )
                self._status_label.setText(
                    f"Đã thêm {queued} đơn vào hàng chờ — đang xử lý nền, "
                    "kết quả cập nhật dần…"
                )

        if simlock_ids:
            self._run_simlock_services(records, simlock_ids)
        elif self._on_run_complete is not None:
            self._on_run_complete()

    def _run_simlock_services(
        self, records: list[DeviceRecord], service_ids: list[int]
    ) -> None:
        """Chạy dịch vụ simlock đồng bộ (endpoint riêng, không qua engine đơn)."""
        self._set_running(True)
        total = len(records)

        def work() -> None:
            done = 0
            max_workers = min(RUN_MAX_WORKERS, len(records))
            try:
                with ThreadPoolExecutor(
                    max_workers=max_workers, thread_name_prefix="svc-run"
                ) as pool:
                    future_map = {
                        pool.submit(run_auto_services, record, service_ids): record
                        for record in records
                    }
                    for future in as_completed(future_map):
                        record = future_map[future]
                        try:
                            outcome = future.result()
                        except Exception:
                            logger.exception("Run services failed for one IMEI")
                            outcome = AutoServicesResult()
                        done += 1
                        self._emit_partial_result(record, outcome)
            except Exception:
                logger.exception("Run services pool failed")

            def finalize() -> None:
                self._set_running(False)
                cache = load_services_cache()
                self._update_status(cache.synced_at_display, len(cache.services))
                if done == 0 and self._on_run_finished is not None:
                    self._on_run_finished(
                        [(record, AutoServicesResult()) for record in records]
                    )
                log_done("Run dịch vụ", f"{done}/{total} IMEI")
                if self._on_run_complete is not None:
                    self._on_run_complete()

            if self._post_to_main is not None:
                self._post_to_main(finalize)
            else:
                finalize()

        threading.Thread(target=work, daemon=True, name="services-run").start()

    def _emit_partial_result(
        self, record: DeviceRecord, outcome: AutoServicesResult
    ) -> None:
        if self._on_run_finished is None:
            return

        def deliver() -> None:
            if self._on_run_finished is not None:
                self._on_run_finished([(record, outcome)])

        if self._post_to_main is not None:
            self._post_to_main(deliver)
        else:
            deliver()

    def _update_status(self, synced_at: str, count: int) -> None:
        if self._running:
            return
        credit_part = f" — {format_vnd(self._credits)} {VND_LABEL}"
        ticked = len(self._collect_selected_ids())
        auto_part = f" · {ticked} dịch vụ tick" if ticked else ""
        self._status_label.setText(
            f"{count} dịch vụ · Đồng bộ: {synced_at}{credit_part}{auto_part}"
        )

    def _refresh(self, *, show_error: bool = True) -> None:
        if self._refreshing or self._running:
            return
        if not load_api_config().enabled:
            if show_error:
                QMessageBox.warning(
                    self,
                    "Dịch vụ",
                    "Chưa cấu hình email và API token (Cài đặt → Tài khoản API).",
                )
            return

        self._selected_ids = set(self._collect_selected_ids())
        self._refreshing = True
        self._refresh_btn.setEnabled(False)
        self._refresh_btn.setText("Đang tải…")
        self._run_btn.setEnabled(False)
        self._status_label.setText("Đang đồng bộ dịch vụ từ server…")
        log_start("Đồng bộ dịch vụ")

        def work() -> None:
            try:
                ok, message, services, credits = sync_services_from_server()
            except Exception as exc:
                logger.warning("Sync services failed: %s", exc)
                ok, message, services, credits = False, str(exc), [], self._credits

            def apply() -> None:
                self._refreshing = False
                self._refresh_btn.setText("Làm mới")
                self._refresh_btn.setEnabled(not self._running)
                self._run_btn.setEnabled(not self._running)

                if not ok:
                    log_done("Đồng bộ dịch vụ", message or "thất bại")
                    cache = load_services_cache()
                    self._update_status(cache.synced_at_display, len(cache.services))
                    fail_note = message or "Không tải được dịch vụ."
                    self._status_label.setText(
                        f"{self._status_label.text()} · Lỗi: {fail_note} (dùng cache)"
                    )
                    if show_error:
                        QMessageBox.warning(self, "Dịch vụ", fail_note)
                    return

                self._credits = credits
                self._populate_table(services)
                cache = load_services_cache()
                self._update_status(cache.synced_at_display, len(services))
                log_done("Đồng bộ dịch vụ", f"{len(services)} dịch vụ, {format_vnd(credits)} {VND_LABEL}")

                if self._on_synced is not None:
                    self._on_synced()

            if self._post_to_main is not None:
                self._post_to_main(apply)
            else:
                apply()

        threading.Thread(target=work, daemon=True, name="services-sync").start()


def _primary_button(text: str) -> QPushButton:
    btn = QPushButton(text)
    mark_primary(btn)
    return btn


def open_services_dialog(
    parent: Optional[QWidget],
    *,
    on_synced: Optional[Callable[[], None]] = None,
    get_checked_records: Optional[GetCheckedRecordsFn] = None,
    on_run_started: Optional[OnRunStartedFn] = None,
    on_run_finished: Optional[OnRunFinishedFn] = None,
    on_record_result: Optional[OnRecordResultFn] = None,
    on_run_complete: Optional[OnRunCompleteFn] = None,
    on_analyze: Optional[OnAnalyzeFn] = None,
    enqueue_orders: Optional[EnqueueOrdersFn] = None,
    post_to_main: Optional[PostToMainFn] = None,
) -> None:
    ServicesDialog(
        parent,
        on_synced=on_synced,
        get_checked_records=get_checked_records,
        on_run_started=on_run_started,
        on_run_finished=on_run_finished,
        on_record_result=on_record_result,
        on_run_complete=on_run_complete,
        on_analyze=on_analyze,
        enqueue_orders=enqueue_orders,
        post_to_main=post_to_main,
    ).exec()


def sync_services_on_login(*, silent: bool = True) -> tuple[bool, str]:
    """Đồng bộ dịch vụ sau đăng nhập. Không chặn login nếu silent=True."""
    try:
        ok, message, _services, _credits = sync_services_from_server()
    except Exception as exc:
        logger.warning("Sync services on login failed: %s", exc)
        if silent:
            return False, str(exc)
        return False, str(exc)

    if not ok and not silent:
        return False, message

    if not ok:
        logger.info("Đồng bộ dịch vụ khi đăng nhập thất bại: %s", message)

    return ok, message
