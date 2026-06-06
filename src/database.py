"""Lưu danh sách thiết bị vào SQLite (dữ liệu giữ khi tắt app)."""

from __future__ import annotations

import logging
import os
import sqlite3
import sys
from pathlib import Path
from typing import Optional

from src.app_branding import APP_SHORT_NAME
from src.models import DeviceRecord

logger = logging.getLogger(__name__)

_RECORD_FIELDS = (
    "imei1",
    "imei2",
    "serial",
    "model",
    "ios_version",
    "color",
    "storage_capacity",
    "condition",
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
                battery_percent TEXT NOT NULL DEFAULT '',
                battery_health TEXT NOT NULL DEFAULT '',
                cycle_count TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT '',
                device_udid TEXT NOT NULL DEFAULT '',
                captured_at TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT '',
                is_checked INTEGER NOT NULL DEFAULT 0,
                sort_order INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        self._migrate_schema()
        self._conn.commit()

    def _migrate_schema(self) -> None:
        cols = {row[1] for row in self._conn.execute("PRAGMA table_info(device_records)")}
        if "ios_version" not in cols:
            self._conn.execute(
                "ALTER TABLE device_records ADD COLUMN ios_version TEXT NOT NULL DEFAULT ''"
            )

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
        cur = self._conn.execute(
            "SELECT * FROM device_records ORDER BY sort_order ASC, id ASC"
        )
        return [self._row_to_pair(row) for row in cur.fetchall()]

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
            [*self._record_values(record), int(is_checked), sort_order],
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
        self._conn.commit()
