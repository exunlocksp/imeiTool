"""Cài đặt hiển thị bảng và in nhãn (lưu JSON trong Application Support)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.app_branding import APP_SHORT_NAME
from src.database import default_db_path

logger = logging.getLogger(__name__)

TABLE_COLUMN_KEYS = (
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

TABLE_COLUMN_LABELS: dict[str, str] = {
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
    "fmi": "FMI (iCloud)",
    "active": "Active",
    "carrier": "Nhà mạng",
    "mdm": "MDM",
    "battery_health": "% Pin",
    "cycle_count": "Lần sạc",
}

PRINT_FIELD_KEYS = (
    "imei",
    "model",
    "color",
    "storage",
    "condition",
    "battery_health",
    "ios",
    "simlock",
    "fmi",
    "active",
    "carrier",
    "mdm",
    "barcode",
)

PRINT_FIELD_LABELS: dict[str, str] = {
    "imei": "IMEI",
    "model": "Model",
    "color": "Màu",
    "storage": "Dung lượng",
    "condition": "Hình thức",
    "battery_health": "% Pin",
    "ios": "iOS",
    "simlock": "Simlock",
    "fmi": "FMI (iCloud)",
    "active": "Active",
    "carrier": "Nhà mạng",
    "mdm": "MDM",
    "barcode": "Barcode",
}

# Nhãn in cho cột simlock (Unlocked / Locked từ API).
SIMLOCK_PRINT_LABELS: dict[str, str] = {
    "Unlocked": "Quốc Tế",
    "Locked": "Máy Lock",
}


def _settings_path() -> Path:
    return default_db_path().parent / "settings.json"


def _default_flags(keys: tuple[str, ...]) -> dict[str, bool]:
    return {key: True for key in keys}


@dataclass
class AppSettings:
    table_columns: dict[str, bool] = field(default_factory=lambda: _default_flags(TABLE_COLUMN_KEYS))
    print_fields: dict[str, bool] = field(default_factory=lambda: _default_flags(PRINT_FIELD_KEYS))
    auto_check_simlock: bool = False

    def visible_table_columns(self) -> list[str]:
        return [key for key in TABLE_COLUMN_KEYS if self.table_columns.get(key, True)]

    def enabled_print_fields(self) -> dict[str, bool]:
        return {key: bool(self.print_fields.get(key, True)) for key in PRINT_FIELD_KEYS}

    def has_print_content(self) -> bool:
        return any(self.print_fields.get(key, True) for key in PRINT_FIELD_KEYS)

    @classmethod
    def load(cls) -> AppSettings:
        path = _settings_path()
        if not path.is_file():
            return cls()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Không đọc được settings.json: %s", exc)
            return cls()
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AppSettings:
        saved_table = data.get("table_columns") or {}
        if saved_table:
            # File cũ: cột mới (fmi, active, carrier…) ẩn mặc định — không phá layout đã lưu.
            table = {key: bool(saved_table.get(key, False)) for key in TABLE_COLUMN_KEYS}
        else:
            table = _default_flags(TABLE_COLUMN_KEYS)

        saved_print = data.get("print_fields") or {}
        if saved_print:
            print_f = {key: bool(saved_print.get(key, False)) for key in PRINT_FIELD_KEYS}
        else:
            print_f = _default_flags(PRINT_FIELD_KEYS)

        return cls(
            table_columns=table,
            print_fields=print_f,
            auto_check_simlock=bool(data.get("auto_check_simlock", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "table_columns": {key: bool(self.table_columns.get(key, True)) for key in TABLE_COLUMN_KEYS},
            "print_fields": {key: bool(self.print_fields.get(key, True)) for key in PRINT_FIELD_KEYS},
            "auto_check_simlock": bool(self.auto_check_simlock),
        }

    def save(self) -> None:
        path = _settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
