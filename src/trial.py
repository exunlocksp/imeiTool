"""Dùng thử 10 ngày — ngày bắt đầu cố định trong code (tạm thời, chưa license server)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

# Đổi ngày này mỗi lần phát hành bản dùng thử mới (YYYY, M, D).
TRIAL_START_DATE = date(2026, 6, 4)
TRIAL_DAYS = 10


@dataclass(frozen=True)
class TrialStatus:
    started_at: date
    days_left: int
    expired: bool


def get_trial_status() -> TrialStatus:
    today = date.today()
    if today < TRIAL_START_DATE:
        return TrialStatus(started_at=TRIAL_START_DATE, days_left=TRIAL_DAYS, expired=False)

    used_days = (today - TRIAL_START_DATE).days
    days_left = max(0, TRIAL_DAYS - used_days)
    expired = used_days >= TRIAL_DAYS
    return TrialStatus(started_at=TRIAL_START_DATE, days_left=days_left, expired=expired)


def trial_status_message() -> str:
    status = get_trial_status()
    if status.expired:
        return "Dùng thử: hết hạn"
    if status.days_left == 0:
        return "Dùng thử: hết hạn hôm nay"
    return f"Dùng thử: còn {status.days_left} ngày"


def trial_status_color() -> tuple[str, str]:
    """Màu chữ badge dùng thử trên footer."""
    status = get_trial_status()
    if status.expired or status.days_left <= 1:
        return ("#C62828", "#EF5350")
    if status.days_left <= 3:
        return ("#E65100", "#FFB74D")
    return ("#666666", "#AAAAAA")
