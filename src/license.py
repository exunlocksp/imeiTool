"""Trạng thái license — server API hoặc dùng thử local."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from src.api_client import LicenseResult, logout_access, verify_license
from src.api_client import _looks_like_sanctum_token
from src.secure_store import save_api_token
from src.vnd_format import VND_LABEL, format_vnd
from src.api_config import (
    ApiConfig,
    clear_api_credentials,
    load_api_config,
    save_license_cache,
)
from src.trial import TRIAL_DAYS, get_trial_status

logger = logging.getLogger(__name__)

_status: Optional["LicenseStatus"] = None


class LicenseMode(str, Enum):
    SERVER = "server"
    OFFLINE = "offline"
    TRIAL = "trial"


@dataclass(frozen=True)
class LicenseStatus:
    mode: LicenseMode
    valid: bool
    blocked: bool
    days_left: Optional[int]
    shop_name: str
    expires_at: str
    message: str
    credits: int = 0
    simlock_count: int = 0
    simlock_remaining: int = 0

    @property
    def expired(self) -> bool:
        return self.blocked


def refresh_license_status() -> LicenseStatus:
    global _status
    cfg = load_api_config()
    if not cfg.enabled:
        _status = LicenseStatus(
            mode=LicenseMode.SERVER,
            valid=False,
            blocked=True,
            days_left=None,
            shop_name="",
            expires_at="",
            message="Chưa đăng nhập. Nhập email và API token để sử dụng app.",
        )
        return _status

    _status = _status_from_server(cfg)
    return _status


def get_license_status() -> LicenseStatus:
    if _status is None:
        return refresh_license_status()
    return _status


def _status_fields_from_result(result: LicenseResult) -> dict[str, int | str]:
    return {
        "credits": int(result.credits or 0),
        "simlock_count": int(result.simlock_count or 0),
        "simlock_remaining": int(result.simlock_remaining or 0),
    }


def _account_status_message(result: LicenseResult) -> str:
    rows = account_info_rows_from_result(result)
    if not rows:
        return result.message
    return "\n".join(value for _label, value in rows)


def account_info_rows_from_result(result: LicenseResult) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    if result.shop_name:
        rows.append(("Tên tài khoản", result.shop_name))
    if result.valid:
        rows.append(("Số tiền", f"{format_vnd(result.credits)} {VND_LABEL}"))
        if result.simlock_count:
            rows.append(
                (
                    "Quota check simlock free",
                    f"{result.simlock_remaining}/{result.simlock_count}",
                )
            )
    return rows


def account_info_rows(status: Optional[LicenseStatus] = None) -> list[tuple[str, str]]:
    s = status or get_license_status()
    if not s.valid:
        return []
    rows: list[tuple[str, str]] = []
    cfg = load_api_config()
    if cfg.api_base_url:
        rows.append(("Máy chủ API", cfg.api_base_url.replace("https://", "").replace("/api/v1", "")))
    if s.shop_name:
        rows.append(("Tên tài khoản", s.shop_name))
    rows.append(("Số tiền", f"{format_vnd(s.credits)} {VND_LABEL}"))
    if s.simlock_count:
        rows.append(
            ("Quota check simlock free", f"{s.simlock_remaining}/{s.simlock_count}")
        )
    return rows


def _is_session_refresh_message(message: str) -> bool:
    lower = (message or "").lower()
    return (
        "hết hạn" in lower
        or "đăng nhập google lại" in lower
        or "token không hợp lệ" in lower
        or "đã thu hồi" in lower
    )


def session_needs_browser_refresh() -> bool:
    cfg = load_api_config()
    if not cfg.api_email.strip():
        return False
    status = get_license_status()
    return not status.valid and _is_session_refresh_message(status.message)


def logout_license() -> None:
    global _status
    logout_access()
    clear_api_credentials()
    _status = LicenseStatus(
        mode=LicenseMode.SERVER,
        valid=False,
        blocked=True,
        days_left=None,
        shop_name="",
        expires_at="",
        message="Chưa đăng nhập.",
    )


def license_status_message() -> str:
    s = get_license_status()
    if s.blocked:
        if _is_session_refresh_message(s.message):
            return "Phiên hết hạn — đăng nhập Google lại"
        if "thiếu email" in (s.message or "").lower():
            return "Chưa đăng nhập — bấm Tài khoản API"
        return s.message or "Chưa đăng nhập"
    if s.mode == LicenseMode.SERVER and s.message:
        return s.message.replace("\n", " — ")
    if s.mode == LicenseMode.OFFLINE:
        name = s.shop_name or "Đã lưu"
        return f"{name} (offline)"
    return s.shop_name or "Đã đăng nhập"


def license_status_color() -> tuple[str, str]:
    s = get_license_status()
    if s.blocked:
        return ("#C62828", "#EF5350")
    if s.mode in (LicenseMode.SERVER, LicenseMode.OFFLINE):
        if s.days_left is not None and s.days_left <= 7:
            return ("#E65100", "#FFB74D")
        return ("#2E7D32", "#81C784")
    if s.days_left is not None and s.days_left <= 1:
        return ("#C62828", "#EF5350")
    if s.days_left is not None and s.days_left <= 3:
        return ("#E65100", "#FFB74D")
    return ("#666666", "#AAAAAA")


def apply_license_result(result: LicenseResult, cfg: ApiConfig) -> LicenseStatus:
    global _status
    if result.valid:
        save_license_cache(
            license_key=cfg.api_token,
            api_email=cfg.api_email,
            valid=True,
            shop_name=result.shop_name,
            expires_at=result.expires_at,
            days_left=result.days_left,
        )
        msg = _account_status_message(result)
        fields = _status_fields_from_result(result)
        _status = LicenseStatus(
            mode=LicenseMode.SERVER,
            valid=True,
            blocked=False,
            days_left=result.days_left,
            shop_name=result.shop_name,
            expires_at=result.expires_at,
            message=msg,
            credits=int(fields["credits"]),
            simlock_count=int(fields["simlock_count"]),
            simlock_remaining=int(fields["simlock_remaining"]),
        )
    else:
        _status = LicenseStatus(
            mode=LicenseMode.SERVER,
            valid=False,
            blocked=True,
            days_left=0,
            shop_name=result.shop_name,
            expires_at=result.expires_at,
            message=result.message,
        )
    return _status


def _status_from_server(cfg: ApiConfig) -> LicenseStatus:
    result = verify_license(cfg)
    if result.valid:
        save_license_cache(
            license_key=cfg.api_token,
            api_email=cfg.api_email,
            valid=True,
            shop_name=result.shop_name,
            expires_at=result.expires_at,
            days_left=result.days_left,
        )
        msg = _account_status_message(result)
        fields = _status_fields_from_result(result)
        return LicenseStatus(
            mode=LicenseMode.SERVER,
            valid=True,
            blocked=False,
            days_left=result.days_left,
            shop_name=result.shop_name,
            expires_at=result.expires_at,
            message=msg,
            credits=int(fields["credits"]),
            simlock_count=int(fields["simlock_count"]),
            simlock_remaining=int(fields["simlock_remaining"]),
        )

    if _is_network_error(result.message):
        hint = result.message
        if "certificate" in hint.lower() or "ssl" in hint.lower():
            hint += " — kiểm tra API URL (mặc định https://tool.taoden.vn/api/v1) và đồng hồ hệ thống."
        return LicenseStatus(
            mode=LicenseMode.SERVER,
            valid=False,
            blocked=True,
            days_left=0,
            shop_name="",
            expires_at="",
            message=hint,
        )

    if _looks_like_sanctum_token(cfg.api_token) and _is_session_refresh_message(result.message):
        save_api_token("")

    return LicenseStatus(
        mode=LicenseMode.SERVER,
        valid=False,
        blocked=True,
        days_left=0,
        shop_name=result.shop_name,
        expires_at=result.expires_at,
        message=result.message,
    )


def _status_from_trial() -> LicenseStatus:
    trial = get_trial_status()
    return LicenseStatus(
        mode=LicenseMode.TRIAL,
        valid=not trial.expired,
        blocked=trial.expired,
        days_left=trial.days_left,
        shop_name="",
        expires_at="",
        message="Dùng thử local" if not trial.expired else f"Hết hạn dùng thử {TRIAL_DAYS} ngày",
    )


def _is_network_error(message: str) -> bool:
    lower = message.lower()
    return "không kết nối" in lower or "urlopen error" in lower or "timed out" in lower
