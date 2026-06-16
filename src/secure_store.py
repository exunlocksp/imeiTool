"""Secret qua Keychain (macOS) / Credential Manager (Windows)."""

from __future__ import annotations

import logging

from src.app_branding import BUNDLE_ID

logger = logging.getLogger(__name__)

_SERVICE = BUNDLE_ID
_KEY_TOKEN = "api_token"
_KEY_EMAIL = "api_email"


def get_api_token() -> str:
    return _get_secret(_KEY_TOKEN)


def get_api_email() -> str:
    return _get_secret(_KEY_EMAIL).lower()


def save_api_token(token: str) -> None:
    _set_secret(_KEY_TOKEN, token)


def save_api_email(email: str) -> None:
    _set_secret(_KEY_EMAIL, email.lower())


def clear_credentials() -> None:
    _delete_secret(_KEY_TOKEN)
    _delete_secret(_KEY_EMAIL)


def _get_secret(name: str) -> str:
    try:
        import keyring

        value = keyring.get_password(_SERVICE, name)
        return (value or "").strip()
    except Exception as exc:
        logger.warning("Keyring đọc %s thất bại: %s", name, exc)
        return ""


def _set_secret(name: str, value: str) -> None:
    value = (value or "").strip()
    try:
        import keyring

        if value:
            keyring.set_password(_SERVICE, name, value)
        else:
            _delete_secret(name)
    except Exception as exc:
        logger.warning("Keyring ghi %s thất bại: %s", name, exc)


def _delete_secret(name: str) -> None:
    try:
        import keyring
        from keyring.errors import PasswordDeleteError

        try:
            keyring.delete_password(_SERVICE, name)
        except PasswordDeleteError:
            pass
    except Exception as exc:
        logger.debug("Keyring xóa %s: %s", name, exc)
