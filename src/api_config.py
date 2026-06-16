"""Cấu hình API — SQLite (settings) + keyring (token/email)."""

from __future__ import annotations

import os
import urllib.parse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.app_branding import APP_VERSION, BUNDLE_ID
from src.database import default_db_path
from src.secure_store import (
    clear_credentials as _clear_keyring_credentials,
    get_api_email,
    get_api_token,
    save_api_email,
    save_api_token,
)
from src.settings_store import get_settings_store

_DEFAULT_API_BASE = "https://tool.taoden.vn/api/v1"
DEFAULT_API_BASE = _DEFAULT_API_BASE
OFFLINE_GRACE_HOURS = 72
USB_SAVE_SERVICE_ID = 3

# Host API cũ (dev/ngrok) — tự chuyển sang production khi mở app.
_LEGACY_API_HOST_SUFFIXES = (".test",)
_LEGACY_API_HOSTS = frozenset({"localhost", "127.0.0.1", "tao02.vn"})
_LEGACY_API_HOST_PARTS = ("ngrok", "tao02", "imeitool")


@dataclass(frozen=True)
class ApiConfig:
    api_base_url: str
    api_email: str
    api_token: str
    default_service_id: Optional[int] = None
    default_service_ref: str = ""

    @property
    def license_key(self) -> str:
        """Alias cũ — cùng giá trị api_token."""
        return self.api_token

    @property
    def enabled(self) -> bool:
        return bool(
            self.api_base_url.strip()
            and self.api_email.strip()
            and self.api_token.strip()
        )


@dataclass(frozen=True)
class LicenseCache:
    valid: bool
    shop_name: str
    expires_at: str
    days_left: Optional[int]
    verified_at: datetime

    def within_grace(self) -> bool:
        if not self.valid:
            return False
        age_h = (datetime.now() - self.verified_at).total_seconds() / 3600.0
        return age_h <= OFFLINE_GRACE_HOURS


def config_path() -> Path:
    """Đường dẫn DB cấu hình (cùng file với danh sách thiết bị)."""
    return default_db_path()


def load_api_config() -> ApiConfig:
    store = get_settings_store()
    base = _normalize_api_base_url(
        (
            os.environ.get("TAODEN_API_URL")
            or store.get("api_base_url")
            or _DEFAULT_API_BASE
        ).strip()
    )
    allow_env = _allow_env_credential_override(base)

    email = (
        (os.environ.get("TAODEN_API_EMAIL") if allow_env else None)
        or get_api_email()
        or ""
    ).strip().lower()

    token = (
        (
            os.environ.get("TAODEN_API_TOKEN")
            or os.environ.get("TAODEN_LICENSE_KEY")
            if allow_env
            else None
        )
        or get_api_token()
        or ""
    ).strip()

    service_ref = store.get("default_service_ref", "").strip()
    raw_sid = store.get("default_service_id", "").strip()
    default_sid = int(raw_sid) if raw_sid.isdigit() else USB_SAVE_SERVICE_ID

    return ApiConfig(
        api_base_url=base,
        api_email=email,
        api_token=token,
        default_service_id=default_sid,
        default_service_ref=service_ref,
    )


def save_api_config(
    *,
    api_email: Optional[str] = None,
    api_token: Optional[str] = None,
    license_key: Optional[str] = None,
    api_base_url: Optional[str] = None,
    default_service_id: Optional[int] = None,
    default_service_ref: Optional[str] = None,
) -> None:
    store = get_settings_store()
    if api_email is not None:
        save_api_email(api_email)
    token = (api_token or license_key or "").strip()
    if token:
        save_api_token(token)
    if api_base_url is not None:
        store.set("api_base_url", _normalize_api_base_url(api_base_url.strip()))
    if default_service_id is not None:
        store.set("default_service_id", str(int(default_service_id)))
    if default_service_ref is not None:
        store.set("default_service_ref", default_service_ref.strip())


def clear_api_credentials() -> None:
    """Xóa token/email — dùng khi đăng xuất hoặc đổi tài khoản."""
    _clear_keyring_credentials()
    store = get_settings_store()
    store.clear_license_cache()


def save_license_cache(
    *,
    license_key: str,
    api_email: str = "",
    valid: bool,
    shop_name: str = "",
    expires_at: str = "",
    days_left: Optional[int] = None,
) -> None:
    del license_key, api_email
    get_settings_store().save_license_cache(
        valid=valid,
        shop_name=shop_name,
        expires_at=expires_at,
        days_left=days_left,
    )


def load_license_cache(license_key: str, api_email: str = "") -> Optional[LicenseCache]:
    cfg = load_api_config()
    if cfg.api_token.strip() != license_key.strip():
        return None
    if api_email.strip() and cfg.api_email.strip().lower() != api_email.strip().lower():
        return None
    row = get_settings_store().load_license_cache_row()
    if row is None:
        return None
    return LicenseCache(
        valid=bool(row["valid"]),
        shop_name=str(row["shop_name"]),
        expires_at=str(row["expires_at"]),
        days_left=row["days_left"],
        verified_at=row["verified_at"],
    )


def client_metadata() -> dict[str, str]:
    from src.api_client import fetch_public_ip

    meta = {
        "app_version": APP_VERSION,
        "bundle_id": BUNDLE_ID,
    }
    public_ip = fetch_public_ip()
    if public_ip:
        meta["client_public_ip"] = public_ip
    return meta


def _collapse_url_path(path: str) -> str:
    segments = [segment for segment in (path or "").split("/") if segment]
    return "/" + "/".join(segments) if segments else ""


def join_api_url(base_url: str, *parts: str) -> str:
    """Ghép base API + endpoint — tránh `//` thừa trong URL."""
    base = _normalize_api_base_url(base_url)
    tail = "/".join(part.strip("/") for part in parts if part and part.strip("/"))
    return f"{base}/{tail}" if tail else base


def _normalize_api_base_url(url: str) -> str:
    url = url.strip()
    if not url:
        return _DEFAULT_API_BASE

    parsed = urllib.parse.urlparse(url)
    path = _collapse_url_path(parsed.path or "")
    if not path:
        path = "/api/v1"

    host = (parsed.hostname or "").lower()
    local = host.endswith(".test") or host in ("localhost", "127.0.0.1")
    scheme = parsed.scheme or "https"
    if local and scheme == "http":
        scheme = "https"

    return urllib.parse.urlunparse(
        (scheme, parsed.netloc, path.rstrip("/"), "", "", "")
    ).rstrip("/")


def _is_legacy_api_host(host: str) -> bool:
    """True nếu host là dev/cũ — cần chuyển sang tool.taoden.vn."""
    h = (host or "").lower().strip()
    if not h or h == "tool.taoden.vn":
        return False
    if h in _LEGACY_API_HOSTS:
        return True
    if any(h.endswith(suffix) for suffix in _LEGACY_API_HOST_SUFFIXES):
        return True
    return any(part in h for part in _LEGACY_API_HOST_PARTS)


def _allow_env_credential_override(base_url: str) -> bool:
    """
    TAODEN_API_EMAIL / TAODEN_API_TOKEN chỉ áp dụng trên dev hoặc khi bật rõ ràng.
    Tránh lộ credential qua env trên máy production.
    """
    if os.environ.get("TAODEN_ALLOW_ENV_CREDENTIALS", "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        return True
    parsed = urllib.parse.urlparse(base_url)
    host = (parsed.hostname or "").lower()
    return host.endswith(".test") or host in ("localhost", "127.0.0.1", "::1")


def migrate_stored_api_base_url() -> bool:
    """
    Nếu SQLite còn URL dev/cũ thì ghi đè production.
    Dev override: đặt env TAODEN_API_URL (không migrate khi env có giá trị).
    """
    if os.environ.get("TAODEN_API_URL", "").strip():
        return False

    store = get_settings_store()
    stored = store.get("api_base_url", "").strip()
    if not stored:
        return False

    parsed = urllib.parse.urlparse(_normalize_api_base_url(stored))
    host = (parsed.hostname or "").lower()
    if not _is_legacy_api_host(host):
        return False

    store.set("api_base_url", _DEFAULT_API_BASE)
    return True
