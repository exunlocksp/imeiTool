"""Gửi IMEI/Serial từ desktop lên Laravel API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from src.api_client import list_services, submit_imei_orders_bulk, verify_access
from src.api_config import ApiConfig, load_api_config
from src.models import DeviceRecord


@dataclass(frozen=True)
class ServiceOption:
    id: int
    name: str
    credit: int
    credit_cost: int
    api_ref_id: str

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> ServiceOption:
        return cls(
            id=int(data["id"]),
            name=str(data.get("name") or ""),
            credit=int(data.get("credit") or 0),
            credit_cost=int(data.get("credit_cost") or 1),
            api_ref_id=str(data.get("api_ref_id") or ""),
        )


@dataclass(frozen=True)
class SubmitSummary:
    ok: bool
    message: str
    submitted: int = 0
    errors: int = 0
    credits: int = 0
    error_details: tuple[str, ...] = ()


def records_with_identifiers(records: list[DeviceRecord]) -> list[DeviceRecord]:
    return [r for r in records if r.imei1 or r.imei2 or r.serial]


def records_to_orders(records: list[DeviceRecord]) -> list[dict[str, str]]:
    return [
        {
            "imei1": r.imei1,
            "imei2": r.imei2,
            "serial": r.serial,
        }
        for r in records_with_identifiers(records)
    ]


def load_service_options(config: Optional[ApiConfig] = None) -> tuple[bool, str, list[ServiceOption]]:
    cfg = config or load_api_config()
    if not cfg.enabled:
        return False, "Chưa cấu hình email và API token. Vào Cài đặt → Tài khoản API…", []

    verify = verify_access(cfg)
    if not verify.valid:
        return False, verify.message or "Không xác thực được với server.", []

    ok, message, raw, _credits = list_services(cfg)
    if not ok:
        return False, message, []

    services = [ServiceOption.from_api(item) for item in raw if isinstance(item, dict)]
    if not services:
        return False, "Server chưa có dịch vụ nào đang bật.", []

    return True, message, services


def submit_records(
    records: list[DeviceRecord],
    *,
    service_id: Optional[int] = None,
    service_ref: Optional[str] = None,
    config: Optional[ApiConfig] = None,
) -> SubmitSummary:
    cfg = config or load_api_config()
    orders = records_to_orders(records)

    if not orders:
        return SubmitSummary(ok=False, message="Không có IMEI/Serial hợp lệ để gửi.")

    if not cfg.enabled:
        return SubmitSummary(ok=False, message="Chưa cấu hình email và API token.")

    result = submit_imei_orders_bulk(
        orders,
        service_id=service_id,
        service_ref=service_ref,
        config=cfg,
    )

    submitted = len(result.orders or [])
    errors = result.errors or []
    details = tuple(
        f"Dòng {int(e.get('index', 0)) + 1}: {e.get('message', '')}"
        for e in errors
        if isinstance(e, dict)
    )

    return SubmitSummary(
        ok=bool(result.ok) and submitted > 0,
        message=result.message,
        submitted=submitted,
        errors=len(errors),
        credits=result.credits,
        error_details=details,
    )
