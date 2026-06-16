from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class DeviceRecord:
    """One row of device information."""

    id: Optional[int] = None  # SQLite primary key — không xuất Excel/in
    imei1: str = ""
    imei2: str = ""
    serial: str = ""
    model: str = ""
    ios_version: str = ""  # ProductVersion — USB
    color: str = ""
    storage_capacity: str = ""  # Bộ nhớ marketing (128 GB, 256 GB, …) — USB khi có
    condition: str = ""  # Hình thức (máy mới, máy cũ, …) — nhập/sửa thủ công
    simlock: str = ""
    fmi: str = ""  # Find My iPhone (iCloud): On | Off — USB
    active: str = ""  # Trạng thái kích hoạt: Yes | No — USB
    carrier: str = ""  # Tên nhà mạng SIM — USB
    mdm: str = ""  # MDM Lock: On | Off — từ kết quả check (server parse)
    battery_percent: str = ""
    battery_health: str = ""
    cycle_count: str = ""
    source: str = ""  # USB | Ảnh | Dán
    device_udid: str = ""  # USB only — for re-scan after xóa dòng
    captured_at: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    note: str = ""

    @property
    def dedupe_key(self) -> str:
        if self.serial:
            return f"serial:{self.serial.upper()}"
        if self.imei1:
            return f"imei:{self.imei1}"
        return f"row:{self.captured_at}"

    def has_data(self) -> bool:
        return bool(self.imei1 or self.imei2 or self.serial or self.model)
