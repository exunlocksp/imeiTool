"""Định nghĩa cột xuất Text/Excel và đọc giá trị từ DeviceRecord."""

from __future__ import annotations

from src.app_settings import TABLE_COLUMN_KEYS, TABLE_COLUMN_LABELS
from src.models import DeviceRecord

EXPORT_FIELD_KEYS = TABLE_COLUMN_KEYS
EXPORT_FIELD_LABELS = TABLE_COLUMN_LABELS

_ATTR_BY_KEY: dict[str, str] = {
    "time": "captured_at",
    "storage": "storage_capacity",
}

EXCEL_COLUMN_WIDTHS: dict[str, int] = {
    "time": 20,
    "source": 10,
    "imei1": 18,
    "imei2": 18,
    "serial": 16,
    "model": 24,
    "ios_version": 10,
    "color": 16,
    "storage": 12,
    "condition": 14,
    "simlock": 12,
    "fmi": 12,
    "active": 10,
    "carrier": 14,
    "mdm": 8,
    "battery_health": 10,
    "cycle_count": 10,
}


def record_export_value(record: DeviceRecord, key: str) -> str:
    attr = _ATTR_BY_KEY.get(key, key)
    return str(getattr(record, attr, "") or "")
