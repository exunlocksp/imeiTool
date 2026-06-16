"""Lưu danh sách thiết bị vào SQLite (dữ liệu giữ khi tắt app)."""

from __future__ import annotations

import logging
import os
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.app_branding import APP_SHORT_NAME
from src.models import DeviceRecord

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PendingOrderRow:
    order_id: int
    device_record_id: int
    service_id: int
    service_name: str
    imei1: str
    imei2: str
    serial: str
    started_at: str
    poll_timeout_sec: float


@dataclass(frozen=True)
class AppOrderRow:
    """Một đơn IMEI app theo dõi để resume. Trạng thái giống server (1/2/3/4).

    - status 1 (pending): chưa gửi server (order_id is None) → engine gửi đi.
    - status 2 (processing): đã gửi (có order_id) → engine poll kết quả.
    Khi xong (4) hoặc bị từ chối (3) thì xoá khỏi bảng.
    """

    local_id: int
    order_id: Optional[int]
    device_record_id: int
    service_id: int
    service_name: str
    imei1: str
    imei2: str
    serial: str
    status: int

_RECORD_FIELDS = (
    "imei1",
    "imei2",
    "serial",
    "model",
    "ios_version",
    "color",
    "storage_capacity",
    "condition",
    "simlock",
    "fmi",
    "active",
    "carrier",
    "mdm",
    "battery_percent",
    "battery_health",
    "cycle_count",
    "source",
    "device_udid",
    "captured_at",
    "note",
)


def default_db_path() -> Path:
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / APP_SHORT_NAME
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", str(Path.home()))) / APP_SHORT_NAME
    else:
        base = Path.home() / ".local" / "share" / APP_SHORT_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base / "devices.db"


class DeviceDatabase:
    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = path or default_db_path()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        # Engine nền và main thread dùng kết nối riêng → chờ khoá thay vì lỗi ngay.
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS device_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                imei1 TEXT NOT NULL DEFAULT '',
                imei2 TEXT NOT NULL DEFAULT '',
                serial TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT '',
                ios_version TEXT NOT NULL DEFAULT '',
                color TEXT NOT NULL DEFAULT '',
                storage_capacity TEXT NOT NULL DEFAULT '',
                condition TEXT NOT NULL DEFAULT '',
                simlock TEXT NOT NULL DEFAULT '',
                fmi TEXT NOT NULL DEFAULT '',
                active TEXT NOT NULL DEFAULT '',
                carrier TEXT NOT NULL DEFAULT '',
                mdm TEXT NOT NULL DEFAULT '',
                battery_percent TEXT NOT NULL DEFAULT '',
                battery_health TEXT NOT NULL DEFAULT '',
                cycle_count TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT '',
                device_udid TEXT NOT NULL DEFAULT '',
                captured_at TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT '',
                server_id INTEGER,
                server_updated_at TEXT NOT NULL DEFAULT '',
                has_service_result INTEGER NOT NULL DEFAULT 0,
                is_hidden INTEGER NOT NULL DEFAULT 0,
                is_checked INTEGER NOT NULL DEFAULT 0,
                sort_order INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dismissed_usb (
                udid TEXT PRIMARY KEY
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pending_orders (
                order_id INTEGER PRIMARY KEY,
                device_record_id INTEGER NOT NULL,
                service_id INTEGER NOT NULL,
                service_name TEXT NOT NULL DEFAULT '',
                imei1 TEXT NOT NULL DEFAULT '',
                imei2 TEXT NOT NULL DEFAULT '',
                serial TEXT NOT NULL DEFAULT '',
                started_at TEXT NOT NULL DEFAULT '',
                poll_timeout_sec REAL NOT NULL DEFAULT 600
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS app_orders (
                local_id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER,
                device_record_id INTEGER NOT NULL,
                service_id INTEGER NOT NULL,
                service_name TEXT NOT NULL DEFAULT '',
                imei1 TEXT NOT NULL DEFAULT '',
                imei2 TEXT NOT NULL DEFAULT '',
                serial TEXT NOT NULL DEFAULT '',
                status INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT ''
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_app_orders_status ON app_orders(status)"
        )
        self._migrate_schema()
        self._migrate_pending_orders_to_app_orders()
        self._conn.commit()

    def _migrate_schema(self) -> None:
        cols = {row[1] for row in self._conn.execute("PRAGMA table_info(device_records)")}
        for col, ddl in (
            ("server_id", "INTEGER"),
            ("server_updated_at", "TEXT NOT NULL DEFAULT ''"),
            ("has_service_result", "INTEGER NOT NULL DEFAULT 0"),
            ("is_hidden", "INTEGER NOT NULL DEFAULT 0"),
        ):
            if col not in cols:
                self._conn.execute(
                    f"ALTER TABLE device_records ADD COLUMN {col} {ddl}"
                )
        if "ios_version" not in cols:
            self._conn.execute(
                "ALTER TABLE device_records ADD COLUMN ios_version TEXT NOT NULL DEFAULT ''"
            )
        if "simlock" not in cols:
            self._conn.execute(
                "ALTER TABLE device_records ADD COLUMN simlock TEXT NOT NULL DEFAULT ''"
            )
        for col in ("fmi", "active", "carrier", "mdm"):
            if col not in cols:
                self._conn.execute(
                    f"ALTER TABLE device_records ADD COLUMN {col} TEXT NOT NULL DEFAULT ''"
                )

    def _migrate_pending_orders_to_app_orders(self) -> None:
        """Chuyển đơn theo dõi cũ (pending_orders, đều đã gửi) sang app_orders status=2."""
        try:
            rows = self._conn.execute(
                """
                SELECT order_id, device_record_id, service_id, service_name,
                       imei1, imei2, serial
                FROM pending_orders
                """
            ).fetchall()
        except sqlite3.OperationalError:
            return
        if not rows:
            return
        ts = datetime.now(timezone.utc).isoformat()
        for row in rows:
            order_id = int(row[0] or 0)
            if order_id <= 0:
                continue
            exists = self._conn.execute(
                "SELECT 1 FROM app_orders WHERE order_id=? LIMIT 1",
                (order_id,),
            ).fetchone()
            if exists is not None:
                continue
            self._conn.execute(
                """
                INSERT INTO app_orders (
                    order_id, device_record_id, service_id, service_name,
                    imei1, imei2, serial, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 2, ?, ?)
                """,
                (
                    order_id,
                    int(row[1] or 0),
                    int(row[2] or 0),
                    str(row[3] or ""),
                    str(row[4] or ""),
                    str(row[5] or ""),
                    str(row[6] or ""),
                    ts,
                    ts,
                ),
            )
        self._conn.execute("DELETE FROM pending_orders")

    def close(self) -> None:
        self._conn.close()

    @staticmethod
    def _record_values(record: DeviceRecord) -> list[str]:
        return [str(getattr(record, name, "") or "") for name in _RECORD_FIELDS]

    @staticmethod
    def _row_to_pair(row: sqlite3.Row) -> tuple[DeviceRecord, bool]:
        data = {name: row[name] for name in _RECORD_FIELDS}
        record = DeviceRecord(id=int(row["id"]), **data)
        return record, bool(row["is_checked"])

    def load_all(self) -> list[tuple[DeviceRecord, bool]]:
        query = "SELECT * FROM device_records ORDER BY sort_order ASC, id ASC"
        cur = self._conn.execute(query)
        return [self._row_to_pair(row) for row in cur.fetchall()]

    def find_record_by_udid(self, udid: str) -> Optional[tuple[DeviceRecord, bool]]:
        udid = (udid or "").strip()
        if not udid:
            return None
        row = self._conn.execute(
            "SELECT * FROM device_records WHERE device_udid=? ORDER BY id DESC LIMIT 1",
            (udid,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_pair(row)

    def find_by_identifier(
        self,
        *,
        serial: str = "",
        imei1: str = "",
    ) -> Optional[tuple[DeviceRecord, bool]]:
        serial = (serial or "").strip().upper()
        imei1 = (imei1 or "").strip()
        if serial:
            row = self._conn.execute(
                "SELECT * FROM device_records WHERE upper(serial)=? ORDER BY id DESC LIMIT 1",
                (serial,),
            ).fetchone()
            if row is not None:
                return self._row_to_pair(row)
        if imei1:
            row = self._conn.execute(
                "SELECT * FROM device_records WHERE imei1=? ORDER BY id DESC LIMIT 1",
                (imei1,),
            ).fetchone()
            if row is not None:
                return self._row_to_pair(row)
        return None

    def insert(
        self,
        record: DeviceRecord,
        *,
        sort_order: int,
        is_checked: bool = False,
    ) -> int:
        placeholders = ", ".join("?" * (len(_RECORD_FIELDS) + 2))
        columns = ", ".join((*_RECORD_FIELDS, "is_checked", "sort_order"))
        cur = self._conn.execute(
            f"INSERT INTO device_records ({columns}) VALUES ({placeholders})",
            [
                *self._record_values(record),
                int(is_checked),
                sort_order,
            ],
        )
        self._conn.commit()
        record_id = int(cur.lastrowid)
        record.id = record_id
        return record_id

    def update(self, record: DeviceRecord, *, is_checked: Optional[bool] = None) -> None:
        if record.id is None:
            raise ValueError("record.id required for update")
        assignments = ", ".join(f"{name}=?" for name in _RECORD_FIELDS)
        values = self._record_values(record)
        if is_checked is None:
            self._conn.execute(
                f"UPDATE device_records SET {assignments} WHERE id=?",
                [*values, record.id],
            )
        else:
            self._conn.execute(
                f"UPDATE device_records SET {assignments}, is_checked=? WHERE id=?",
                [*values, int(is_checked), record.id],
            )
        self._conn.commit()

    def update_checked(self, record_id: int, is_checked: bool) -> None:
        self._conn.execute(
            "UPDATE device_records SET is_checked=? WHERE id=?",
            (int(is_checked), record_id),
        )
        self._conn.commit()

    def update_all_checked(self, is_checked: bool) -> None:
        self._conn.execute(
            "UPDATE device_records SET is_checked=?",
            (int(is_checked),),
        )
        self._conn.commit()

    def delete(self, record_id: int) -> None:
        self._conn.execute("DELETE FROM device_records WHERE id=?", (record_id,))
        self._conn.commit()

    def delete_all(self) -> None:
        self._conn.execute("DELETE FROM device_records")
        self._conn.execute("DELETE FROM dismissed_usb")
        self._conn.commit()

    def dismiss_usb(self, udid: str) -> None:
        udid = (udid or "").strip()
        if not udid:
            return
        self._conn.execute(
            "INSERT OR IGNORE INTO dismissed_usb (udid) VALUES (?)",
            (udid,),
        )
        self._conn.commit()

    def undismiss_usb(self, udid: str) -> None:
        udid = (udid or "").strip()
        if not udid:
            return
        self._conn.execute("DELETE FROM dismissed_usb WHERE udid=?", (udid,))
        self._conn.commit()

    def load_dismissed_usb(self) -> set[str]:
        cur = self._conn.execute("SELECT udid FROM dismissed_usb")
        return {str(row[0]) for row in cur.fetchall() if row[0]}

    def save_pending_order(
        self,
        *,
        order_id: int,
        device_record_id: int,
        service_id: int,
        service_name: str,
        imei1: str = "",
        imei2: str = "",
        serial: str = "",
        poll_timeout_sec: float = 600.0,
        started_at: Optional[str] = None,
    ) -> None:
        if order_id <= 0 or device_record_id <= 0:
            return
        ts = started_at or datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """
            INSERT INTO pending_orders (
                order_id, device_record_id, service_id, service_name,
                imei1, imei2, serial, started_at, poll_timeout_sec
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(order_id) DO UPDATE SET
                device_record_id=excluded.device_record_id,
                service_id=excluded.service_id,
                service_name=excluded.service_name,
                imei1=excluded.imei1,
                imei2=excluded.imei2,
                serial=excluded.serial,
                started_at=excluded.started_at,
                poll_timeout_sec=excluded.poll_timeout_sec
            """,
            (
                order_id,
                device_record_id,
                service_id,
                (service_name or "").strip(),
                (imei1 or "").strip(),
                (imei2 or "").strip(),
                (serial or "").strip().upper(),
                ts,
                float(poll_timeout_sec),
            ),
        )
        self._conn.commit()

    def delete_pending_order(self, order_id: int) -> None:
        if order_id <= 0:
            return
        self._conn.execute("DELETE FROM pending_orders WHERE order_id=?", (order_id,))
        self._conn.commit()

    def load_pending_orders(self) -> list[PendingOrderRow]:
        cur = self._conn.execute(
            """
            SELECT order_id, device_record_id, service_id, service_name,
                   imei1, imei2, serial, started_at, poll_timeout_sec
            FROM pending_orders
            ORDER BY order_id ASC
            """
        )
        rows: list[PendingOrderRow] = []
        for row in cur.fetchall():
            rows.append(
                PendingOrderRow(
                    order_id=int(row[0]),
                    device_record_id=int(row[1]),
                    service_id=int(row[2]),
                    service_name=str(row[3] or ""),
                    imei1=str(row[4] or ""),
                    imei2=str(row[5] or ""),
                    serial=str(row[6] or ""),
                    started_at=str(row[7] or ""),
                    poll_timeout_sec=float(row[8] or 600.0),
                )
            )
        return rows

    # ----------------------------------------------------------- app_orders

    @staticmethod
    def _row_to_app_order(row: sqlite3.Row) -> AppOrderRow:
        order_id = row["order_id"]
        return AppOrderRow(
            local_id=int(row["local_id"]),
            order_id=int(order_id) if order_id is not None else None,
            device_record_id=int(row["device_record_id"]),
            service_id=int(row["service_id"]),
            service_name=str(row["service_name"] or ""),
            imei1=str(row["imei1"] or ""),
            imei2=str(row["imei2"] or ""),
            serial=str(row["serial"] or ""),
            status=int(row["status"] or 1),
        )

    def enqueue_app_order(
        self,
        *,
        device_record_id: int,
        service_id: int,
        service_name: str = "",
        imei1: str = "",
        imei2: str = "",
        serial: str = "",
    ) -> Optional[int]:
        """Thêm đơn ở status=1 (chờ gửi). Bỏ qua nếu đã có đơn đang hoạt động
        (status 1/2) cho cùng dòng + dịch vụ. Trả local_id (hoặc None nếu bỏ qua)."""
        if device_record_id <= 0 or service_id <= 0:
            return None
        existing = self._conn.execute(
            """
            SELECT local_id FROM app_orders
            WHERE device_record_id=? AND service_id=? AND status IN (1, 2)
            LIMIT 1
            """,
            (device_record_id, service_id),
        ).fetchone()
        if existing is not None:
            return None
        ts = datetime.now(timezone.utc).isoformat()
        cur = self._conn.execute(
            """
            INSERT INTO app_orders (
                order_id, device_record_id, service_id, service_name,
                imei1, imei2, serial, status, created_at, updated_at
            ) VALUES (NULL, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (
                device_record_id,
                service_id,
                (service_name or "").strip(),
                (imei1 or "").strip(),
                (imei2 or "").strip(),
                (serial or "").strip().upper(),
                ts,
                ts,
            ),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def mark_app_order_sent(self, local_id: int, *, order_id: int, status: int) -> None:
        if local_id <= 0:
            return
        self._conn.execute(
            "UPDATE app_orders SET order_id=?, status=?, updated_at=? WHERE local_id=?",
            (int(order_id), int(status), datetime.now(timezone.utc).isoformat(), local_id),
        )
        self._conn.commit()

    def set_app_order_status(self, local_id: int, status: int) -> None:
        if local_id <= 0:
            return
        self._conn.execute(
            "UPDATE app_orders SET status=?, updated_at=? WHERE local_id=?",
            (int(status), datetime.now(timezone.utc).isoformat(), local_id),
        )
        self._conn.commit()

    def delete_app_order(self, local_id: int) -> None:
        if local_id <= 0:
            return
        self._conn.execute("DELETE FROM app_orders WHERE local_id=?", (local_id,))
        self._conn.commit()

    def load_app_orders(
        self, *, statuses: Optional[tuple[int, ...]] = None
    ) -> list[AppOrderRow]:
        if statuses:
            placeholders = ", ".join("?" * len(statuses))
            cur = self._conn.execute(
                f"SELECT * FROM app_orders WHERE status IN ({placeholders}) ORDER BY local_id ASC",
                tuple(int(s) for s in statuses),
            )
        else:
            cur = self._conn.execute("SELECT * FROM app_orders ORDER BY local_id ASC")
        return [self._row_to_app_order(row) for row in cur.fetchall()]
