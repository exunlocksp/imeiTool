"""Đọc thông số pin qua Diagnostics IORegistry (IOPMPowerSource)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from pymobiledevice3.lockdown import create_using_usbmux
from pymobiledevice3.services.diagnostics import DiagnosticsService

logger = logging.getLogger(__name__)

BATTERY_KEYS = frozenset({
    "CurrentCapacity",
    "MaxCapacity",
    "DesignCapacity",
    "CycleCount",
    "AppleRawMaxCapacity",
    "AppleRawCurrentCapacity",
    "NominalChargeCapacity",
    "IsCharging",
    "ExternalConnected",
    "FullyCharged",
    "BatteryData",
    "LegacyBatteryInfo",
    "StateOfCharge",
    "Temperature",
})


@dataclass
class BatteryStats:
    charge_percent: Optional[int] = None
    health_percent: Optional[int] = None
    cycle_count: Optional[int] = None
    design_capacity_mah: Optional[int] = None
    max_capacity_mah: Optional[int] = None
    current_capacity_mah: Optional[int] = None
    is_charging: Optional[bool] = None
    unavailable_reason: str = ""

    def format_charge(self) -> str:
        return f"{self.charge_percent}%" if self.charge_percent is not None else ""

    def format_health(self) -> str:
        if self.health_percent is None:
            return ""
        detail = ""
        if self.max_capacity_mah and self.design_capacity_mah:
            detail = f" ({self.max_capacity_mah}/{self.design_capacity_mah} mAh)"
        return f"{self.health_percent}%{detail}"

    def format_health_percent(self) -> str:
        return f"{self.health_percent}%" if self.health_percent is not None else ""

    def format_cycles(self) -> str:
        return str(self.cycle_count) if self.cycle_count is not None else ""

    def summary_note(self) -> str:
        parts: list[str] = []
        if self.health_percent is not None:
            parts.append(f"Pin {self.health_percent}%")
        if self.cycle_count is not None:
            parts.append(f"{self.cycle_count} lần sạc")
        if self.is_charging is True:
            parts.append("đang sạc")
        return ", ".join(parts)


def _as_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return None


def _as_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value)
    return None


def _flatten_battery_tree(node: Any, bag: dict[str, Any]) -> None:
    if not isinstance(node, dict):
        return
    for key, value in node.items():
        if key in BATTERY_KEYS and key not in bag:
            bag[key] = value
        if isinstance(value, dict):
            if key == "BatteryData":
                for sub_k, sub_v in value.items():
                    sk = str(sub_k)
                    if sk not in bag:
                        bag[sk] = sub_v
            elif key == "LegacyBatteryInfo":
                for sub_k, sub_v in value.items():
                    norm = str(sub_k).replace(" ", "")
                    if norm not in bag:
                        bag[norm] = sub_v
            _flatten_battery_tree(value, bag)


def _looks_like_percent_scale(current: int, maximum: int, design: Optional[int]) -> bool:
    if current <= 100 and maximum <= 100:
        return True
    if design and design > 200 and maximum <= 100:
        return True
    return False


def parse_battery_ioreg(raw: Optional[dict]) -> BatteryStats:
    """Parse IORegistry battery snapshot → structured stats."""
    stats = BatteryStats()
    if not raw:
        stats.unavailable_reason = "Không có dữ liệu IORegistry"
        return stats

    bag: dict[str, Any] = {}
    _flatten_battery_tree(raw, bag)

    if not bag:
        stats.unavailable_reason = "Thiết bị không trả về trường pin (có thể cần mở khóa màn hình)"
        return stats

    design = _as_int(bag.get("DesignCapacity"))
    nominal = _as_int(
        bag.get("NominalChargeCapacity")
        or bag.get("AppleRawMaxCapacity")
        or bag.get("MaxCapacity")
    )
    current = _as_int(
        bag.get("AppleRawCurrentCapacity")
        or bag.get("CurrentCapacity")
        or bag.get("StateOfCharge")
    )
    max_cap = _as_int(bag.get("AppleRawMaxCapacity") or bag.get("MaxCapacity") or nominal)
    cycles = _as_int(bag.get("CycleCount"))

    stats.design_capacity_mah = design if design and design > 200 else None
    stats.cycle_count = cycles
    stats.is_charging = _as_bool(bag.get("IsCharging"))

    if stats.design_capacity_mah and nominal:
        if nominal <= 100 and stats.design_capacity_mah > 200:
            stats.health_percent = max(0, min(100, nominal))
            stats.max_capacity_mah = None
        else:
            stats.max_capacity_mah = nominal
            stats.health_percent = max(
                0, min(100, round(100 * nominal / stats.design_capacity_mah))
            )

    if current is not None and max_cap is not None:
        if _looks_like_percent_scale(current, max_cap, design):
            stats.charge_percent = max(0, min(100, current))
        elif max_cap > 0 and max_cap > 100:
            stats.current_capacity_mah = current
            stats.charge_percent = max(0, min(100, round(100 * current / max_cap)))
        elif stats.health_percent and current <= 100:
            stats.charge_percent = max(0, min(100, current))

    if stats.charge_percent is None and current is not None and current <= 100:
        stats.charge_percent = current

    if stats.max_capacity_mah is None and max_cap and max_cap > 100:
        stats.max_capacity_mah = max_cap
    if stats.current_capacity_mah is None and current and current > 100:
        stats.current_capacity_mah = current

    if stats.charge_percent is None and stats.health_percent is None and stats.cycle_count is None:
        stats.unavailable_reason = "Không parse được — thử mở khóa iPhone và cắm lại"

    return stats


async def read_battery_async(lockdown) -> BatteryStats:
    try:
        diag = DiagnosticsService(lockdown)
        raw = await diag.get_battery()
        return parse_battery_ioreg(raw)
    except Exception as exc:
        logger.debug("Battery read failed: %s", exc)
        return BatteryStats(unavailable_reason=str(exc))


async def read_battery_for_udid(udid: str) -> BatteryStats:
    async with await create_using_usbmux(serial=udid, autopair=True, pair_timeout=120) as lockdown:
        return await read_battery_async(lockdown)
