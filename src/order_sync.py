"""Đồng bộ đơn IMEI giữa app và server — KHÔNG biết gì về nhà cung cấp.

App chỉ GET/POST tới server. Mọi việc gửi đơn đến nhà cung cấp và lấy kết quả
do server tự lo. App theo dõi trạng thái đơn (giống server) và lưu local để
resume khi tắt/mở lại:

    1 pending    : chưa gửi server → engine gửi đi → chuyển 2
    2 processing : đã gửi, đang chờ kết quả → engine poll mỗi 5 giây
    3 denied     : CHỈ khi server trả về denied
    4 done       : hoàn thành

Engine quét đơn status 1 (gửi đi) và status 2 (lấy kết quả) định kỳ 5 giây,
và chạy lại tự động khi mở app (resume).
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Optional

from src.api_client import fetch_orders_status, submit_imei_orders_bulk
from src.api_config import load_api_config
from src.auto_services import append_service_note, apply_order_result
from src.database import AppOrderRow, DeviceDatabase
from src.models import DeviceRecord

logger = logging.getLogger(__name__)

STATUS_PENDING = 1
STATUS_PROCESSING = 2
STATUS_DENIED = 3
STATUS_DONE = 4

POLL_INTERVAL_SEC = 5.0
SUBMIT_CHUNK = 100
POLL_CHUNK = 500

RecordsProvider = Callable[[], list[DeviceRecord]]
OnRecordResult = Callable[[DeviceRecord], None]
OnProgress = Callable[[str], None]


def _record_keys(imei1: str, imei2: str, serial: str) -> list[str]:
    keys: list[str] = []
    if serial:
        keys.append(f"serial:{serial.strip().upper()}")
    if imei1:
        keys.append(f"imei1:{imei1.strip()}")
    if imei2:
        keys.append(f"imei2:{imei2.strip()}")
    return keys


def _order_keys(order: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    serial = str(order.get("serial") or "").strip().upper()
    if serial:
        keys.append(f"serial:{serial}")
    if order.get("imei1"):
        keys.append(f"imei1:{str(order['imei1']).strip()}")
    if order.get("imei2"):
        keys.append(f"imei2:{str(order['imei2']).strip()}")
    primary = str(order.get("imei") or "").strip()
    if primary:
        keys.append(f"serial:{primary.upper()}")
        keys.append(f"imei1:{primary}")
    return keys


class OrderSyncEngine:
    """Vòng lặp nền: gửi đơn chờ + lấy kết quả mỗi 5 giây. Provider-agnostic."""

    def __init__(
        self,
        *,
        records_provider: RecordsProvider,
        on_record_result: OnRecordResult,
        on_progress: Optional[OnProgress] = None,
        db: Optional[DeviceDatabase] = None,
    ) -> None:
        self._records_provider = records_provider
        self._on_record_result = on_record_result
        self._on_progress = on_progress
        self._db = db or DeviceDatabase()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._wake = threading.Event()

    # ----------------------------------------------------------- lifecycle

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="order-sync"
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def wake(self) -> None:
        """Đánh thức engine xử lý ngay (không đợi hết 5 giây)."""
        self._wake.set()

    # ----------------------------------------------------------- enqueue

    def enqueue(
        self,
        records: list[DeviceRecord],
        service_ids: list[int],
        *,
        service_names: Optional[dict[int, str]] = None,
    ) -> int:
        """Thêm đơn status=1 cho mỗi (dòng × dịch vụ). Trả số đơn đã thêm."""
        names = service_names or {}
        added = 0
        for record in records:
            if record.id is None:
                continue
            if not (record.imei1 or record.imei2 or record.serial):
                continue
            for sid in service_ids:
                local_id = self._db.enqueue_app_order(
                    device_record_id=record.id,
                    service_id=sid,
                    service_name=names.get(sid, ""),
                    imei1=record.imei1,
                    imei2=record.imei2,
                    serial=record.serial,
                )
                if local_id is not None:
                    added += 1
        if added:
            self.wake()
        return added

    def has_active(self) -> bool:
        return bool(self._db.load_app_orders(statuses=(STATUS_PENDING, STATUS_PROCESSING)))

    # ----------------------------------------------------------- loop

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception:
                logger.exception("Order sync run_once lỗi")
            self._wake.wait(POLL_INTERVAL_SEC)
            self._wake.clear()

    def run_once(self) -> tuple[int, int]:
        """Một lượt: gửi đơn status 1 + lấy kết quả đơn status 2.

        Trả (đã_gửi, đã_xong)."""
        if not load_api_config().enabled:
            return 0, 0
        records = self._records_provider()
        sent = self._send_pending(records)
        finished = self._poll_processing(records)
        return sent, finished

    # ----------------------------------------------------------- internal

    def _report(self, message: str) -> None:
        if self._on_progress is not None and message:
            self._on_progress(message)

    def _find_record(
        self, records: list[DeviceRecord], row: AppOrderRow
    ) -> Optional[DeviceRecord]:
        for record in records:
            if record.id is not None and record.id == row.device_record_id:
                return record
        serial = (row.serial or "").strip().upper()
        imei1 = (row.imei1 or "").strip()
        imei2 = (row.imei2 or "").strip()
        for record in records:
            if serial and (record.serial or "").strip().upper() == serial:
                return record
            if imei1 and (record.imei1 or "").strip() == imei1:
                return record
            if imei2 and (record.imei2 or "").strip() == imei2:
                return record
        return None

    def _finalize(
        self, records: list[DeviceRecord], row: AppOrderRow, order: dict[str, Any]
    ) -> None:
        record = self._find_record(records, row)
        if record is None:
            return
        apply_order_result(record, row.service_name, order)
        self._on_record_result(record)

    def _send_pending(self, records: list[DeviceRecord]) -> int:
        rows = self._db.load_app_orders(statuses=(STATUS_PENDING,))
        if not rows:
            return 0

        by_service: dict[int, list[AppOrderRow]] = {}
        for row in rows:
            by_service.setdefault(row.service_id, []).append(row)

        sent = 0
        for service_id, group in by_service.items():
            for start in range(0, len(group), SUBMIT_CHUNK):
                chunk = group[start:start + SUBMIT_CHUNK]
                devices = [
                    {"imei1": r.imei1, "imei2": r.imei2, "serial": r.serial}
                    for r in chunk
                ]
                res = submit_imei_orders_bulk(devices, service_id=service_id)
                if not res.orders:
                    # Server từ chối CỐ ĐỊNH từng đơn (vd dịch vụ chưa cấu hình) →
                    # ghi chú và bỏ khỏi hàng chờ, KHÔNG retry vô hạn.
                    if self._handle_submit_errors(records, chunk, res.errors):
                        continue
                    # Lỗi tạm thời (mạng…) → GIỮ status 1, thử lại lượt sau.
                    self._report(res.message or "Gửi đơn thất bại, sẽ thử lại…")
                    continue

                index: dict[str, list[AppOrderRow]] = {}
                for r in chunk:
                    for key in _record_keys(r.imei1, r.imei2, r.serial):
                        index.setdefault(key, []).append(r)
                consumed: set[int] = set()

                for order in res.orders:
                    row = self._match_row(order, index, consumed)
                    if row is None:
                        continue
                    oid = int(order.get("id") or 0)
                    if oid <= 0:
                        continue
                    status = int(order.get("status") or 0)
                    if status in (STATUS_DONE, STATUS_DENIED):
                        self._finalize(records, row, order)
                        self._db.delete_app_order(row.local_id)
                    else:
                        # Gửi thành công → đang xử lý, chờ poll lấy kết quả.
                        self._db.mark_app_order_sent(
                            row.local_id, order_id=oid, status=STATUS_PROCESSING
                        )
                    sent += 1
        if sent:
            self._report(f"Đã gửi {sent} đơn lên máy chủ…")
        return sent

    def _handle_submit_errors(
        self,
        records: list[DeviceRecord],
        chunk: list[AppOrderRow],
        errors: Optional[list[dict[str, Any]]],
    ) -> bool:
        """Lỗi cố định theo từng đơn (index → dòng trong chunk) → ghi note + bỏ
        khỏi hàng chờ để không gửi lại vô hạn. Trả True nếu đã xử lý lỗi nào đó."""
        if not errors:
            return False
        handled = False
        for err in errors:
            try:
                idx = int(err.get("index"))
            except (TypeError, ValueError):
                continue
            if not (0 <= idx < len(chunk)):
                continue
            row = chunk[idx]
            message = str(err.get("message") or "Đơn không hợp lệ.").strip()
            record = self._find_record(records, row)
            if record is not None:
                append_service_note(record, row.service_name, message)
                self._on_record_result(record)
            self._db.delete_app_order(row.local_id)
            handled = True
        return handled

    def _match_row(
        self,
        order: dict[str, Any],
        index: dict[str, list[AppOrderRow]],
        consumed: set[int],
    ) -> Optional[AppOrderRow]:
        for key in _order_keys(order):
            for row in index.get(key, []):
                if row.local_id not in consumed:
                    consumed.add(row.local_id)
                    return row
        return None

    def _poll_processing(self, records: list[DeviceRecord]) -> int:
        rows = self._db.load_app_orders(statuses=(STATUS_PROCESSING,))
        if not rows:
            return 0

        by_oid: dict[int, AppOrderRow] = {
            row.order_id: row for row in rows if row.order_id
        }
        order_ids = list(by_oid.keys())
        finished = 0

        for start in range(0, len(order_ids), POLL_CHUNK):
            chunk = order_ids[start:start + POLL_CHUNK]
            res = fetch_orders_status(chunk)
            if not res.ok or not res.orders:
                continue
            for order in res.orders:
                oid = int(order.get("id") or 0)
                row = by_oid.get(oid)
                if row is None:
                    continue
                status = int(order.get("status") or 0)
                # CHỈ kết thúc khi server báo DONE hoặc DENIED. Các trạng thái
                # khác (pending/processing) → giữ nguyên, poll tiếp lượt sau.
                if status in (STATUS_DONE, STATUS_DENIED):
                    self._finalize(records, row, order)
                    self._db.delete_app_order(row.local_id)
                    finished += 1

        if finished:
            self._report(f"Đã lấy {finished} kết quả từ máy chủ…")
        return finished
