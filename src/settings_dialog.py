"""Hộp thoại Cài đặt — cột bảng và mục in."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox
from typing import Callable

import customtkinter as ctk

from src.app_settings import (
    PRINT_FIELD_KEYS,
    PRINT_FIELD_LABELS,
    TABLE_COLUMN_KEYS,
    TABLE_COLUMN_LABELS,
    AppSettings,
)

class SettingsDialog(ctk.CTkToplevel):
    def __init__(
        self,
        parent: tk.Misc,
        settings: AppSettings,
        on_save: Callable[[AppSettings], None],
    ) -> None:
        super().__init__(parent)
        self._on_save = on_save
        self._table_vars: dict[str, tk.BooleanVar] = {}
        self._print_vars: dict[str, tk.BooleanVar] = {}

        self.title("Cài đặt")
        self.geometry("460x520")
        self.minsize(400, 420)
        self.transient(parent)
        self.grab_set()

        body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        body.pack(fill=tk.BOTH, expand=True, padx=16, pady=(16, 8))

        ctk.CTkLabel(
            body,
            text="Bảng",
            font=ctk.CTkFont(size=15, weight="bold"),
            anchor=tk.W,
        ).pack(anchor=tk.W, pady=(0, 6))
        ctk.CTkLabel(
            body,
            text="Cột được tick sẽ hiển thị trên bảng.",
            text_color=("#666666", "#AAAAAA"),
            anchor=tk.W,
        ).pack(anchor=tk.W, pady=(0, 8))

        table_frame = ctk.CTkFrame(body, corner_radius=8)
        table_frame.pack(fill=tk.X, pady=(0, 16))
        for key in TABLE_COLUMN_KEYS:
            var = tk.BooleanVar(value=settings.table_columns.get(key, True))
            self._table_vars[key] = var
            ctk.CTkCheckBox(
                table_frame,
                text=TABLE_COLUMN_LABELS[key],
                variable=var,
                font=ctk.CTkFont(size=13),
            ).pack(anchor=tk.W, padx=12, pady=4)

        ctk.CTkLabel(
            body,
            text="In",
            font=ctk.CTkFont(size=15, weight="bold"),
            anchor=tk.W,
        ).pack(anchor=tk.W, pady=(0, 6))
        ctk.CTkLabel(
            body,
            text="Mục được tick sẽ in trên nhãn.",
            text_color=("#666666", "#AAAAAA"),
            anchor=tk.W,
        ).pack(anchor=tk.W, pady=(0, 8))

        print_frame = ctk.CTkFrame(body, corner_radius=8)
        print_frame.pack(fill=tk.X, pady=(0, 8))
        for key in PRINT_FIELD_KEYS:
            var = tk.BooleanVar(value=settings.print_fields.get(key, True))
            self._print_vars[key] = var
            ctk.CTkCheckBox(
                print_frame,
                text=PRINT_FIELD_LABELS[key],
                variable=var,
                font=ctk.CTkFont(size=13),
            ).pack(anchor=tk.W, padx=12, pady=4)

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.pack(fill=tk.X, padx=16, pady=(0, 16))

        ctk.CTkButton(
            actions,
            text="Hủy",
            width=100,
            fg_color=("#E8E8E8", "#3A3A3A"),
            text_color=("#1A1A1A", "#EEEEEE"),
            hover_color=("#D0D0D0", "#4A4A4A"),
            command=self.destroy,
        ).pack(side=tk.RIGHT, padx=(8, 0))

        ctk.CTkButton(
            actions,
            text="Lưu",
            width=100,
            command=self._save,
        ).pack(side=tk.RIGHT)

        self.bind("<Escape>", lambda _e: self.destroy())
        self.after(50, self.focus_set)

    def _save(self) -> None:
        settings = AppSettings(
            table_columns={key: var.get() for key, var in self._table_vars.items()},
            print_fields={key: var.get() for key, var in self._print_vars.items()},
        )
        if not settings.visible_table_columns():
            messagebox.showwarning(
                "Cài đặt",
                "Phải chọn ít nhất một cột hiển thị trên bảng.",
                parent=self,
            )
            return
        if not settings.has_print_content():
            messagebox.showwarning(
                "Cài đặt",
                "Phải chọn ít nhất một mục in.",
                parent=self,
            )
            return
        try:
            settings.save()
        except OSError as exc:
            messagebox.showerror("Cài đặt", f"Không lưu được cài đặt:\n{exc}", parent=self)
            return
        self._on_save(settings)
        self.destroy()


def open_settings_dialog(
    parent: tk.Misc,
    settings: AppSettings,
    on_save: Callable[[AppSettings], None],
) -> None:
    SettingsDialog(parent, settings, on_save)
