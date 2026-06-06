"""Dùng thử 10 ngày — ngày bắt đầu cố định trong code (tạm thời, chưa license server)."""

from __future__ import annotations

import tkinter as tk
import webbrowser
from dataclasses import dataclass
from datetime import date

import customtkinter as ctk

from src.app_branding import APP_NAME, ZALO_CHAT_URL

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


def show_trial_expired_dialog(parent: tk.Misc) -> None:
    win = ctk.CTkToplevel(parent)
    win.title("Hết hạn dùng thử")
    win.geometry("440x280")
    win.resizable(False, False)
    win.transient(parent)
    win.grab_set()

    body = ctk.CTkFrame(win, fg_color="transparent")
    body.pack(fill=tk.BOTH, expand=True, padx=28, pady=(24, 12))

    ctk.CTkLabel(
        body,
        text="Hết hạn dùng thử",
        font=ctk.CTkFont(size=20, weight="bold"),
        text_color=("#C62828", "#EF5350"),
    ).pack(anchor=tk.W, pady=(0, 10))

    message = (
        f"{APP_NAME} đã hết thời gian dùng thử {TRIAL_DAYS} ngày.\n\n"
        "Vui lòng liên hệ Chat Zalo để gia hạn và tiếp tục sử dụng."
    )
    ctk.CTkLabel(
        body,
        text=message,
        font=ctk.CTkFont(size=14),
        justify=tk.LEFT,
        wraplength=360,
    ).pack(anchor=tk.W, pady=(0, 16))

    def _close() -> None:
        win.grab_release()
        win.destroy()
        parent.quit()

    def _open_zalo() -> None:
        webbrowser.open(ZALO_CHAT_URL)

    ctk.CTkButton(
        body,
        text="Chat Zalo",
        width=160,
        fg_color="#0068FF",
        hover_color="#0052CC",
        command=_open_zalo,
    ).pack(anchor=tk.CENTER)

    win.protocol("WM_DELETE_WINDOW", _close)
    win.after(50, win.focus)


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
