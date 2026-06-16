"""Cấu hình app lưu SQLite — không dùng file JSON."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from src.database import default_db_path

logger = logging.getLogger(__name__)

_LEGACY_JSON = Path.home() / ".taoden-imei-tool.json"

_store: Optional["AppSettingsStore"] = None


class AppSettingsStore:
    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = path or default_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()
        self._migrate_legacy_json()
        self._migrate_api_base_url()
        self._purge_legacy_json_files()

    def _init_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL DEFAULT ''
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS license_cache (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                valid INTEGER NOT NULL DEFAULT 0,
                shop_name TEXT NOT NULL DEFAULT '',
                expires_at TEXT NOT NULL DEFAULT '',
                days_left INTEGER,
                verified_at TEXT NOT NULL DEFAULT ''
            )
            """
        )
        self._conn.commit()

    def get(self, key: str, default: str = "") -> str:
        row = self._conn.execute(
            "SELECT value FROM app_settings WHERE key=?",
            (key,),
        ).fetchone()
        if row is None:
            return default
        return str(row["value"] or default)

    def set(self, key: str, value: str) -> None:
        self._conn.execute(
            """
            INSERT INTO app_settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (key, value),
        )
        self._conn.commit()

    def delete(self, key: str) -> None:
        self._conn.execute("DELETE FROM app_settings WHERE key=?", (key,))
        self._conn.commit()

    def clear_license_cache(self) -> None:
        self._conn.execute("DELETE FROM license_cache WHERE id=1")
        self._conn.commit()

    def save_license_cache(
        self,
        *,
        valid: bool,
        shop_name: str = "",
        expires_at: str = "",
        days_left: Optional[int] = None,
        verified_at: Optional[str] = None,
    ) -> None:
        verified_at = (verified_at or "").strip() or datetime.now().isoformat(
            timespec="seconds"
        )
        self._conn.execute(
            """
            INSERT INTO license_cache (id, valid, shop_name, expires_at, days_left, verified_at)
            VALUES (1, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                valid=excluded.valid,
                shop_name=excluded.shop_name,
                expires_at=excluded.expires_at,
                days_left=excluded.days_left,
                verified_at=excluded.verified_at
            """,
            (
                int(valid),
                shop_name,
                expires_at,
                days_left,
                verified_at,
            ),
        )
        self._conn.commit()

    def load_license_cache_row(self) -> Optional[dict[str, Any]]:
        row = self._conn.execute(
            "SELECT valid, shop_name, expires_at, days_left, verified_at FROM license_cache WHERE id=1"
        ).fetchone()
        if row is None:
            return None
        try:
            verified_at = datetime.fromisoformat(str(row["verified_at"] or ""))
        except ValueError:
            return None
        days = row["days_left"]
        return {
            "valid": bool(row["valid"]),
            "shop_name": str(row["shop_name"] or ""),
            "expires_at": str(row["expires_at"] or ""),
            "days_left": int(days) if days is not None else None,
            "verified_at": verified_at,
        }

    def _migrate_api_base_url(self) -> None:
        import os
        import urllib.parse

        from src.api_config import _DEFAULT_API_BASE, _is_legacy_api_host, _normalize_api_base_url

        if os.environ.get("TAODEN_API_URL", "").strip():
            return

        stored = self.get("api_base_url", "").strip()
        if not stored:
            return

        host = (
            urllib.parse.urlparse(_normalize_api_base_url(stored)).hostname or ""
        ).lower()
        if not _is_legacy_api_host(host):
            return

        self.set("api_base_url", _DEFAULT_API_BASE)
        logger.info("Đã chuyển API URL cũ (%s) → %s", stored, _DEFAULT_API_BASE)

    def _migrate_legacy_json(self) -> None:
        from src.secure_store import get_api_email, get_api_token, save_api_email, save_api_token

        if get_api_token() or get_api_email():
            return

        sources = [_LEGACY_JSON, _LEGACY_JSON.with_suffix(".json.migrated")]
        for path in sources:
            if not path.is_file():
                continue
            if self._import_legacy_json(path, save_api_token=save_api_token, save_api_email=save_api_email):
                logger.info("Đã chuyển cấu hình từ %s sang DB + keyring", path)
                self._purge_legacy_json_files()
                return

    def _purge_legacy_json_files(self) -> None:
        from src.secure_store import get_api_token

        if not get_api_token():
            return

        for path in (_LEGACY_JSON, _LEGACY_JSON.with_suffix(".json.migrated")):
            if not path.is_file():
                continue
            try:
                path.unlink()
                logger.info("Đã xóa file JSON legacy: %s", path)
            except OSError as exc:
                logger.warning("Không xóa được %s: %s", path, exc)

    def _import_legacy_json(self, path: Path, *, save_api_token, save_api_email) -> bool:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Bỏ qua migrate %s: %s", path, exc)
            return False
        if not isinstance(raw, dict):
            return False

        token = str(raw.get("api_token") or raw.get("license_key") or "").strip()
        email = str(
            raw.get("api_email") or raw.get("email") or raw.get("license_email") or ""
        ).strip()
        if not token and not email and not raw.get("api_base_url") and not raw.get("license_cache"):
            return False

        if token:
            save_api_token(token)
        if email:
            save_api_email(email)

        if raw.get("api_base_url"):
            from src.api_config import _is_legacy_api_host, _normalize_api_base_url, _DEFAULT_API_BASE
            import urllib.parse

            raw_url = str(raw["api_base_url"]).strip()
            host = (urllib.parse.urlparse(_normalize_api_base_url(raw_url)).hostname or "").lower()
            if _is_legacy_api_host(host):
                self.set("api_base_url", _DEFAULT_API_BASE)
            else:
                self.set("api_base_url", raw_url)
        if raw.get("default_service_ref") is not None:
            self.set("default_service_ref", str(raw["default_service_ref"] or "").strip())
        if raw.get("default_service_id") is not None:
            self.set("default_service_id", str(int(raw["default_service_id"])))

        cache = raw.get("license_cache")
        if isinstance(cache, dict):
            days = cache.get("days_left")
            self.save_license_cache(
                valid=bool(cache.get("valid")),
                shop_name=str(cache.get("shop_name") or ""),
                expires_at=str(cache.get("expires_at") or ""),
                days_left=int(days) if days is not None else None,
                verified_at=str(cache.get("verified_at") or ""),
            )
        return bool(token or email or raw.get("api_base_url") or cache)


def get_settings_store() -> AppSettingsStore:
    global _store
    if _store is None:
        _store = AppSettingsStore()
    return _store
