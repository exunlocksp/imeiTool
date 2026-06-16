"""Gọi API Albert simlock (miễn phí) — menu Check Simlock & run dịch vụ simlock."""

from __future__ import annotations

import logging

from src.api_client import SimlockCheckResult, check_simlock
from src.api_config import load_api_config
from src.models import DeviceRecord

logger = logging.getLogger(__name__)

SIMLOCK_PENDING_LABEL = "Đang xử lý…"
SIMLOCK_UNKNOWN_LABEL = "Không xác định"


def fetch_simlock(record: DeviceRecord) -> SimlockCheckResult | None:
    """Kiểm tra simlock qua server. Trả None nếu bỏ qua (chưa đăng nhập / thiếu IMEI)."""
    if not record.serial or not record.imei1:
        return None

    cfg = load_api_config()
    if not cfg.enabled:
        return None

    return check_simlock(
        serial=record.serial,
        imei1=record.imei1,
        imei2=record.imei2,
        config=cfg,
    )
