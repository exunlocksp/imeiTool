from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional

from pymobiledevice3 import usbmux
from pymobiledevice3.exceptions import (
    ConnectionFailedError,
    NotPairedError,
    PairingDialogResponsePendingError,
    PyMobileDevice3Exception,
    UserDeniedPairingError,
)
from pymobiledevice3.lockdown import create_using_usbmux
from pymobiledevice3.services.diagnostics import DiagnosticsService

from src.battery_reader import read_battery_async
from src.enclosure_color import read_enclosure_color_async
from src.storage_reader import read_storage_async
from src.models import DeviceRecord
from src.product_map import resolve_model_name

logger = logging.getLogger(__name__)

StatusCallback = Callable[[str], None]
RecordCallback = Callable[[DeviceRecord], None]
UnplugCallback = Callable[[str], None]
DismissLiftCallback = Callable[[str], None]

DISMISS_LIFT_SECONDS = 5.0


class DevicePhase(str, Enum):
    DETECTED = "detected"
    WAITING_TRUST = "waiting_trust"
    READING = "reading"
    DONE = "done"
    FAILED = "failed"


@dataclass
class TrackedDevice:
    serial_usb: str
    phase: DevicePhase = DevicePhase.DETECTED
    last_message: str = ""


GESTALT_KEYS = [
    "SerialNumber",
    "InternationalMobileEquipmentIdentity",
    "InternationalMobileEquipmentIdentity2",
    "ProductType",
    "ModelNumber",
    "DeviceEnclosureColor",
    "DeviceColor",
    "DiskUsage",
]


def _run(coro):
    return asyncio.run(coro)


async def _read_fmi_async(lockdown) -> str:
    """Find My iPhone: On/Off (domain com.apple.fmip)."""
    try:
        associated = await lockdown.get_value(domain="com.apple.fmip", key="IsAssociated")
    except Exception as exc:
        logger.debug("FMI read skipped: %s", exc)
        return ""
    if associated is None:
        return ""
    return "On" if associated else "Off"


async def _read_active_async(lockdown) -> str:
    """ActivationState → Yes/No."""
    try:
        state = await lockdown.get_value(key="ActivationState")
    except Exception as exc:
        logger.debug("ActivationState read skipped: %s", exc)
        return ""
    text = str(state or "").strip()
    if not text:
        return ""
    return "No" if "unactivated" in text.lower() else "Yes"


async def _list_usb_devices() -> list[usbmux.MuxDevice]:
    return await usbmux.list_devices()


def _is_usb_connection(dev: usbmux.MuxDevice) -> bool:
    return getattr(dev, "connection_type", "USB") == "USB"


def list_connected_udids(*, usb_only: bool = True) -> set[str]:
    """UDID thiết bị iOS — mặc định chỉ cáp USB (bỏ qua Wi‑Fi sync)."""
    try:
        devices = _run(_list_usb_devices())
    except Exception:
        return set()
    udids: set[str] = set()
    for dev in devices:
        if not dev.serial:
            continue
        if usb_only and not _is_usb_connection(dev):
            continue
        udids.add(dev.serial)
    return udids


async def _read_device_async(udid: str) -> DeviceRecord:
    async with await create_using_usbmux(serial=udid, autopair=True, pair_timeout=120) as lockdown:
        serial = await lockdown.get_value(key="SerialNumber") or ""
        product_type = await lockdown.get_value(key="ProductType") or ""
        model_number = await lockdown.get_value(key="ModelNumber") or ""
        ios_version = await lockdown.get_value(key="ProductVersion") or ""
        if not ios_version:
            ios_version = lockdown.all_values.get("ProductVersion") or ""

        imei1 = lockdown.all_values.get("InternationalMobileEquipmentIdentity") or ""
        imei2 = lockdown.all_values.get("InternationalMobileEquipmentIdentity2") or ""

        gestalt: dict = {}
        try:
            diag = DiagnosticsService(lockdown)
            gestalt = await diag.mobilegestalt(GESTALT_KEYS)
            imei1 = imei1 or gestalt.get("InternationalMobileEquipmentIdentity") or ""
            imei2 = imei2 or gestalt.get("InternationalMobileEquipmentIdentity2") or ""
            serial = serial or gestalt.get("SerialNumber") or ""
            product_type = product_type or gestalt.get("ProductType") or ""
            model_number = model_number or gestalt.get("ModelNumber") or ""
        except Exception as exc:
            logger.debug("MobileGestalt skipped: %s", exc)

        product_type_str = str(product_type) if product_type else ""
        model = resolve_model_name(product_type_str, str(model_number) if model_number else None)

        color, color_note = await read_enclosure_color_async(
            lockdown, product_type_str, gestalt=gestalt or None
        )

        battery = await read_battery_async(lockdown)
        storage = await read_storage_async(lockdown, gestalt=gestalt or None)

        fmi = await _read_fmi_async(lockdown)
        active = await _read_active_async(lockdown)
        # Nhà mạng không lấy từ máy khi cắm/rút — chỉ điền khi chạy dịch vụ
        # (phân tích dòng "Locked Carrier" trong kết quả → cột nhà mạng).
        carrier = ""

        note_parts = [battery.summary_note()] if battery.summary_note() else []
        if storage.summary_note():
            note_parts.append(storage.summary_note())
        if battery.unavailable_reason:
            note_parts.append(battery.unavailable_reason)
        if color_note:
            note_parts.append(color_note)
        if storage.unavailable_reason and not storage.capacity_label:
            note_parts.append(storage.unavailable_reason)

        return DeviceRecord(
            imei1=str(imei1) if imei1 else "",
            imei2=str(imei2) if imei2 else "",
            serial=str(serial) if serial else "",
            model=model,
            ios_version=str(ios_version).strip() if ios_version else "",
            color=color,
            storage_capacity=storage.format_capacity(),
            fmi=fmi,
            active=active,
            carrier=carrier,
            battery_percent="",
            battery_health=battery.format_health_percent(),
            cycle_count=battery.format_cycles(),
            source="USB",
            device_udid=udid,
            note="; ".join(note_parts),
        )


def read_device_info(udid: str) -> DeviceRecord:
    return _run(_read_device_async(udid))


class UsbDeviceMonitor:
    """Poll usbmux and read each new trusted device once."""

    def __init__(
        self,
        on_status: Optional[StatusCallback] = None,
        on_record: Optional[RecordCallback] = None,
        on_unplug: Optional[UnplugCallback] = None,
        on_dismiss_lift: Optional[DismissLiftCallback] = None,
        poll_interval: float = 1.5,
    ) -> None:
        self.on_status = on_status or (lambda _msg: None)
        self.on_record = on_record or (lambda _rec: None)
        self.on_unplug = on_unplug or (lambda _udid: None)
        self.on_dismiss_lift = on_dismiss_lift or (lambda _udid: None)
        self.poll_interval = poll_interval
        self._tracked: dict[str, TrackedDevice] = {}
        self._completed_udids: set[str] = set()
        self._completed_serials: set[str] = set()
        self._udid_serial: dict[str, str] = {}
        self._last_udids: set[str] = set()
        self._dismissed_udids: set[str] = set()
        self._dismiss_lift_pending: dict[str, float] = {}
        self._running = False

    def dismiss_udid(self, udid: str) -> None:
        if udid:
            self._dismissed_udids.add(udid)

    def undismiss_udid(self, udid: str) -> None:
        self._dismissed_udids.discard(udid)

    def mark_completed(self, udid: str, record: DeviceRecord) -> None:
        self._completed_udids.add(udid)
        if record.serial:
            key = record.serial.upper()
            self._completed_serials.add(key)
            self._udid_serial[udid] = key

    def should_skip_udid(self, udid: str) -> bool:
        if udid in self._dismissed_udids:
            return True
        if udid in self._completed_udids:
            return True
        tracked = self._tracked.get(udid)
        return bool(tracked and tracked.phase == DevicePhase.DONE)

    def _handle_disconnect(self, udid: str) -> None:
        """Rút cáp / mất kết nối."""
        self._tracked.pop(udid, None)
        self._completed_udids.discard(udid)
        serial = self._udid_serial.pop(udid, None)
        if serial:
            self._completed_serials.discard(serial)
        if udid in self._dismissed_udids:
            self._dismiss_lift_pending[udid] = time.monotonic()
        self.on_unplug(udid)

    def _lift_dismissals(self, current_udids: set[str]) -> None:
        """Sau khi rút thật sự (~5s), cho phép đọc lại thiết bị đã xóa."""
        now = time.monotonic()
        for udid, since in list(self._dismiss_lift_pending.items()):
            if udid in current_udids:
                self._dismiss_lift_pending.pop(udid, None)
                continue
            if now - since < DISMISS_LIFT_SECONDS:
                continue
            self._dismiss_lift_pending.pop(udid, None)
            self._dismissed_udids.discard(udid)
            self.on_dismiss_lift(udid)

    def poll_once(self) -> None:
        try:
            devices = _run(_list_usb_devices())
        except Exception as exc:
            self.on_status(f"Không kết nối usbmuxd: {exc}")
            return

        usb_devices = [d for d in devices if d.serial and _is_usb_connection(d)]
        current_udids = {d.serial for d in usb_devices if d.serial}

        for udid in self._last_udids - current_udids:
            self._handle_disconnect(udid)
        self._last_udids = current_udids
        self._lift_dismissals(current_udids)

        if not usb_devices:
            if devices:
                self.on_status("Chờ cắm iPhone/iPad bằng cáp USB… (bỏ qua Wi‑Fi sync)")
            else:
                self.on_status("Chờ cắm iPhone/iPad…")
            return

        for dev in usb_devices:
            udid = dev.serial
            if not udid or self.should_skip_udid(udid):
                continue

            if udid not in self._tracked:
                self._tracked[udid] = TrackedDevice(serial_usb=udid)
                self.on_status(f"Phát hiện thiết bị {udid[:8]}… — bấm «Tin cậy» trên iPhone")

            self._process_device(udid)

    def _process_device(self, udid: str) -> None:
        tracked = self._tracked[udid]
        if tracked.phase in (DevicePhase.READING, DevicePhase.DONE):
            return

        tracked.phase = DevicePhase.WAITING_TRUST
        tracked.last_message = "Đang chờ tin cậy / ghép đôi…"
        self.on_status(tracked.last_message)

        try:
            tracked.phase = DevicePhase.READING
            self.on_status(f"Đang đọc {udid[:8]}…")
            record = read_device_info(udid)

            if not record.has_data():
                raise PyMobileDevice3Exception("Không lấy được dữ liệu thiết bị")

            self.mark_completed(udid, record)
            tracked.phase = DevicePhase.DONE
            self.on_record(record)
            label = record.model or record.serial or udid[:8]
            self.on_status(f"Đã đọc: {label}")

        except PairingDialogResponsePendingError:
            tracked.phase = DevicePhase.WAITING_TRUST
            self.on_status("Chờ người dùng bấm «Tin cậy» trên iPhone…")
        except UserDeniedPairingError:
            tracked.phase = DevicePhase.FAILED
            self.on_status("Người dùng từ chối tin cậy máy tính")
        except NotPairedError:
            tracked.phase = DevicePhase.WAITING_TRUST
            self.on_status("Thiết bị chưa ghép đôi — bấm «Tin cậy»…")
        except ConnectionFailedError:
            tracked.phase = DevicePhase.WAITING_TRUST
            self.on_status("Chưa kết nối lockdown — mở khóa iPhone và bấm «Tin cậy»")
        except Exception as exc:
            logger.exception("USB read failed for %s", udid)
            if "trust" in str(exc).lower() or "pair" in str(exc).lower():
                tracked.phase = DevicePhase.WAITING_TRUST
                self.on_status("Chờ tin cậy thiết bị…")
            else:
                tracked.phase = DevicePhase.FAILED
                tracked.last_message = str(exc)
                self.on_status(f"Lỗi đọc thiết bị: {exc}")
