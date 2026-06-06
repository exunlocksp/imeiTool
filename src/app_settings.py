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
    "battery_health": "% Pin",
    "cycle_count": "Lần sạc",
}

PRINT_FIELD_KEYS = (
    "imei",
    "model",
    "color",
    "storage",
    "battery_health",
    "ios",
    "barcode",
)

PRINT_FIELD_LABELS: dict[str, str] = {
    "imei": "IMEI",
    "model": "Model",
    "color": "Màu",
    "storage": "Dung lượng",
    "battery_health": "% Pin",
    "ios": "iOS",
    "barcode": "Barcode",
}


def _settings_path() -> Path:
    return default_db_path().parent / "settings.json"


def _default_flags(keys: tuple[str, ...]) -> dict[str, bool]:
    return {key: True for key in keys}


@dataclass
class AppSettings:
    table_columns: dict[str, bool] = field(default_factory=lambda: _default_flags(TABLE_COLUMN_KEYS))
    print_fields: dict[str, bool] = field(default_factory=lambda: _default_flags(PRINT_FIELD_KEYS))

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
        table = _default_flags(TABLE_COLUMN_KEYS)
        table.update({k: bool(v) for k, v in (data.get("table_columns") or {}).items() if k in table})
        print_f = _default_flags(PRINT_FIELD_KEYS)
        print_f.update({k: bool(v) for k, v in (data.get("print_fields") or {}).items() if k in print_f})
        return cls(table_columns=table, print_fields=print_f)

    def to_dict(self) -> dict[str, Any]:
        return {
            "table_columns": {key: bool(self.table_columns.get(key, True)) for key in TABLE_COLUMN_KEYS},
            "print_fields": {key: bool(self.print_fields.get(key, True)) for key in PRINT_FIELD_KEYS},
        }

    def save(self) -> None:
        path = _settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
