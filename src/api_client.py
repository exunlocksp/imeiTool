"""HTTP client gọi Laravel API — xác thực, dịch vụ & đặt IMEI."""

from __future__ import annotations

import json
import logging
import ssl
import urllib.error
import urllib.parse
import urllib.request
from urllib.parse import urlparse
from dataclasses import dataclass
from typing import Any, Optional

from src.activity_log import log_get, log_post, payload_summary, response_summary
from src.api_config import ApiConfig, client_metadata, join_api_url, load_api_config, save_api_config
from src.models import DeviceRecord

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AccessResult:
    valid: bool
    message: str
    email: str = ""
    shop_name: str = ""
    credits: int = 0
    token_count: int = 1
    token_used: int = 0
    token_remaining: int = 1
    access_token: str = ""
    simlock_count: int = 10
    simlock_used: int = 0
    simlock_remaining: int = 10
    expires_at: str = ""
    days_left: Optional[int] = None

    @property
    def ip_count(self) -> int:
        return self.token_count

    @property
    def ip_used(self) -> int:
        return self.token_used

    @property
    def ip_remaining(self) -> int:
        return self.token_remaining


@dataclass(frozen=True)
class SimlockQuotaResult:
    ok: bool
    message: str
    simlock_count: int = 10
    simlock_used: int = 0
    simlock_remaining: int = 10


@dataclass(frozen=True)
class SimlockCheckResult:
    ok: bool
    message: str
    simlock: str = ""
    attempts: int = 0
    saved: bool = False
    simlock_count: int = 10
    simlock_used: int = 0
    simlock_remaining: int = 10


_simlock_quota: dict[str, int] = {
    "count": 10,
    "used": 0,
    "remaining": 10,
}


def get_simlock_quota() -> tuple[int, int, int]:
    """(limit, used, remaining) — cập nhật sau verify/check simlock."""
    return (
        _simlock_quota["count"],
        _simlock_quota["used"],
        _simlock_quota["remaining"],
    )


def _simlock_int(data: dict[str, Any], key: str, *, default: int = 0) -> int:
    if key not in data or data[key] is None:
        return default
    return int(data[key])


def _simlock_quota_result(data: dict[str, Any]) -> tuple[int, int, int]:
    return (
        _simlock_int(data, "simlock_count", default=_simlock_quota["count"]),
        _simlock_int(data, "simlock_used", default=_simlock_quota["used"]),
        _simlock_int(data, "simlock_remaining", default=_simlock_quota["remaining"]),
    )


def _apply_simlock_quota(data: dict[str, Any]) -> None:
    global _simlock_quota
    if "simlock_count" not in data:
        return
    count, used, remaining = _simlock_quota_result(data)
    _simlock_quota = {
        "count": count,
        "used": used,
        "remaining": remaining,
    }


@dataclass(frozen=True)
class ImeiOrderResult:
    ok: bool
    message: str
    order: Optional[dict[str, Any]] = None
    orders: Optional[list[dict[str, Any]]] = None
    errors: Optional[list[dict[str, Any]]] = None
    credits: int = 0
    charged: bool = False


@dataclass(frozen=True)
class SickwOrderPollResult:
    ok: bool
    message: str
    completed: bool = False
    failed: bool = False
    order: Optional[dict[str, Any]] = None
    result: Optional[Any] = None
    credits: int = 0


# Giữ tương thích license.py cũ
LicenseResult = AccessResult


def _auth_payload(cfg: ApiConfig) -> dict[str, str]:
    payload: dict[str, str] = {}
    if cfg.api_email.strip():
        payload["email"] = cfg.api_email
    if cfg.api_token.strip() and not _looks_like_sanctum_token(cfg.api_token):
        payload["api_token"] = cfg.api_token
    return payload


_public_ip_cache: Optional[str] = None

_PUBLIC_IP_ENDPOINTS = (
    "https://api.ipify.org?format=json",
    "https://ipv4.icanhazip.com",
    "https://ifconfig.me/ip",
)


def fetch_public_ip(*, timeout: float = 8.0, force: bool = False) -> str:
    """IP internet (WAN) của máy — dùng khi server local chỉ thấy 127.x."""
    global _public_ip_cache
    if _public_ip_cache and not force:
        return _public_ip_cache

    for url in _PUBLIC_IP_ENDPOINTS:
        try:
            req = urllib.request.Request(
                url,
                method="GET",
                headers={"Accept": "application/json", "User-Agent": "TaodenIMEITool/1.0"},
            )
            with _urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8").strip()
            if url.endswith(".json"):
                ip = str(json.loads(raw).get("ip") or "").strip()
            else:
                ip = raw.splitlines()[0].strip()
            if ip and _looks_like_ip(ip):
                _public_ip_cache = ip
                return ip
        except Exception as exc:
            logger.debug("Fetch public IP from %s failed: %s", url, exc)

    return _public_ip_cache or ""


def _looks_like_ip(value: str) -> bool:
    parts = value.split(".")
    if len(parts) != 4:
        return False
    try:
        return all(0 <= int(part) <= 255 for part in parts)
    except ValueError:
        return False


@dataclass(frozen=True)
class ClientIpInfo:
    ip: str
    seen_ip: str = ""
    is_local_seen: bool = False


def fetch_client_ip(
    config: Optional[ApiConfig] = None,
    *,
    timeout: float = 8.0,
) -> str:
    """IP dùng cho whitelist (ưu tiên IP internet khi dev local)."""
    return fetch_client_ip_info(config, timeout=timeout).ip


def fetch_client_ip_info(
    config: Optional[ApiConfig] = None,
    *,
    timeout: float = 8.0,
) -> ClientIpInfo:
    """IP whitelist + IP kết nối thô từ server."""
    cfg = config or load_api_config()
    if not (cfg.api_base_url or "").strip():
        return ClientIpInfo(ip="")
    params: dict[str, Any] = {}
    public_ip = fetch_public_ip()
    if public_ip:
        params["client_public_ip"] = public_ip
    try:
        data = _get_json(join_api_url(cfg.api_base_url, "access", "client-ip"), params, timeout=timeout)
    except Exception as exc:
        logger.debug("Fetch client IP failed: %s", exc)
        return ClientIpInfo(ip=public_ip or "")
    return ClientIpInfo(
        ip=str(data.get("ip") or public_ip or "").strip(),
        seen_ip=str(data.get("seen_ip") or "").strip(),
        is_local_seen=bool(data.get("is_local_seen")),
    )


def _device_name() -> str:
    import platform
    import socket

    host = (socket.gethostname() or "").strip()
    system = (platform.system() or "").strip()
    if host and system:
        return f"{host} ({system})"
    return host or system or "Desktop"


def _quota_int(data: dict[str, Any], key: str, *, legacy_key: str = "", default: int = 0) -> int:
    if key in data and data[key] is not None:
        return int(data[key])
    if legacy_key and legacy_key in data and data[legacy_key] is not None:
        return int(data[legacy_key])
    return default


def _token_quota_fields(data: dict[str, Any]) -> tuple[int, int, int]:
    count = _quota_int(data, "token_count", legacy_key="ip_count", default=1)
    used = _quota_int(data, "token_used", legacy_key="ip_used", default=0)
    if "token_remaining" in data or "ip_remaining" in data:
        remaining = _quota_int(data, "token_remaining", legacy_key="ip_remaining", default=0)
    else:
        remaining = max(0, count - used)
    return max(1, count), used, remaining


def verify_access(config: Optional[ApiConfig] = None, *, timeout: float = 15.0) -> AccessResult:
    cfg = config or load_api_config()
    if not cfg.enabled:
        return AccessResult(valid=False, message="Chưa cấu hình email và API token.")

    fetch_public_ip(timeout=min(timeout, 10.0), force=True)

    payload = {
        **_auth_payload(cfg),
        **client_metadata(),
        "device_name": _device_name(),
    }
    use_bearer = _looks_like_sanctum_token(cfg.api_token)
    try:
        data = _post_json(
            join_api_url(cfg.api_base_url, "access", "verify"),
            payload,
            timeout=timeout,
            bearer=use_bearer,
        )
    except Exception as exc:
        logger.warning("Access verify failed: %s", exc)
        return AccessResult(valid=False, message=f"Không kết nối được server: {exc}")

    message = str(data.get("message") or "")
    if _looks_like_internal_error(message):
        message = "Lỗi hệ thống. Vui lòng thử lại hoặc liên hệ admin."

    access_token = str(data.get("access_token") or "").strip()
    if access_token:
        save_api_config(api_email=cfg.api_email, api_token=access_token)
        cfg = load_api_config()

    return _access_result_from_data(data, message=message, access_token=access_token)


def exchange_desktop_code(
    *,
    code: str,
    state: str,
    redirect_uri: str,
    config: Optional[ApiConfig] = None,
    timeout: float = 15.0,
) -> AccessResult:
    cfg = config or load_api_config()
    if not (cfg.api_base_url or "").strip():
        return AccessResult(valid=False, message="Chưa cấu hình URL server.")

    payload = {
        "code": code,
        "state": state,
        "redirect_uri": redirect_uri,
        **client_metadata(),
    }
    try:
        data = _post_json(
            join_api_url(cfg.api_base_url, "access", "exchange"),
            payload,
            timeout=timeout,
            bearer=False,
        )
    except Exception as exc:
        logger.warning("Desktop auth exchange failed: %s", exc)
        return AccessResult(valid=False, message=f"Không đổi được mã đăng nhập: {exc}")

    message = str(data.get("message") or "")
    if _looks_like_internal_error(message):
        message = "Lỗi hệ thống. Vui lòng thử lại hoặc liên hệ admin."

    access_token = str(data.get("access_token") or "").strip()
    if access_token:
        email = str(data.get("email") or "").strip().lower()
        save_api_config(api_email=email, api_token=access_token)

    result = _access_result_from_data(data, message=message, access_token=access_token)
    _apply_simlock_quota(data)
    return result


def _access_result_from_data(
    data: dict[str, Any],
    *,
    message: str,
    access_token: str = "",
) -> AccessResult:
    token_count, token_used, token_remaining = _token_quota_fields(data)
    _apply_simlock_quota(data)
    return AccessResult(
        valid=bool(data.get("valid")),
        message=message,
        email=str(data.get("email") or "").strip().lower(),
        shop_name=str(data.get("shop_name") or ""),
        credits=int(data.get("credits") or 0),
        token_count=token_count,
        token_used=token_used,
        token_remaining=token_remaining,
        access_token=access_token or str(data.get("access_token") or "").strip(),
        simlock_count=_simlock_int(data, "simlock_count", default=_simlock_quota["count"]),
        simlock_used=_simlock_int(data, "simlock_used", default=_simlock_quota["used"]),
        simlock_remaining=_simlock_int(data, "simlock_remaining", default=_simlock_quota["remaining"]),
    )


def _looks_like_internal_error(message: str) -> bool:
    lower = message.lower()
    markers = (
        "sqlstate",
        "duplicate entry",
        "insert into ",
        "connection:",
        "sql:",
        "stack trace",
    )
    return any(marker in lower for marker in markers)


def verify_license(config: Optional[ApiConfig] = None, *, timeout: float = 15.0) -> AccessResult:
    return verify_access(config, timeout=timeout)


def logout_access(config: Optional[ApiConfig] = None, *, timeout: float = 15.0) -> bool:
    """Thu hồi token Sanctum hiện tại trên server."""
    cfg = config or load_api_config()
    token = cfg.api_token.strip()
    if not token or not _looks_like_sanctum_token(token):
        return True
    try:
        data = _post_json(
            join_api_url(cfg.api_base_url, "access", "logout"),
            {},
            timeout=timeout,
        )
        return bool(data.get("ok"))
    except Exception as exc:
        logger.warning("Access logout failed: %s", exc)
        return False


def list_services(
    config: Optional[ApiConfig] = None,
    *,
    timeout: float = 15.0,
) -> tuple[bool, str, list[dict[str, Any]], int]:
    cfg = config or load_api_config()
    if not cfg.enabled:
        return False, "Chưa cấu hình email và API token.", [], 0

    payload = {**_auth_payload(cfg), **client_metadata()}
    try:
        data = _get_json(join_api_url(cfg.api_base_url, "services"), payload, timeout=timeout)
    except Exception as exc:
        logger.warning("List services failed: %s", exc)
        return False, f"Không tải được dịch vụ: {exc}", [], 0

    if not data.get("ok"):
        return False, str(data.get("message") or "Không tải được dịch vụ."), [], 0

    services = data.get("services")
    if not isinstance(services, list):
        return False, "Phản hồi dịch vụ không hợp lệ.", [], 0

    return True, "OK", services, int(data.get("credits") or 0)


def fetch_simlock_quota(
    config: Optional[ApiConfig] = None,
    *,
    timeout: float = 15.0,
) -> SimlockQuotaResult:
    """Tải hạn mức check simlock miễn phí từ server (không cần credit)."""
    cfg = config or load_api_config()
    if not cfg.enabled:
        return SimlockQuotaResult(ok=False, message="Chưa cấu hình email và API token.")

    payload: dict[str, Any] = {**_auth_payload(cfg), **client_metadata()}
    try:
        data = _post_json(
            join_api_url(cfg.api_base_url, "albert", "simlock", "quota"),
            payload,
            timeout=timeout,
        )
    except Exception as exc:
        logger.warning("Fetch simlock quota failed: %s", exc)
        return SimlockQuotaResult(ok=False, message=f"Không tải được hạn mức: {exc}")

    _apply_simlock_quota(data)
    count, used, remaining = get_simlock_quota()
    return SimlockQuotaResult(
        ok=bool(data.get("ok")),
        message=str(data.get("message") or ""),
        simlock_count=count,
        simlock_used=used,
        simlock_remaining=remaining,
    )


def check_simlock(
    *,
    serial: str,
    imei1: str,
    imei2: str = "",
    config: Optional[ApiConfig] = None,
    timeout: float = 120.0,
) -> SimlockCheckResult:
    cfg = config or load_api_config()
    if not cfg.enabled:
        return SimlockCheckResult(ok=False, message="Chưa cấu hình email và API token.")

    payload: dict[str, Any] = {
        **_auth_payload(cfg),
        "serial": serial,
        "imei1": imei1,
        "imei2": imei2,
        **client_metadata(),
    }

    try:
        data = _post_json(join_api_url(cfg.api_base_url, "albert", "simlock"), payload, timeout=timeout)
    except Exception as exc:
        logger.warning("Simlock check failed: %s", exc)
        return SimlockCheckResult(ok=False, message=f"Kiểm tra simlock thất bại: {exc}")

    _apply_simlock_quota(data)
    return SimlockCheckResult(
        ok=bool(data.get("ok")),
        message=str(data.get("message") or ""),
        simlock=str(data.get("simlock") or ""),
        attempts=int(data.get("attempts") or 0),
        saved=bool(data.get("saved")),
        simlock_count=_simlock_int(data, "simlock_count", default=_simlock_quota["count"]),
        simlock_used=_simlock_int(data, "simlock_used", default=_simlock_quota["used"]),
        simlock_remaining=_simlock_int(data, "simlock_remaining", default=_simlock_quota["remaining"]),
    )


def submit_imei_order(
    *,
    imei1: str = "",
    imei2: str = "",
    serial: str = "",
    service_id: Optional[int] = None,
    service_ref: Optional[str] = None,
    config: Optional[ApiConfig] = None,
    timeout: float = 30.0,
) -> ImeiOrderResult:
    cfg = config or load_api_config()
    if not cfg.enabled:
        return ImeiOrderResult(ok=False, message="Chưa cấu hình email và API token.")

    payload: dict[str, Any] = {
        **_auth_payload(cfg),
        "imei1": imei1,
        "imei2": imei2,
        "serial": serial,
        **client_metadata(),
    }
    if service_id is not None:
        payload["service_id"] = service_id
    if service_ref:
        payload["service_ref"] = service_ref

    try:
        data = _post_json(join_api_url(cfg.api_base_url, "imei", "orders"), payload, timeout=timeout)
    except Exception as exc:
        logger.warning("Submit IMEI order failed: %s", exc)
        return ImeiOrderResult(ok=False, message=f"Đặt IMEI thất bại: {exc}")

    return ImeiOrderResult(
        ok=bool(data.get("ok")),
        message=str(data.get("message") or ""),
        order=data.get("order") if isinstance(data.get("order"), dict) else None,
        credits=int(data.get("credits") or 0),
        charged=bool(data.get("charged")),
    )


def submit_imei_orders_bulk(
    orders: list[dict[str, str]],
    *,
    service_id: Optional[int] = None,
    service_ref: Optional[str] = None,
    config: Optional[ApiConfig] = None,
    timeout: float = 60.0,
) -> ImeiOrderResult:
    cfg = config or load_api_config()
    if not cfg.enabled:
        return ImeiOrderResult(ok=False, message="Chưa cấu hình email và API token.")
    if not orders:
        return ImeiOrderResult(ok=True, message="Không có đơn để gửi.")

    payload: dict[str, Any] = {
        **_auth_payload(cfg),
        "orders": orders,
        **client_metadata(),
    }
    if service_id is not None:
        payload["service_id"] = service_id
    if service_ref:
        payload["service_ref"] = service_ref

    try:
        data = _post_json(join_api_url(cfg.api_base_url, "imei", "orders", "bulk"), payload, timeout=timeout)
    except Exception as exc:
        logger.warning("Bulk IMEI submit failed: %s", exc)
        return ImeiOrderResult(ok=False, message=f"Gửi IMEI hàng loạt thất bại: {exc}")

    errors = data.get("errors")
    orders_out = data.get("orders")

    return ImeiOrderResult(
        ok=bool(data.get("ok")),
        message=str(data.get("message") or ""),
        orders=orders_out if isinstance(orders_out, list) else None,
        errors=errors if isinstance(errors, list) else None,
        credits=int(data.get("credits") or 0),
    )


def list_imei_orders(
    *,
    config: Optional[ApiConfig] = None,
    timeout: float = 30.0,
) -> ImeiOrderResult:
    """Danh sách đơn gần đây của user — dùng khôi phục đơn chưa xong khi mở lại app."""
    cfg = config or load_api_config()
    if not cfg.enabled:
        return ImeiOrderResult(ok=False, message="Chưa cấu hình email và API token.")

    payload: dict[str, Any] = {
        **_auth_payload(cfg),
        **client_metadata(),
    }

    try:
        data = _get_json(join_api_url(cfg.api_base_url, "imei", "orders"), payload, timeout=timeout)
    except Exception as exc:
        logger.warning("List IMEI orders failed: %s", exc)
        return ImeiOrderResult(ok=False, message=f"Lấy danh sách đơn thất bại: {exc}")

    orders_out = data.get("orders")
    return ImeiOrderResult(
        ok=bool(data.get("ok")),
        message=str(data.get("message") or ""),
        orders=orders_out if isinstance(orders_out, list) else None,
        credits=int(data.get("credits") or 0),
    )


def fetch_orders_status(
    order_ids: list[int],
    *,
    config: Optional[ApiConfig] = None,
    timeout: float = 30.0,
) -> ImeiOrderResult:
    """Lấy trạng thái + kết quả nhiều đơn theo id (poll lô lớn)."""
    cfg = config or load_api_config()
    if not cfg.enabled:
        return ImeiOrderResult(ok=False, message="Chưa cấu hình email và API token.")
    if not order_ids:
        return ImeiOrderResult(ok=True, message="", orders=[])

    payload: dict[str, Any] = {
        **_auth_payload(cfg),
        "ids": list(order_ids),
        **client_metadata(),
    }

    try:
        data = _post_json(join_api_url(cfg.api_base_url, "imei", "orders", "status"), payload, timeout=timeout)
    except Exception as exc:
        logger.warning("Fetch orders status failed: %s", exc)
        return ImeiOrderResult(ok=False, message=f"Lấy trạng thái đơn thất bại: {exc}")

    orders_out = data.get("orders")

    return ImeiOrderResult(
        ok=bool(data.get("ok")),
        message=str(data.get("message") or ""),
        orders=orders_out if isinstance(orders_out, list) else None,
        credits=int(data.get("credits") or 0),
    )


def create_sickw_order(
    *,
    imei: str,
    config: Optional[ApiConfig] = None,
    timeout: float = 30.0,
) -> ImeiOrderResult:
    cfg = config or load_api_config()
    if not cfg.enabled:
        return ImeiOrderResult(ok=False, message="Chưa cấu hình email và API token.")

    payload: dict[str, Any] = {
        **_auth_payload(cfg),
        "imei": imei.strip(),
        **client_metadata(),
    }

    try:
        data = _post_json(join_api_url(cfg.api_base_url, "sickw", "create"), payload, timeout=timeout)
    except Exception as exc:
        logger.warning("Create Sickw order failed: %s", exc)
        return ImeiOrderResult(ok=False, message=f"Tạo đơn Sickw thất bại: {exc}")

    order = data.get("order") if isinstance(data.get("order"), dict) else None

    return ImeiOrderResult(
        ok=bool(data.get("ok")),
        message=str(data.get("message") or ""),
        order=order,
        credits=int(data.get("credits") or 0),
        charged=bool(data.get("ok")),
    )


def poll_sickw_order(
    order_id: int,
    *,
    config: Optional[ApiConfig] = None,
    timeout: float = 15.0,
) -> SickwOrderPollResult:
    cfg = config or load_api_config()
    if not cfg.enabled:
        return SickwOrderPollResult(ok=False, message="Chưa cấu hình email và API token.")

    payload = {**_auth_payload(cfg), **client_metadata()}
    try:
        data = _get_json(join_api_url(cfg.api_base_url, "sickw", "orders", str(order_id)), payload, timeout=timeout)
    except Exception as exc:
        logger.warning("Poll Sickw order failed: %s", exc)
        return SickwOrderPollResult(ok=False, message=f"Poll Sickw thất bại: {exc}")

    order = data.get("order") if isinstance(data.get("order"), dict) else None
    result = order.get("result") if isinstance(order, dict) else None

    return SickwOrderPollResult(
        ok=bool(data.get("ok")),
        message=str(data.get("message") or ""),
        completed=bool(data.get("completed")),
        failed=bool(data.get("failed")),
        order=order,
        result=result,
        credits=int(data.get("credits") or 0),
    )


def sync_records(
    records: list[DeviceRecord],
    config: Optional[ApiConfig] = None,
    *,
    service_id: Optional[int] = None,
    service_ref: str = "CHECK_IMEI",
    timeout: float = 60.0,
) -> tuple[bool, str]:
    """Gửi danh sách thiết bị lên server dưới dạng đơn IMEI."""
    cfg = config or load_api_config()
    if not cfg.enabled:
        return False, "Chưa cấu hình email và API token."
    if not records:
        return True, "Không có bản ghi để gửi."

    sid = service_id if service_id is not None else cfg.default_service_id
    sref = None if sid is not None else (cfg.default_service_ref or service_ref)

    orders = [
        {
            "imei1": r.imei1,
            "imei2": r.imei2,
            "serial": r.serial,
        }
        for r in records
        if r.imei1 or r.imei2 or r.serial
    ]

    if not orders:
        return False, "Không có IMEI/Serial hợp lệ trong danh sách."

    result = submit_imei_orders_bulk(
        orders,
        service_id=sid,
        service_ref=sref,
        config=cfg,
        timeout=timeout,
    )

    if result.orders:
        return result.ok, result.message
    return False, result.message


def _is_local_dev_host(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host.endswith(".test") or host in ("localhost", "127.0.0.1")


def _ssl_context(*, insecure: bool = False) -> ssl.SSLContext:
    if insecure:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx

    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _urlopen(req: urllib.request.Request, *, timeout: float):
    url = req.full_url
    insecure = _is_local_dev_host(url)
    ctx = _ssl_context(insecure=insecure)
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))
    try:
        return opener.open(req, timeout=timeout)
    except urllib.error.URLError as exc:
        if not insecure or "CERTIFICATE_VERIFY_FAILED" not in str(exc):
            raise
        # Chỉ dev (.test / localhost): fallback cert tự ký Herd/Valet
        fallback = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=_ssl_context(insecure=True))
        )
        return fallback.open(req, timeout=timeout)


def ping_server(config: Optional[ApiConfig] = None, *, timeout: float = 8.0) -> bool:
    cfg = config or load_api_config()
    if not cfg.api_base_url:
        return False
    try:
        url = join_api_url(cfg.api_base_url, "health")
        req = urllib.request.Request(url, method="GET")
        with _urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        ok = bool(data.get("ok"))
        log_get(url, ok=ok, detail=response_summary(data))
        return ok
    except Exception as exc:
        log_get(join_api_url(cfg.api_base_url, "health"), ok=False, detail=str(exc)[:80])
        return False


def _looks_like_sanctum_token(token: str) -> bool:
    """Sanctum plain text: `{id}|{secret}` — khác mã kích hoạt 48 ký tự."""
    if "|" not in token:
        return False
    token_id, _secret = token.split("|", 1)
    return token_id.isdigit() and bool(_secret.strip())


def _client_ip_headers(extra: Optional[dict[str, Any]] = None, *, bearer: bool = True) -> dict[str, str]:
    public_ip = fetch_public_ip()
    cfg = load_api_config()
    token = str((extra or {}).get("api_token") or cfg.api_token or "").strip()
    email = str((extra or {}).get("email") or cfg.api_email or "").strip()
    headers = {
        "Accept": "application/json",
        "User-Agent": "TaodenIMEITool/1.0",
    }
    if email:
        headers["X-Api-Email"] = email
    use_bearer = bearer and token and _looks_like_sanctum_token(token)
    if use_bearer:
        headers["Authorization"] = f"Bearer {token}"
    elif token:
        headers["X-Api-Token"] = token
    if public_ip:
        headers["X-Taoden-Client-Ip"] = public_ip
    return headers


def _get_json(url: str, params: dict[str, Any], *, timeout: float) -> dict[str, Any]:
    cfg = load_api_config()
    auth = _auth_payload(cfg)
    merged = {**auth, **params}
    query = urllib.parse.urlencode({k: v for k, v in merged.items() if v is not None and v != ""})
    full_url = f"{url}?{query}" if query else url
    req = urllib.request.Request(
        full_url,
        method="GET",
        headers=_client_ip_headers(auth),
    )
    try:
        with _urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(raw)
            log_get(url, ok=bool(data.get("ok", False)), detail=response_summary(data))
            return data
        except json.JSONDecodeError:
            log_get(url, ok=False, detail=f"HTTP {exc.code}")
            raise RuntimeError(f"HTTP {exc.code}: {raw[:200]}") from exc
    data = json.loads(raw)
    log_get(url, ok=bool(data.get("ok", True)), detail=response_summary(data))
    return data


def _post_json(
    url: str,
    payload: dict[str, Any],
    *,
    timeout: float,
    bearer: bool = True,
) -> dict[str, Any]:
    body_summary = payload_summary(payload)
    body = json.dumps(payload).encode("utf-8")
    headers = _client_ip_headers(payload, bearer=bearer)
    headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers=headers,
    )
    try:
        with _urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(raw)
            log_post(
                url,
                ok=bool(data.get("ok", False)),
                detail=response_summary(data),
                body=body_summary,
            )
            return data
        except json.JSONDecodeError:
            log_post(url, ok=False, detail=f"HTTP {exc.code}", body=body_summary)
            raise RuntimeError(f"HTTP {exc.code}: {raw[:200]}") from exc
    data = json.loads(raw)
    log_post(url, ok=bool(data.get("ok", True)), detail=response_summary(data), body=body_summary)
    return data
