"""Cửa sổ About riêng — không dùng panel mặc định Python/macOS."""

from __future__ import annotations

import sys
import tkinter as tk
import webbrowser
from typing import Optional

import customtkinter as ctk

from src.app_branding import ZALO_CHAT_URL, app_icon_path, header_logo_path


def show_about_dialog(
    parent: tk.Misc,
    app_name: str,
    app_version: str,
    credits_text: str,
) -> None:
    existing: Optional[ctk.CTkToplevel] = getattr(parent, "_about_win", None)
    if existing is not None and existing.winfo_exists():
        existing.focus()
        existing.lift()
        return

    win = ctk.CTkToplevel(parent)
    win.title(f"Về {app_name}")
    win.geometry("500x520")
    win.minsize(440, 460)
    win.resizable(True, True)
    win.transient(parent)
    win.grab_set()
    parent._about_win = win  # type: ignore[attr-defined]

    body = ctk.CTkFrame(win, fg_color="transparent")
    body.pack(fill=tk.BOTH, expand=True, padx=24, pady=(20, 12))
    body.grid_columnconfigure(0, weight=1)
    body.grid_rowconfigure(3, weight=1)

    logo_ref: list[Optional[ctk.CTkImage]] = [None]
    logo_path = header_logo_path() or app_icon_path()
    if logo_path is not None and logo_path.suffix.lower() in (".png", ".gif", ".jpg", ".jpeg", ".webp"):
        try:
            logo_ref[0] = ctk.CTkImage(light_image=str(logo_path), dark_image=str(logo_path), size=(72, 72))
            ctk.CTkLabel(body, image=logo_ref[0], text="").grid(row=0, column=0, pady=(0, 10))
            win._about_logo_ref = logo_ref[0]  # type: ignore[attr-defined]
        except Exception:
            pass

    ctk.CTkLabel(
        body,
        text=app_name,
        font=ctk.CTkFont(size=22, weight="bold"),
    ).grid(row=1, column=0, sticky="ew")

    ctk.CTkLabel(
        body,
        text=f"Phiên bản {app_version}",
        font=ctk.CTkFont(size=14),
        text_color=("#555555", "#AAAAAA"),
    ).grid(row=2, column=0, sticky="ew", pady=(2, 12))

    textbox = ctk.CTkTextbox(
        body,
        wrap=tk.WORD,
        font=ctk.CTkFont(size=13),
        activate_scrollbars=True,
    )
    textbox.grid(row=3, column=0, sticky="nsew", pady=(0, 10))
    textbox.insert("1.0", credits_text.strip())
    textbox.configure(state=tk.DISABLED)

    ctk.CTkLabel(
        body,
        text="© Taoden.vn · Exshop.vn",
        font=ctk.CTkFont(size=12),
        text_color=("#666666", "#999999"),
    ).grid(row=4, column=0, sticky="ew", pady=(0, 8))

    btn_row = ctk.CTkFrame(win, fg_color="transparent")
    btn_row.pack(fill=tk.X, padx=24, pady=(0, 18))

    def _close() -> None:
        win.grab_release()
        win.destroy()

    def _open_zalo() -> None:
        webbrowser.open(ZALO_CHAT_URL)

    ctk.CTkButton(
        btn_row,
        text="Chat Zalo",
        width=140,
        fg_color="#0068FF",
        hover_color="#0052CC",
        command=_open_zalo,
    ).pack(anchor=tk.CENTER)

    if logo_path is not None and logo_path.suffix.lower() == ".icns" and sys.platform == "darwin":
        try:
            win.iconbitmap(str(logo_path))
        except Exception:
            pass

    win.protocol("WM_DELETE_WINDOW", _close)
    win.after(50, win.focus)
