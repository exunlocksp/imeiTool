"""Định dạng số dư / giá VNĐ — dấu phẩy hàng nghìn."""

from __future__ import annotations

VND_LABEL = "VNĐ"


def format_vnd(amount: int | float) -> str:
    return f"{int(round(amount)):,}"


def format_signed_vnd(amount: int) -> str:
    if amount > 0:
        return f"+{format_vnd(amount)}"
    if amount < 0:
        return f"-{format_vnd(abs(amount))}"
    return "0"
