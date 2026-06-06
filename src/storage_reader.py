"""Đọc dung lượng bộ nhớ qua MobileGestalt DiskUsage, lockdown disk_usage và AFC."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from pymobiledevice3.exceptions import DeprecationError
from pymobiledevice3.services.afc import AfcService
from pymobiledevice3.services.diagnostics import DiagnosticsService

logger = logging.getLogger(__name__)

CAPACITY_TIERS_GB = (8, 16, 32, 64, 128, 256, 512, 1024, 2048)

# AFC GET_DEVINFO (Media partition — thường nhỏ hơn NAND; dùng khi không có Gestalt)
_AFC_TOTAL_KEYS = ("FSTotalBytes", "TotalBytes", "TotalDiskCapacity")
_AFC_FREE_KEYS = ("FSFreeBytes", "FreeBytes", "AmountDataAvailable")


@dataclass
class StorageStats:
    capacity_label: str = ""
    total_bytes: Optional[int] = None
    free_bytes: Optional[int] = None
    source: str = ""
    unavailable_reason: str = ""

    def format_capacity(self) -> str:
        return self.capacity_label

    def summary_note(self) -> str:
        if not self.capacity_label and not self.free_bytes:
            return ""
        parts: list[str] = []
        if self.capacity_label:
            src = f" ({self.source})" if self.source else ""
            parts.append(f"Bộ nhớ {self.capacity_label}{src}")
        if self.free_bytes is not None and self.total_bytes:
            free_gb = self.free_bytes / 1_000_000_000
            parts.append(f"trống ~{free_gb:.1f} GB")
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


def _pick_largest(*values: Optional[int]) -> Optional[int]:
    nums = [v for v in values if v is not None and v > 0]
    return max(nums) if nums else None


def bytes_to_marketing_label(total_bytes: int) -> str:
    """Map raw NAND / disk bytes → nhãn marketing (128 GB, 256 GB, …)."""
    if total_bytes <= 0:
        return ""

    decimal_gb = total_bytes / 1_000_000_000
    best_tier = min(CAPACITY_TIERS_GB, key=lambda t: abs(decimal_gb - t))
    if best_tier > 0 and abs(decimal_gb - best_tier) / best_tier <= 0.18:
        return f"{best_tier} GB"

    binary_gb = total_bytes / (1024**3)
    best_tier = min(CAPACITY_TIERS_GB, key=lambda t: abs(binary_gb - t))
    if best_tier > 0 and abs(binary_gb - best_tier) / best_tier <= 0.18:
        return f"{best_tier} GB"

    if decimal_gb >= 1:
        return f"{round(decimal_gb)} GB"
    return ""


def parse_disk_usage_dict(data: Any) -> tuple[Optional[int], Optional[int]]:
    """Parse Gestalt / lockdown disk_usage dict → (total_bytes, free_bytes)."""
    if not isinstance(data, dict):
        return None, None

    total = _pick_largest(
        _as_int(data.get("TotalDiskCapacity")),
        _as_int(data.get("TotalDataCapacity")),
        _sum_capacities(
            _as_int(data.get("TotalDataCapacity")),
            _as_int(data.get("TotalSystemCapacity")),
        ),
    )
    free = _pick_largest(
        _as_int(data.get("AmountDataAvailable")),
        _as_int(data.get("TotalDataAvailable")),
    )
    return total, free


def _sum_capacities(a: Optional[int], b: Optional[int]) -> Optional[int]:
    if a and b:
        return a + b
    return None


def parse_afc_device_info(info: dict[str, str]) -> tuple[Optional[int], Optional[int]]:
    total: Optional[int] = None
    free: Optional[int] = None
    for key in _AFC_TOTAL_KEYS:
        total = _as_int(info.get(key))
        if total:
            break
    for key in _AFC_FREE_KEYS:
        free = _as_int(info.get(key))
        if free is not None:
            break
    return total, free


def build_storage_stats(
    *,
    total_bytes: Optional[int],
    free_bytes: Optional[int] = None,
    source: str = "",
) -> StorageStats:
    stats = StorageStats(total_bytes=total_bytes, free_bytes=free_bytes, source=source)
    if total_bytes:
        stats.capacity_label = bytes_to_marketing_label(total_bytes)
    if not stats.capacity_label:
        stats.unavailable_reason = "Không xác định dung lượng từ thiết bị"
    return stats


async def _read_gestalt_disk_usage(lockdown, gestalt: Optional[dict]) -> StorageStats:
    disk = None
    if gestalt:
        disk = gestalt.get("DiskUsage")

    if disk is None:
        try:
            diag = DiagnosticsService(lockdown)
            result = await diag.mobilegestalt(["DiskUsage"])
            disk = result.get("DiskUsage")
        except DeprecationError:
            logger.debug("MobileGestalt DiskUsage deprecated (iOS >= 17.4)")
        except Exception as exc:
            logger.debug("MobileGestalt DiskUsage failed: %s", exc)

    total, free = parse_disk_usage_dict(disk)
    if total:
        return build_storage_stats(total_bytes=total, free_bytes=free, source="Gestalt")
    return StorageStats(unavailable_reason="Gestalt DiskUsage không có dữ liệu")


async def _read_lockdown_disk_usage(lockdown) -> StorageStats:
    try:
        data = await lockdown.get_value(domain="com.apple.disk_usage")
        total, free = parse_disk_usage_dict(data)
        if total:
            return build_storage_stats(total_bytes=total, free_bytes=free, source="lockdown")
    except Exception as exc:
        logger.debug("lockdown disk_usage failed: %s", exc)
    return StorageStats(unavailable_reason="lockdown disk_usage không có dữ liệu")


async def _read_afc_storage(lockdown) -> StorageStats:
    try:
        async with AfcService(lockdown) as afc:
            info = await afc.get_device_info()
        total, free = parse_afc_device_info(info)
        if total:
            label = bytes_to_marketing_label(total)
            stats = build_storage_stats(total_bytes=total, free_bytes=free, source="AFC")
            if label:
                return stats
            stats.unavailable_reason = "AFC có bytes nhưng không khớp cấu hình marketing"
            return stats
    except Exception as exc:
        logger.debug("AFC get_device_info failed: %s", exc)
    return StorageStats(unavailable_reason="AFC không đọc được")


async def read_storage_async(lockdown, gestalt: Optional[dict] = None) -> StorageStats:
    """Thử Gestalt → lockdown disk_usage → AFC (theo thứ tự ưu tiên)."""
    for reader in (
        lambda: _read_gestalt_disk_usage(lockdown, gestalt),
        lambda: _read_lockdown_disk_usage(lockdown),
        lambda: _read_afc_storage(lockdown),
    ):
        stats = await reader()
        if stats.capacity_label:
            return stats

    reasons = [
        "Gestalt DiskUsage (iOS 17.4+ có thể bị chặn)",
        "lockdown com.apple.disk_usage",
        "AFC (chỉ phân vùng Media, có thể không đủ)",
    ]
    return StorageStats(
        unavailable_reason="Không đọc được bộ nhớ — đã thử: " + "; ".join(reasons)
    )
