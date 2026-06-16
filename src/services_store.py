"""Cache dịch vụ từ Laravel API — lưu JSON local."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from src.api_client import list_services
from src.database import default_db_path

logger = logging.getLogger(__name__)

SAVE_IMEI_NAME_HINT = "lưu imei"
SIMLOCK_NAME_HINT = "simlock"

SICKW_POLL_INTERVAL_SEC = 1.5
DHRU_POLL_INTERVAL_SEC = 10.0
SICKW_POLL_TIMEOUT_SEC = 90.0
DHRU_POLL_TIMEOUT_SEC = 600.0


@dataclass(frozen=True)
class ServiceItem:
    """Dịch vụ từ server — server_id dùng khi POST /imei/orders."""

    server_id: int
    name: str
    credit: int
    credit_cost: int = 1
    api_id: Optional[int] = None
    api_route: str = ""
    api_type: str = ""
    provider_service_id: str = ""
    sickw_service_id: str = ""
    uses_provider: bool = False
    uses_sickw: bool = False

    @property
    def id(self) -> int:
        """Alias — luôn là ID dịch vụ trên Laravel."""
        return self.server_id

    @property
    def is_save_imei(self) -> bool:
        return SAVE_IMEI_NAME_HINT in self.name.lower()

    @property
    def is_simlock(self) -> bool:
        return SIMLOCK_NAME_HINT in self.name.lower()

    @property
    def is_sickw(self) -> bool:
        api_type = self.api_type.strip().lower()
        api_route = self.api_route.strip().lower()
        return api_type == "sickw" or api_route == "sickw"

    @property
    def is_dhru(self) -> bool:
        api_type = self.api_type.strip().lower()
        return api_type == "dhru" or (bool(self.api_route.strip()) and not self.is_sickw)

    @property
    def uses_external_provider(self) -> bool:
        if self.is_save_imei or self.is_simlock:
            return False
        if self.uses_provider:
            return True
        if self.api_id is not None and bool(self.provider_service_id.strip() or self.sickw_service_id.strip()):
            return True
        return self.is_sickw or self.is_dhru

    def provider_label(self) -> str:
        if self.api_route:
            return self.api_route
        if self.api_type:
            return self.api_type
        return "server"

    def provider_poll_interval(self) -> float:
        """Khoảng cách poll đơn nhà cung cấp — Dhru chậm hơn Sickw."""
        if self.is_dhru:
            return DHRU_POLL_INTERVAL_SEC
        return SICKW_POLL_INTERVAL_SEC

    def provider_poll_timeout(self) -> float:
        """Thời gian chờ tối đa — Dhru có thể vài phút."""
        if self.is_dhru:
            return DHRU_POLL_TIMEOUT_SEC
        return SICKW_POLL_TIMEOUT_SEC

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ServiceItem:
        server_id = int(data.get("server_id") or data.get("id") or 0)
        api_id_raw = data.get("api_id")
        api_id = int(api_id_raw) if api_id_raw not in (None, "", 0) else None

        return cls(
            server_id=server_id,
            name=str(data.get("name") or "").strip(),
            credit=int(data.get("credit") or 0),
            credit_cost=int(data.get("credit_cost") or 1),
            api_id=api_id,
            api_route=str(data.get("api_route") or "").strip(),
            api_type=str(data.get("api_type") or "").strip(),
            provider_service_id=str(
                data.get("provider_service_id") or data.get("sickw_service_id") or ""
            ).strip(),
            sickw_service_id=str(data.get("sickw_service_id") or "").strip(),
            uses_provider=bool(data.get("uses_provider") or data.get("uses_sickw")),
            uses_sickw=bool(data.get("uses_sickw")),
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "server_id": self.server_id,
            "id": self.server_id,
            "name": self.name,
            "credit": self.credit,
            "credit_cost": self.credit_cost,
        }
        if self.api_id is not None:
            payload["api_id"] = self.api_id
        if self.api_route:
            payload["api_route"] = self.api_route
        if self.api_type:
            payload["api_type"] = self.api_type
        if self.provider_service_id:
            payload["provider_service_id"] = self.provider_service_id
        if self.sickw_service_id:
            payload["sickw_service_id"] = self.sickw_service_id
        if self.uses_provider:
            payload["uses_provider"] = True
        if self.uses_sickw:
            payload["uses_sickw"] = True
        return payload


@dataclass(frozen=True)
class AutoServicePrefs:
    enabled: bool = False
    service_ids: tuple[int, ...] = ()

    def is_selected(self, service_id: int) -> bool:
        return service_id in self.service_ids


@dataclass(frozen=True)
class ServicesCache:
    services: tuple[ServiceItem, ...]
    synced_at: str
    credits: int = 0
    auto_enabled: bool = False
    auto_service_ids: tuple[int, ...] = ()

    @property
    def auto_prefs(self) -> AutoServicePrefs:
        return AutoServicePrefs(enabled=self.auto_enabled, service_ids=self.auto_service_ids)

    @property
    def synced_at_display(self) -> str:
        raw = self.synced_at.strip()
        if not raw:
            return "Chưa đồng bộ"
        try:
            dt = datetime.fromisoformat(raw)
            return dt.strftime("%d/%m/%Y %H:%M")
        except ValueError:
            return raw


def _services_path() -> Path:
    return default_db_path().parent / "services.json"


def _read_services_file() -> dict[str, Any]:
    path = _services_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Không đọc được services.json: %s", exc)
        return {}
    return data if isinstance(data, dict) else {}


def _parse_auto_service_ids(raw: Any) -> tuple[int, ...]:
    if not isinstance(raw, list):
        return ()
    ids: list[int] = []
    for item in raw:
        try:
            value = int(item)
        except (TypeError, ValueError):
            continue
        if value > 0 and value not in ids:
            ids.append(value)
    return tuple(ids)


def load_auto_service_prefs() -> AutoServicePrefs:
    return load_services_cache().auto_prefs


def save_auto_service_prefs(*, enabled: bool, service_ids: list[int]) -> None:
    path = _services_path()
    data = _read_services_file()
    data["auto_enabled"] = bool(enabled)
    data["auto_service_ids"] = list(_parse_auto_service_ids(service_ids))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def load_services_cache() -> ServicesCache:
    data = _read_services_file()
    if not data:
        return ServicesCache(services=(), synced_at="", credits=0)

    raw_services = data.get("services")
    items: list[ServiceItem] = []
    if isinstance(raw_services, list):
        for row in raw_services:
            if isinstance(row, dict) and (row.get("server_id") or row.get("id")):
                items.append(ServiceItem.from_dict(row))

    items.sort(key=lambda s: s.name.lower())

    return ServicesCache(
        services=tuple(items),
        synced_at=str(data.get("synced_at") or ""),
        credits=int(data.get("credits") or 0),
        auto_enabled=bool(data.get("auto_enabled")),
        auto_service_ids=_parse_auto_service_ids(data.get("auto_service_ids")),
    )


def save_services_cache(services: list[ServiceItem], *, credits: int = 0) -> None:
    path = _services_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = _read_services_file()
    payload = {
        "synced_at": datetime.now().isoformat(timespec="seconds"),
        "credits": credits,
        "services": [s.to_dict() for s in services],
        "auto_enabled": bool(existing.get("auto_enabled")),
        "auto_service_ids": list(_parse_auto_service_ids(existing.get("auto_service_ids"))),
    }
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def sync_services_from_server(*, timeout: float = 15.0) -> tuple[bool, str, list[ServiceItem], int]:
    """Tải dịch vụ từ server và lưu local (kèm server_id, api_id)."""
    ok, message, rows, credits = list_services(timeout=timeout)
    if not ok:
        return False, message, [], credits

    services = [
        ServiceItem.from_dict(row)
        for row in rows
        if isinstance(row, dict) and (row.get("server_id") or row.get("id"))
    ]
    services.sort(key=lambda s: s.name.lower())
    save_services_cache(services, credits=credits)

    return True, message, services, credits


@dataclass(frozen=True)
class ServicesRunEstimate:
    """Ước tính trước khi Run dịch vụ từ dialog."""

    record_count: int
    paid_service_count: int
    simlock_service_count: int
    skipped_save_imei: int
    required_vnd: int
    simlock_check_count: int

    @property
    def has_payable_orders(self) -> bool:
        return self.paid_service_count > 0 and self.required_vnd > 0

    @property
    def has_simlock_checks(self) -> bool:
        return self.simlock_check_count > 0


def estimate_services_run(
    service_ids: list[int],
    record_count: int,
) -> ServicesRunEstimate:
    """Tính VNĐ cần trừ (IMEI × giá dịch vụ trả phí) và số lượt simlock free."""
    n = max(0, int(record_count))
    required_vnd = 0
    paid_count = 0
    simlock_svc = 0
    skipped_save = 0

    for sid in service_ids:
        svc = find_service_by_id(sid)
        if svc is None:
            continue
        if svc.is_save_imei:
            skipped_save += 1
            continue
        if svc.is_simlock:
            simlock_svc += 1
            continue
        paid_count += 1
        required_vnd += n * max(0, int(svc.credit))

    return ServicesRunEstimate(
        record_count=n,
        paid_service_count=paid_count,
        simlock_service_count=simlock_svc,
        skipped_save_imei=skipped_save,
        required_vnd=required_vnd,
        simlock_check_count=n * simlock_svc if simlock_svc else 0,
    )


def find_service_by_id(service_id: int) -> Optional[ServiceItem]:
    for item in load_services_cache().services:
        if item.server_id == service_id:
            return item
    return None


def find_service_by_name(name: str) -> Optional[ServiceItem]:
    needle = name.strip().lower()
    if not needle:
        return None
    for item in load_services_cache().services:
        if item.name.lower() == needle:
            return item
    return None
