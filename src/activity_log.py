"""Nhật ký hoạt động — hiển thị trên panel log của GUI."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Callable, Optional
from urllib.parse import urlparse

_handler: Optional[Callable[[str], None]] = None

_SENSITIVE_KEYS = frozenset({"api_token", "password", "token"})

# Không hiển thị trên panel Nhật ký (vẫn gọi API bình thường).
_SILENT_GET_PATH_SUFFIXES = ("/imei/orders",)
_SILENT_POST_PATH_PARTS = ("/access/verify", "/access/logout", "/imei/orders/status")


def set_log_handler(handler: Optional[Callable[[str], None]]) -> None:
    global _handler
    _handler = handler


def _emit(tag: str, message: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {tag} {message}"
    if _handler is not None:
        _handler(line)


def log_action(message: str) -> None:
    _emit("·", message)


def log_get(url: str, *, ok: bool = True, detail: str = "") -> None:
    path = _api_path(url)
    if not _should_log_get(path):
        return
    status = "OK" if ok else "LỖI"
    extra = f" — {detail}" if detail else ""
    _emit("GET", f"{path} [{status}]{extra}")


def log_post(url: str, *, ok: bool = True, detail: str = "", body: str = "") -> None:
    path = _api_path(url)
    if not _should_log_post(path):
        return
    status = "OK" if ok else "LỖI"
    parts = [p for p in (body, detail) if p]
    extra = f" — {' | '.join(parts)}" if parts else ""
    _emit("POST", f"{path} [{status}]{extra}")


def log_start(name: str, detail: str = "") -> None:
    suffix = f": {detail}" if detail else ""
    _emit("▶", f"{name} bắt đầu{suffix}")


def log_done(name: str, detail: str = "") -> None:
    suffix = f": {detail}" if detail else ""
    _emit("■", f"{name} xong{suffix}")


def log_error(message: str) -> None:
    _emit("✗", message)


def _api_path(url: str) -> str:
    parsed = urlparse(url)
    return parsed.path or url


def _should_log_get(path: str) -> bool:
    normalized = path.rstrip("/")
    if any(normalized.endswith(suffix) for suffix in _SILENT_GET_PATH_SUFFIXES):
        return False
    return True


def _should_log_post(path: str) -> bool:
    return not any(part in path for part in _SILENT_POST_PATH_PARTS)


def payload_summary(payload: dict[str, Any]) -> str:
    orders = payload.get("orders")
    if isinstance(orders, list):
        return f"{len(orders)} đơn"
    ids = payload.get("ids")
    if isinstance(ids, list):
        return f"{len(ids)} id"
    if payload.get("service_id") is not None:
        return f"service_id={payload['service_id']}"
    for key in ("imei1", "imei", "serial"):
        val = str(payload.get(key) or "").strip()
        if val:
            short = val if len(val) <= 12 else f"{val[:8]}…"
            return f"{key}={short}"
    return ""


def response_summary(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    parts: list[str] = []
    if "ok" in data:
        parts.append("ok" if data.get("ok") else "fail")
    if data.get("credits") is not None:
        from src.vnd_format import VND_LABEL, format_vnd

        parts.append(f"{VND_LABEL}={format_vnd(data['credits'])}")
    orders = data.get("orders")
    if isinstance(orders, list):
        parts.append(f"orders={len(orders)}")
    if data.get("completed"):
        parts.append("completed")
    errors = data.get("errors")
    if isinstance(errors, list) and errors:
        seen: set[str] = set()
        for item in errors:
            if not isinstance(item, dict):
                continue
            err_msg = str(item.get("message") or "").strip()
            if not err_msg or err_msg in seen:
                continue
            seen.add(err_msg)
            if len(err_msg) <= 60:
                parts.append(err_msg)
            else:
                parts.append(f"{err_msg[:57]}…")
            break
    elif data.get("message"):
        msg = str(data["message"]).strip()
        if msg and len(msg) <= 60:
            parts.append(msg)
        elif msg:
            parts.append(f"{msg[:57]}…")
    return ", ".join(parts)


def sanitize_for_log(text: str) -> str:
    """Ẩn token trong chuỗi log."""
    return re.sub(
        r'("api_token"\s*:\s*")[^"]+(")',
        r'\1***\2',
        text,
    )
