from __future__ import annotations

import logging
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Optional

import customtkinter as ctk
from PIL import Image

from src.app_branding import ABOUT_CREDITS, APP_NAME, APP_VERSION, app_icon_path
if sys.platform == "darwin":
    from src.macos_menu import apply_macos_menu_branding, register_about_handler
else:

    def register_about_handler(root, app_name, *, about_credits, app_version):  # type: ignore[no-untyped-def]
        def _noop() -> None:
            pass

        return _noop

    def apply_macos_menu_branding(root, app_name, *, quit_command=None) -> None:  # type: ignore[no-untyped-def]
        return None

from src.clipboard_image import clipboard_image
from src.database import DeviceDatabase
from src.excel_export import export_records
from src.models import DeviceRecord
from src.line_import import LINE_IMPORT_HINT, parse_bulk_lines
from src.app_settings import AppSettings
from src.print_labels import open_print_labels
from src.settings_dialog import open_settings_dialog
from src.ocr_parser import (
    ocr_available,
    ocr_engine_name,
    ocr_missing_hint,
    parse_image,
    parse_text_to_record,
)
from src.trial import (
    get_trial_status,
    show_trial_expired_dialog,
    trial_status_color,
    trial_status_message,
)
from src.usb_reader import UsbDeviceMonitor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CHECK_ON = "☑"
CHECK_OFF = "☐"

COLUMNS = (
    "check",
    "time",
    "source",
    "imei1",
    "imei2",
    "serial",
    "model",
    "ios_version",
    "color",
    "storage",
    "condition",
    "battery_health",
    "cycle_count",
)
COLUMN_LABELS = {
    "check": CHECK_OFF,
    "time": "Thời gian",
    "source": "Nguồn",
    "imei1": "IMEI 1",
    "imei2": "IMEI 2",
    "serial": "Serial",
    "model": "Model",
    "ios_version": "iOS",
    "color": "Màu",
    "storage": "Bộ nhớ",
    "condition": "Hình thức",
    "battery_health": "% Pin",
    "cycle_count": "Lần sạc",
}
COLUMN_ATTR: dict[str, str] = {
    col: (
        "captured_at"
        if col == "time"
        else "storage_capacity"
        if col == "storage"
        else col
    )
    for col in COLUMNS
}
COLUMN_WEIGHTS = {
    "check": 0.22,
    "time": 1.0,
    "source": 0.55,
    "imei1": 1.3,
    "imei2": 1.3,
    "serial": 1.0,
    "model": 1.2,
    "ios_version": 0.65,
    "color": 0.9,
    "storage": 0.75,
    "condition": 0.85,
    "battery_health": 1.1,
    "cycle_count": 0.65,
}

DETAIL_PANEL_WIDTH = 340
STATUS_BAR_HEIGHT = 44


def _open_file(path: Path) -> None:
    if sys.platform == "darwin":
        subprocess.run(["open", str(path)], check=False)
    elif sys.platform == "win32":
        import os

        os.startfile(path)  # type: ignore[attr-defined]
    else:
        subprocess.run(["xdg-open", str(path)], check=False)


class ImeiToolApp:
    def __init__(self, root: ctk.CTk) -> None:
        self.root = root
        self.root.title(APP_NAME)
        self.root.minsize(1024, 640)
        self._window_icon_ref: Optional[tk.PhotoImage] = None
        self._image_dialog_preview: Optional[ctk.CTkImage] = None

        self.db = DeviceDatabase()
        self.records: list[DeviceRecord] = []
        self._dedupe_keys: set[str] = set()
        self._ocr_image: Optional[Image.Image] = None
        self._preview_max = (960, 240)
        self._usb_stop = threading.Event()
        self._usb_thread: Optional[threading.Thread] = None
        self._resize_job: Optional[str] = None
        self._selected_row: Optional[int] = None
        self._edit_entry: Optional[tk.Entry] = None
        self._edit_row_index: Optional[int] = None
        self._edit_col_key: Optional[str] = None
        self._checked_rows: set[int] = set()
        self.settings = AppSettings.load()

        self.monitor = UsbDeviceMonitor(
            on_status=self._thread_safe_status,
            on_record=self._thread_safe_record,
            on_unplug=self._thread_safe_unplug,
        )

        self._apply_window_icon()
        self._about_handler = register_about_handler(
            self.root,
            APP_NAME,
            about_credits=ABOUT_CREDITS,
            app_version=APP_VERSION,
        )
        self._build_ui()
        self._load_from_database()
        apply_macos_menu_branding(self.root, APP_NAME, quit_command=self._on_close)
        self._start_usb_monitor()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(300, self._about_handler)

    def _apply_window_icon(self) -> None:
        icon = app_icon_path()
        if icon is None:
            return
        try:
            if icon.suffix.lower() == ".icns" and sys.platform == "darwin":
                self.root.iconbitmap(str(icon))
            else:
                self._window_icon_ref = tk.PhotoImage(file=str(icon))
                self.root.iconphoto(True, self._window_icon_ref)
        except Exception as exc:
            logger.debug("Window icon skipped: %s", exc)

    def _build_ui(self) -> None:
        self._build_menu()

        self.root.grid_rowconfigure(0, weight=1)
        self.root.grid_rowconfigure(1, weight=0, minsize=STATUS_BAR_HEIGHT)
        self.root.grid_columnconfigure(0, weight=1)

        body = ctk.CTkFrame(self.root, fg_color="transparent")
        body.grid(row=0, column=0, sticky="nsew", padx=12, pady=(8, 6))
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(0, weight=1)

        self._build_table(body)

        footer = ctk.CTkFrame(self.root, corner_radius=0, height=STATUS_BAR_HEIGHT)
        footer.grid(row=1, column=0, sticky="ew")
        footer.grid_propagate(False)

        self.status_var = tk.StringVar(value="Sẵn sàng")
        status_row = ctk.CTkFrame(footer, fg_color="transparent")
        status_row.pack(fill=tk.BOTH, expand=True, padx=16, pady=10)

        ctk.CTkLabel(
            status_row,
            textvariable=self.status_var,
            anchor=tk.W,
            font=ctk.CTkFont(size=13),
        ).pack(side=tk.LEFT, fill=tk.X, expand=True)

        ctk.CTkLabel(
            status_row,
            text=trial_status_message(),
            anchor=tk.E,
            text_color=trial_status_color(),
            font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(side=tk.RIGHT, padx=(12, 16))

        if ocr_available():
            name = ocr_engine_name()
            ocr_hint = f"OCR: {name}" if name else "OCR: sẵn sàng"
        elif __import__("src.bundle_paths", fromlist=["is_frozen"]).is_frozen():
            ocr_hint = "OCR: không khả dụng trong bản build"
        else:
            ocr_hint = "OCR: cần macOS 10.15+"
        ctk.CTkLabel(
            status_row,
            text=ocr_hint,
            anchor=tk.E,
            text_color=("#666666", "#AAAAAA"),
            font=ctk.CTkFont(size=12),
        ).pack(side=tk.RIGHT)

    def _build_menu(self) -> None:
        menubar = tk.Menu(self.root)

        if sys.platform == "darwin" and self._about_handler is not None:
            apple_menu = tk.Menu(menubar, name="apple")
            menubar.add_cascade(menu=apple_menu)
            apple_menu.add_command(
                label=f"About {APP_NAME}",
                command=self._about_handler,
            )

        file_menu = tk.Menu(menubar, tearoff=0)
        if self._about_handler is not None:
            file_menu.add_command(label=f"Về {APP_NAME}…", command=self._about_handler)
            file_menu.add_separator()
        file_menu.add_command(label="Xuất Excel…", command=self._export_excel, accelerator="⌘E")
        file_menu.add_command(label="In đã tick…", command=self._print_checked, accelerator="⌘P")
        file_menu.add_separator()
        file_menu.add_command(label="Thoát", command=self._on_close, accelerator="⌘Q")
        menubar.add_cascade(label="Tệp", menu=file_menu)

        import_menu = tk.Menu(menubar, tearoff=0)
        import_menu.add_command(
            label="Thêm theo dòng…",
            command=self._open_add_lines_dialog,
            accelerator="⌘L",
        )
        import_menu.add_command(
            label="Đọc từ ảnh…",
            command=self._open_image_dialog,
            accelerator="⌘I",
        )
        import_menu.add_command(
            label="Phân tích văn bản…",
            command=self._open_text_dialog,
            accelerator="⌘T",
        )
        menubar.add_cascade(label="Nhập liệu", menu=import_menu)

        table_menu = tk.Menu(menubar, tearoff=0)
        table_menu.add_command(label="Xóa dòng đã tick", command=self._delete_checked)
        table_menu.add_command(label="Xóa tất cả", command=self._clear_all)
        menubar.add_cascade(label="Bảng", menu=table_menu)

        settings_menu = tk.Menu(menubar, tearoff=0)
        settings_menu.add_command(label="Cài đặt…", command=self._open_settings)
        menubar.add_cascade(label="Cài đặt", menu=settings_menu)

        self.root.config(menu=menubar)
        if sys.platform == "darwin":
            self.root.createcommand("::tk::mac::Quit", self._on_close)
        self.root.bind("<Command-e>", lambda _e: self._export_excel())
        self.root.bind("<Command-p>", lambda _e: self._print_checked())
        self.root.bind("<Command-l>", lambda _e: self._open_add_lines_dialog())
        self.root.bind("<Command-i>", lambda _e: self._open_image_dialog())
        self.root.bind("<Command-t>", lambda _e: self._open_text_dialog())

    def _style_treeview(self, parent: ctk.CTkFrame) -> ttk.Style:
        style = ttk.Style(parent)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        bg = "#2B2B2B"
        fg = "#EAEAEA"
        head_bg = "#1C1C1C"
        select = "#3B8ED0"

        style.configure(
            "IMEI.Treeview",
            background=bg,
            foreground=fg,
            fieldbackground=bg,
            borderwidth=0,
            rowheight=30,
            font=("SF Pro Text", 12),
        )
        style.configure(
            "IMEI.Treeview.Heading",
            background=head_bg,
            foreground=fg,
            relief=tk.FLAT,
            font=("SF Pro Text", 12, "bold"),
        )
        style.map(
            "IMEI.Treeview",
            background=[("selected", select)],
            foreground=[("selected", "white")],
        )
        return style

    def _build_table(self, parent: ctk.CTkFrame) -> None:
        card = ctk.CTkFrame(parent, corner_radius=12)
        card.pack(fill=tk.BOTH, expand=True)

        split = ctk.CTkFrame(card, fg_color="transparent")
        split.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        split.grid_columnconfigure(0, weight=1)
        split.grid_columnconfigure(1, weight=0, minsize=DETAIL_PANEL_WIDTH)
        split.grid_rowconfigure(0, weight=1)

        table_side = ctk.CTkFrame(split, fg_color="transparent")
        table_side.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        table_side.grid_rowconfigure(0, weight=1)
        table_side.grid_columnconfigure(0, weight=1)

        tree_wrap = ctk.CTkFrame(table_side, corner_radius=8, fg_color=("#EBEBEB", "#2B2B2B"))
        tree_wrap.grid(row=0, column=0, sticky="nsew")

        self._style_treeview(tree_wrap)

        tree_inner = tk.Frame(tree_wrap, bg="#2B2B2B")
        tree_inner.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

        self.tree = ttk.Treeview(
            tree_inner,
            columns=COLUMNS,
            show="headings",
            selectmode="browse",
            style="IMEI.Treeview",
        )
        for col in COLUMNS:
            if col == "check":
                self.tree.heading(col, text=CHECK_OFF, command=self._toggle_all_checks)
                self.tree.column(col, width=44, minwidth=44, stretch=False, anchor=tk.CENTER)
            else:
                self.tree.heading(col, text=COLUMN_LABELS[col])
                self.tree.column(col, width=80, minwidth=50, stretch=True, anchor=tk.W)

        vsb = ctk.CTkScrollbar(tree_inner, orientation="vertical", command=self.tree.yview)
        hsb = ctk.CTkScrollbar(tree_inner, orientation="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        tree_inner.grid_rowconfigure(0, weight=1)
        tree_inner.grid_columnconfigure(0, weight=1)

        self.tree.bind("<Configure>", self._on_tree_resize)
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self.tree.bind("<ButtonRelease-1>", self._on_tree_cell_click)

        self._apply_table_columns()
        self._build_detail_panel(split)

    def _build_detail_panel(self, parent: ctk.CTkFrame) -> None:
        panel = ctk.CTkFrame(parent, corner_radius=8, width=DETAIL_PANEL_WIDTH)
        panel.grid(row=0, column=1, sticky="nsew")
        panel.grid_propagate(False)

        ctk.CTkLabel(
            panel,
            text="Chi tiết dòng chọn",
            font=ctk.CTkFont(size=15, weight="bold"),
            anchor=tk.W,
        ).pack(anchor=tk.W, padx=12, pady=(12, 6))

        self.detail_text = ctk.CTkTextbox(
            panel,
            font=ctk.CTkFont(family="Menlo", size=12),
            wrap=tk.WORD,
            activate_scrollbars=True,
        )
        self.detail_text.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))
        self.detail_text.configure(state=tk.DISABLED)
        self._show_record_detail(None)

    def _format_record_detail(self, record: DeviceRecord) -> str:
        lines = [
            ("Thời gian", record.captured_at),
            ("Nguồn", record.source),
            ("IMEI 1", record.imei1),
            ("IMEI 2", record.imei2),
            ("Serial", record.serial),
            ("Model", record.model),
            ("iOS", record.ios_version),
            ("Màu", record.color),
            ("Bộ nhớ", record.storage_capacity),
            ("Hình thức", record.condition),
            ("% Pin", record.battery_health),
            ("Lần sạc", record.cycle_count),
            ("UDID (USB)", record.device_udid),
            ("Ghi chú", record.note),
        ]
        parts: list[str] = []
        for label, value in lines:
            text = str(value).strip() if value is not None else ""
            parts.append(f"{label}:\n{text or '—'}")
        return "\n\n".join(parts)

    def _show_record_detail(self, record: Optional[DeviceRecord]) -> None:
        self.detail_text.configure(state=tk.NORMAL)
        self.detail_text.delete("1.0", tk.END)
        if record is None:
            self.detail_text.insert("1.0", "Chọn một dòng trong bảng để xem đầy đủ thông tin.")
        else:
            self.detail_text.insert("1.0", self._format_record_detail(record))
        self.detail_text.configure(state=tk.DISABLED)

    def _record_at_tree_index(self, index: int) -> Optional[DeviceRecord]:
        if 0 <= index < len(self.records):
            return self.records[index]
        return None

    def _on_tree_select(self, _event: Optional[tk.Event] = None) -> None:
        self._commit_cell_edit()
        sel = self.tree.selection()
        if not sel:
            self._selected_row = None
            self._show_record_detail(None)
            return
        self._selected_row = self.tree.index(sel[0])
        self._show_record_detail(self._record_at_tree_index(self._selected_row))

    def _display_columns(self) -> tuple[str, ...]:
        cols = self.tree["displaycolumns"]
        if not cols or cols == "#all":
            return COLUMNS
        if isinstance(cols, str):
            return (cols,)
        return tuple(cols)

    def _apply_table_columns(self) -> None:
        visible = ("check",) + tuple(self.settings.visible_table_columns())
        self.tree["displaycolumns"] = visible
        self._resize_columns()

    def _open_settings(self) -> None:
        open_settings_dialog(self.root, self.settings, self._on_settings_saved)

    def _on_settings_saved(self, settings: AppSettings) -> None:
        self.settings = settings
        self._apply_table_columns()
        self.status_var.set("Đã lưu cài đặt")

    def _tree_cell_at(self, event: tk.Event) -> tuple[Optional[str], Optional[str], Optional[int]]:
        region = self.tree.identify_region(event.x, event.y)
        if region not in ("cell", "tree"):
            return None, None, None
        row_id = self.tree.identify_row(event.y)
        col_id = self.tree.identify_column(event.x)
        if not row_id or not col_id:
            return None, None, None
        try:
            display_index = int(col_id.lstrip("#")) - 1
        except ValueError:
            return None, None, None
        displaycols = self._display_columns()
        if display_index < 0 or display_index >= len(displaycols):
            return None, None, None
        col_key = displaycols[display_index]
        col_index = COLUMNS.index(col_key)
        return row_id, col_key, col_index

    def _modifier_copy(self, event: tk.Event) -> bool:
        if event.state & 0x4:
            return True
        return sys.platform == "darwin" and bool(event.state & 0x8)

    def _copy_tree_cell(self, row_id: str, col_index: int) -> None:
        values = self.tree.item(row_id, "values")
        if col_index < 0 or col_index >= len(values):
            return
        text = str(values[col_index]).strip()
        if not text:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.root.update_idletasks()
        col_name = COLUMN_LABELS.get(COLUMNS[col_index], "")
        preview = text if len(text) <= 48 else f"{text[:45]}…"
        self.status_var.set(f"Đã copy ({col_name}): {preview}")

    def _on_tree_cell_click(self, event: tk.Event) -> None:
        row_id, col_key, col_index = self._tree_cell_at(event)
        if not row_id or col_key is None or col_index is None:
            return
        if col_key == "check":
            self._toggle_row_check(self.tree.index(row_id))
            return
        if self._modifier_copy(event):
            self._copy_tree_cell(row_id, col_index)
            return
        self._begin_cell_edit(row_id, col_key)

    def _toggle_row_check(self, row_index: int) -> None:
        if row_index in self._checked_rows:
            self._checked_rows.discard(row_index)
        else:
            self._checked_rows.add(row_index)
        self._refresh_row_checks(row_index)
        record = self._record_at_tree_index(row_index)
        if record is not None and record.id is not None:
            self._db_persist_checked(record.id, row_index in self._checked_rows)
        n = len(self._checked_rows)
        self.status_var.set(f"Đã chọn {n} dòng" if n else "Đã bỏ chọn")

    def _toggle_all_checks(self) -> None:
        self._commit_cell_edit()
        if len(self.records) == 0:
            return
        if len(self._checked_rows) >= len(self.records):
            self._checked_rows.clear()
            heading = CHECK_OFF
        else:
            self._checked_rows = set(range(len(self.records)))
            heading = CHECK_ON
        self.tree.heading("check", text=heading)
        self._refresh_all_row_checks()
        self._db_persist_all_checked(heading == CHECK_ON)
        n = len(self._checked_rows)
        self.status_var.set(f"Đã chọn tất cả ({n})" if n else "Đã bỏ chọn tất cả")

    def _refresh_row_checks(self, row_index: int) -> None:
        children = list(self.tree.get_children())
        if 0 <= row_index < len(children) and row_index < len(self.records):
            self.tree.item(
                children[row_index],
                values=self._record_values(self.records[row_index], row_index),
            )

    def _refresh_all_row_checks(self) -> None:
        for i in range(len(self.records)):
            self._refresh_row_checks(i)

    def _checked_records(self) -> list[DeviceRecord]:
        return [self.records[i] for i in sorted(self._checked_rows) if 0 <= i < len(self.records)]

    def _begin_cell_edit(self, row_id: str, col_key: str) -> None:
        if col_key == "check":
            return
        if self._edit_entry is not None:
            if self._edit_row_index == self.tree.index(row_id) and self._edit_col_key == col_key:
                self._edit_entry.focus_set()
                return
            self._commit_cell_edit()

        row_index = self.tree.index(row_id)
        record = self._record_at_tree_index(row_index)
        if record is None:
            return

        bbox = self.tree.bbox(row_id, col_key)
        if not bbox:
            return

        attr = COLUMN_ATTR[col_key]
        current = str(getattr(record, attr, "") or "")

        x, y, width, height = bbox
        self._edit_row_index = row_index
        self._edit_col_key = col_key

        self._edit_entry = tk.Entry(
            self.tree,
            font=("SF Pro Text", 12) if sys.platform == "darwin" else ("Segoe UI", 11),
            borderwidth=1,
            relief=tk.SOLID,
        )
        self._edit_entry.insert(0, current)
        self._edit_entry.select_range(0, tk.END)
        self._edit_entry.place(x=x, y=y, width=max(width, 40), height=height)
        self._edit_entry.focus_set()
        self._edit_entry.bind("<Return>", lambda _e: self._commit_cell_edit())
        self._edit_entry.bind("<Escape>", lambda _e: self._cancel_cell_edit())
        self._edit_entry.bind("<FocusOut>", lambda _e: self.root.after(1, self._commit_cell_edit))

        label = COLUMN_LABELS.get(col_key, col_key)
        self.status_var.set(f"Đang sửa ({label}) — Enter lưu, Esc hủy, ⌘/Ctrl+click copy")

    def _cancel_cell_edit(self) -> None:
        if self._edit_entry is not None:
            self._edit_entry.destroy()
            self._edit_entry = None
        self._edit_row_index = None
        self._edit_col_key = None

    def _commit_cell_edit(self) -> None:
        if self._edit_entry is None or self._edit_row_index is None or self._edit_col_key is None:
            self._cancel_cell_edit()
            return

        new_value = self._edit_entry.get().strip()
        row_index = self._edit_row_index
        col_key = self._edit_col_key
        self._cancel_cell_edit()

        record = self._record_at_tree_index(row_index)
        if record is None:
            return

        attr = COLUMN_ATTR[col_key]
        old_value = str(getattr(record, attr, "") or "")
        if new_value == old_value:
            return

        setattr(record, attr, new_value)
        self._update_tree_row(row_index, record)
        if self._selected_row == row_index:
            self._show_record_detail(record)
        self._db_save_record(record)
        label = COLUMN_LABELS.get(col_key, col_key)
        self.status_var.set(f"Đã cập nhật {label}")

    def _on_tree_resize(self, _event: Optional[tk.Event] = None) -> None:
        if self._resize_job:
            self.root.after_cancel(self._resize_job)
        self._resize_job = self.root.after(80, self._resize_columns)

    def _resize_columns(self) -> None:
        self._resize_job = None
        total_w = max(self.tree.winfo_width() - 24, 400)
        check_w = 44
        rest_cols = [c for c in self._display_columns() if c != "check"]
        if not rest_cols:
            return
        weight_sum = sum(COLUMN_WEIGHTS.get(c, 1.0) for c in rest_cols)
        rest_w = max(total_w - check_w, 400)
        for col in rest_cols:
            w = int(rest_w * COLUMN_WEIGHTS.get(col, 1.0) / weight_sum)
            self.tree.column(col, width=max(w, 50))

    def _analyze_button(self, parent, text: str, command) -> ctk.CTkButton:
        return ctk.CTkButton(
            parent,
            text=text,
            command=command,
            fg_color="#000000",
            text_color="#FFFFFF",
            hover_color="#333333",
            border_width=0,
            corner_radius=8,
            height=36,
            font=ctk.CTkFont(size=13, weight="bold"),
        )

    def _secondary_button(self, parent, text: str, command) -> ctk.CTkButton:
        return ctk.CTkButton(
            parent,
            text=text,
            command=command,
            fg_color=("#E8E8E8", "#3A3A3A"),
            text_color=("#1A1A1A", "#EEEEEE"),
            hover_color=("#D0D0D0", "#4A4A4A"),
            height=36,
            corner_radius=8,
        )

    def _thread_safe_status(self, message: str) -> None:
        self.root.after(0, lambda: self.status_var.set(message))

    def _thread_safe_record(self, record: DeviceRecord) -> None:
        self.root.after(0, lambda: self._add_record(record))

    def _thread_safe_unplug(self, udid: str) -> None:
        self.root.after(0, lambda: self.status_var.set("Đã rút thiết bị — dữ liệu giữ trong bảng. Cắm lại để cập nhật."))

    def _record_values(self, record: DeviceRecord, row_index: Optional[int] = None) -> tuple:
        if row_index is None:
            row_index = self.records.index(record) if record in self.records else -1
        mark = CHECK_ON if row_index in self._checked_rows else CHECK_OFF
        return (
            mark,
            record.captured_at,
            record.source,
            record.imei1,
            record.imei2,
            record.serial,
            record.model,
            record.ios_version,
            record.color,
            record.storage_capacity,
            record.condition,
            record.battery_health,
            record.cycle_count,
        )

    def _refresh_table(self) -> None:
        self._cancel_cell_edit()
        self._checked_rows.clear()
        self.tree.heading("check", text=CHECK_OFF)
        for item in self.tree.get_children():
            self.tree.delete(item)
        for i, record in enumerate(self.records):
            self.tree.insert("", tk.END, values=self._record_values(record, i))
        self._selected_row = None
        self._show_record_detail(None)

    def _db_save_record(self, record: DeviceRecord, *, is_checked: Optional[bool] = None) -> None:
        try:
            if record.id is None:
                self.db.insert(
                    record,
                    sort_order=len(self.records) - 1,
                    is_checked=bool(is_checked),
                )
            else:
                self.db.update(record, is_checked=is_checked)
        except Exception:
            logger.exception("Lưu SQLite thất bại")

    def _db_persist_checked(self, record_id: int, is_checked: bool) -> None:
        try:
            self.db.update_checked(record_id, is_checked)
        except Exception:
            logger.exception("Lưu trạng thái tick SQLite thất bại")

    def _db_persist_all_checked(self, is_checked: bool) -> None:
        try:
            self.db.update_all_checked(is_checked)
        except Exception:
            logger.exception("Lưu tick tất cả SQLite thất bại")

    def _load_from_database(self) -> None:
        try:
            rows = self.db.load_all()
        except Exception:
            logger.exception("Đọc SQLite thất bại")
            messagebox.showwarning(
                "Dữ liệu cục bộ",
                "Không đọc được dữ liệu đã lưu. Bảng bắt đầu trống.",
                parent=self.root,
            )
            return

        if not rows:
            return

        for record, checked in rows:
            if not record.has_data():
                continue
            self._register_record(record)
            idx = len(self.records)
            self.records.append(record)
            if checked:
                self._checked_rows.add(idx)

        for i, record in enumerate(self.records):
            self.tree.insert("", tk.END, values=self._record_values(record, i))

        if self._checked_rows and len(self._checked_rows) >= len(self.records):
            self.tree.heading("check", text=CHECK_ON)

        self.status_var.set(f"Đã tải {len(self.records)} dòng từ bộ nhớ cục bộ")

    def _unregister_record(self, record: DeviceRecord) -> None:
        self._dedupe_keys.discard(record.dedupe_key)
        if record.serial:
            key = record.serial.upper()
            self._dedupe_keys.discard(f"serial:{key}")
            self.monitor._completed_serials.discard(key)
        if record.imei1:
            self._dedupe_keys.discard(f"imei:{record.imei1}")
        if record.device_udid:
            self.monitor._completed_udids.discard(record.device_udid)
            self.monitor._udid_serial.pop(record.device_udid, None)

    def _start_usb_monitor(self) -> None:
        def loop() -> None:
            while not self._usb_stop.is_set():
                try:
                    self.monitor.poll_once()
                except Exception:
                    logger.exception("USB poll error")
                self._usb_stop.wait(1.5)

        self._usb_thread = threading.Thread(target=loop, name="usb-monitor", daemon=True)
        self._usb_thread.start()

    def _is_duplicate(self, record: DeviceRecord) -> bool:
        if record.dedupe_key in self._dedupe_keys:
            return True
        if record.serial and f"serial:{record.serial.upper()}" in self._dedupe_keys:
            return True
        return False

    def _register_record(self, record: DeviceRecord) -> None:
        self._dedupe_keys.add(record.dedupe_key)
        if record.serial:
            key = record.serial.upper()
            self._dedupe_keys.add(f"serial:{key}")
            self.monitor._completed_serials.add(key)
            if record.device_udid:
                self.monitor._udid_serial[record.device_udid] = key
        if record.imei1:
            self._dedupe_keys.add(f"imei:{record.imei1}")
        if record.device_udid:
            self.monitor._completed_udids.add(record.device_udid)

    def _find_usb_row_index(self, udid: str) -> Optional[int]:
        if not udid:
            return None
        for i, row in enumerate(self.records):
            if row.device_udid == udid:
                return i
        return None

    def _update_tree_row(self, index: int, record: DeviceRecord) -> None:
        children = list(self.tree.get_children())
        if 0 <= index < len(children):
            self.tree.item(children[index], values=self._record_values(record, index))

    def _add_record(self, record: DeviceRecord, *, force: bool = False) -> bool:
        if not record.has_data():
            messagebox.showwarning("Không có dữ liệu", "Không tìm thấy IMEI/Serial/Model.")
            return False

        # USB cắm lại: cập nhật dòng cũ (cùng UDID), không xóa khi rút cáp
        if record.source == "USB" and record.device_udid:
            existing = self._find_usb_row_index(record.device_udid)
            if existing is not None:
                old = self.records[existing]
                self._dedupe_keys.discard(old.dedupe_key)
                if old.serial:
                    self._dedupe_keys.discard(f"serial:{old.serial.upper()}")
                if old.imei1:
                    self._dedupe_keys.discard(f"imei:{old.imei1}")
                record.id = old.id
                record.condition = old.condition
                self.records[existing] = record
                self._register_record(record)
                self._db_save_record(record)
                self._update_tree_row(existing, record)
                children = list(self.tree.get_children())
                if 0 <= existing < len(children):
                    self.tree.selection_set(children[existing])
                self._selected_row = existing
                self._show_record_detail(record)
                label = record.model or record.serial or record.imei1
                self.status_var.set(f"Đã cập nhật: {label}")
                return True

        if not force and self._is_duplicate(record):
            self.status_var.set(f"Bỏ qua trùng: {record.serial or record.imei1}")
            return False

        self._register_record(record)
        self.records.append(record)
        new_index = len(self.records) - 1
        self._db_save_record(record)
        row_id = self.tree.insert("", tk.END, values=self._record_values(record, new_index))
        self.tree.selection_set(row_id)
        self.tree.see(row_id)
        self._selected_row = len(self.records) - 1
        self._show_record_detail(record)
        label = record.model or record.serial or record.imei1
        self.status_var.set(f"Đã thêm: {label}")
        return True

    def _open_image_dialog(self) -> None:
        existing = getattr(self, "_image_win", None)
        if existing is not None and existing.winfo_exists():
            existing.focus()
            return

        win = ctk.CTkToplevel(self.root)
        win.title("Đọc từ ảnh (OCR)")
        win.geometry("560x420")
        win.minsize(480, 360)
        win.transient(self.root)
        win.grab_set()
        self._image_win = win
        self._ocr_image = None

        body = ctk.CTkFrame(win, fg_color="transparent")
        body.pack(fill=tk.BOTH, expand=True, padx=16, pady=16)

        ctk.CTkLabel(
            body,
            text="Chọn ảnh hoặc dán (⌘V) màn hình Cài đặt → Giới thiệu, rồi bấm «Thêm vào bảng».",
            font=ctk.CTkFont(size=12),
            anchor=tk.W,
            justify=tk.LEFT,
            text_color=("#444444", "#BBBBBB"),
            wraplength=500,
        ).pack(anchor=tk.W, pady=(0, 8))

        preview_label = ctk.CTkLabel(
            body,
            text="(Chưa có ảnh)",
            corner_radius=8,
            fg_color=("#E5E5E5", "#333333"),
            height=200,
        )

        def _close() -> None:
            win.grab_release()
            win.destroy()
            self._image_win = None
            self._ocr_image = None

        def _update_preview() -> None:
            if self._ocr_image is None:
                preview_label.configure(image=None, text="(Chưa có ảnh)")
                return
            display = self._ocr_image.copy()
            display.thumbnail(self._preview_max, Image.Resampling.LANCZOS)
            size = (display.width, display.height)
            self._image_dialog_preview = ctk.CTkImage(
                light_image=display, dark_image=display, size=size
            )
            preview_label.configure(image=self._image_dialog_preview, text="")

        def _load_image(image: Image.Image) -> None:
            self._ocr_image = image.convert("RGB").copy()
            _update_preview()

        def _pick() -> None:
            paths = filedialog.askopenfilenames(
                parent=win,
                title="Chọn ảnh (⌘ để chọn nhiều)",
                filetypes=[
                    ("Ảnh", "*.png *.jpg *.jpeg *.webp *.bmp"),
                    ("Tất cả", "*.*"),
                ],
            )
            if not paths:
                return
            added = self._process_image_paths(list(paths), parent=win)
            if added > 0:
                _close()

        def _paste() -> None:
            try:
                img = clipboard_image()
            except Exception as exc:
                messagebox.showerror("Dán ảnh", str(exc), parent=win)
                return
            if img is None:
                return
            _load_image(img)

        def _submit() -> None:
            if self._ocr_image is None:
                messagebox.showinfo("Ảnh", "Chọn hoặc dán ảnh trước.", parent=win)
                return
            if not ocr_available():
                messagebox.showwarning("Thiếu OCR", ocr_missing_hint(), parent=win)
                return
            self.status_var.set("Đang đọc ảnh…")
            win.update_idletasks()
            try:
                ok, reason = self._ocr_and_add_record(self._ocr_image.copy())
            except Exception as exc:
                messagebox.showerror("OCR lỗi", str(exc), parent=win)
                return
            if ok:
                self.status_var.set(f"Đã thêm từ ảnh: {reason}")
                _close()
                return
            if reason == "duplicate":
                messagebox.showinfo("Trùng", "Dữ liệu đã có trong bảng.", parent=win)
                _close()
                return
            messagebox.showwarning(
                "Không nhận dạng được",
                "Gợi ý: file PNG/JPG gốc, crop sát vùng Cài đặt → Giới thiệu.",
                parent=win,
            )

        def _on_paste_shortcut(_event: tk.Event) -> str:
            _paste()
            return "break"

        for seq in ("<Control-v>", "<Command-v>"):
            win.bind(seq, _on_paste_shortcut)
            body.bind(seq, _on_paste_shortcut)
            preview_label.bind(seq, _on_paste_shortcut)

        pick_row = ctk.CTkFrame(body, fg_color="transparent")
        pick_row.pack(fill=tk.X, pady=(0, 8))
        self._secondary_button(pick_row, "Chọn ảnh…", _pick).pack(side=tk.LEFT, padx=(0, 8))
        ctk.CTkLabel(
            pick_row,
            text="(nhiều file → OCR hết và đóng)",
            font=ctk.CTkFont(size=11),
            text_color=("#777777", "#999999"),
        ).pack(side=tk.LEFT, padx=(0, 8))
        self._secondary_button(pick_row, "Dán ảnh (⌘V)", _paste).pack(side=tk.LEFT)
        preview_label.pack(fill=tk.BOTH, expand=True, pady=(0, 12))

        action_row = ctk.CTkFrame(body, fg_color="transparent")
        action_row.pack(fill=tk.X)
        ctk.CTkButton(action_row, text="Hủy", width=90, command=_close).pack(side=tk.RIGHT)
        self._analyze_button(action_row, "Thêm vào bảng", _submit).pack(side=tk.RIGHT, padx=(0, 8))

        win.protocol("WM_DELETE_WINDOW", _close)

    def _open_text_dialog(self) -> None:
        existing = getattr(self, "_text_win", None)
        if existing is not None and existing.winfo_exists():
            existing.focus()
            return

        win = ctk.CTkToplevel(self.root)
        win.title("Phân tích văn bản")
        win.geometry("560x400")
        win.minsize(440, 320)
        win.transient(self.root)
        win.grab_set()
        self._text_win = win

        body = ctk.CTkFrame(win, fg_color="transparent")
        body.pack(fill=tk.BOTH, expand=True, padx=16, pady=16)

        ctk.CTkLabel(
            body,
            text="Dán văn bản từ Cài đặt → Cài đặt chung → Giới thiệu (IMEI, Serial, Model…).",
            font=ctk.CTkFont(size=12),
            anchor=tk.W,
            justify=tk.LEFT,
            text_color=("#444444", "#BBBBBB"),
            wraplength=500,
        ).pack(anchor=tk.W, pady=(0, 8))

        textbox = ctk.CTkTextbox(body, font=ctk.CTkFont(family="Menlo", size=12))
        textbox.pack(fill=tk.BOTH, expand=True, pady=(0, 12))
        textbox.focus_set()

        def _close() -> None:
            win.grab_release()
            win.destroy()
            self._text_win = None

        def _submit() -> None:
            text = textbox.get("1.0", "end").strip()
            if not text:
                messagebox.showinfo(
                    "Văn bản",
                    "Dán nội dung từ Cài đặt > Cài đặt chung > Giới thiệu.",
                    parent=win,
                )
                return
            record = parse_text_to_record(text, source="Dán")
            if not record.has_data():
                messagebox.showwarning(
                    "Không nhận dạng được",
                    record.note or "Không tìm thấy IMEI/Serial/Model trong văn bản.",
                    parent=win,
                )
                return
            if self._add_record(record):
                label = record.model or record.serial or record.imei1
                self.status_var.set(f"Đã thêm từ văn bản: {label}")
                _close()
            else:
                messagebox.showinfo("Trùng", "Dữ liệu đã có trong bảng.", parent=win)
                _close()

        action_row = ctk.CTkFrame(body, fg_color="transparent")
        action_row.pack(fill=tk.X)
        ctk.CTkButton(action_row, text="Hủy", width=90, command=_close).pack(side=tk.RIGHT)
        self._analyze_button(action_row, "Thêm vào bảng", _submit).pack(side=tk.RIGHT, padx=(0, 8))

        win.protocol("WM_DELETE_WINDOW", _close)

    def _process_image_paths(self, paths: list[str], *, parent: tk.Misc | None = None) -> int:
        if not paths:
            return 0
        if not ocr_available():
            messagebox.showwarning("Thiếu OCR", ocr_missing_hint(), parent=parent)
            return 0

        total = len(paths)
        added = 0
        no_data = 0
        duplicate = 0
        load_errors: list[str] = []
        ocr_errors: list[str] = []

        for i, path in enumerate(paths, start=1):
            name = Path(path).name
            self.status_var.set(f"Đang OCR ảnh {i}/{total}: {name}…")
            self.root.update_idletasks()
            try:
                image = Image.open(path).convert("RGB")
            except Exception as exc:
                load_errors.append(f"{name}: {exc}")
                continue

            try:
                ok, reason = self._ocr_and_add_record(image)
            except Exception as exc:
                ocr_errors.append(f"{name}: {exc}")
                continue

            if ok:
                added += 1
            elif reason == "duplicate":
                duplicate += 1
            else:
                no_data += 1

        parts = [f"Đã thêm {added}/{total} ảnh"]
        if duplicate:
            parts.append(f"{duplicate} trùng")
        if no_data:
            parts.append(f"{no_data} không đọc được")
        if load_errors:
            parts.append(f"{len(load_errors)} lỗi mở file")
        self.status_var.set(" · ".join(parts))

        if total == 1 and added == 0 and not load_errors and not ocr_errors:
            messagebox.showwarning(
                "Không nhận dạng được",
                "Không đọc được IMEI/Serial/Model từ ảnh.\n\n"
                "Gợi ý: file PNG/JPG gốc, crop sát vùng Cài đặt → Giới thiệu.",
                parent=parent,
            )

        issues: list[str] = []
        if load_errors:
            issues.append("Lỗi mở file:\n" + "\n".join(load_errors[:8]))
        if ocr_errors:
            issues.append("Lỗi OCR:\n" + "\n".join(ocr_errors[:8]))
        if added == 0 and (no_data or duplicate) and not load_errors and not ocr_errors and total > 1:
            issues.append("Không ảnh nào thêm được (không đọc được hoặc trùng dữ liệu).")
        if issues and (added < total or load_errors or ocr_errors):
            extra = ""
            if len(load_errors) + len(ocr_errors) > 8:
                extra = "\n\n(…)"
            messagebox.showwarning("Kết quả chọn ảnh", "\n\n".join(issues) + extra, parent=parent)

        return added

    def _ocr_and_add_record(self, image: Image.Image) -> tuple[bool, str]:
        """OCR một ảnh và thêm bảng. Trả (thành công, lý do nếu thất bại)."""
        record = parse_image(image, source="Ảnh")
        if not record.has_data():
            return False, "no_data"
        if self._add_record(record):
            return True, record.model or record.serial or record.imei1
        return False, "duplicate"

    def _open_add_lines_dialog(self) -> None:
        existing = getattr(self, "_add_lines_win", None)
        if existing is not None and existing.winfo_exists():
            existing.focus()
            return

        win = ctk.CTkToplevel(self.root)
        win.title("Thêm theo từng dòng")
        win.geometry("580x460")
        win.minsize(480, 360)
        win.transient(self.root)
        win.grab_set()
        self._add_lines_win = win

        body = ctk.CTkFrame(win, fg_color="transparent")
        body.pack(fill=tk.BOTH, expand=True, padx=16, pady=16)

        ctk.CTkLabel(
            body,
            text=LINE_IMPORT_HINT,
            font=ctk.CTkFont(size=12),
            anchor=tk.W,
            justify=tk.LEFT,
            text_color=("#444444", "#BBBBBB"),
            wraplength=520,
        ).pack(anchor=tk.W, pady=(0, 10))

        textbox = ctk.CTkTextbox(body, font=ctk.CTkFont(family="Menlo", size=12))
        textbox.pack(fill=tk.BOTH, expand=True, pady=(0, 12))
        textbox.focus_set()

        btn_row = ctk.CTkFrame(body, fg_color="transparent")
        btn_row.pack(fill=tk.X)

        def _close() -> None:
            win.grab_release()
            win.destroy()
            self._add_lines_win = None

        def _submit() -> None:
            text = textbox.get("1.0", "end").strip()
            if not text:
                messagebox.showinfo(
                    "Thêm dòng",
                    "Nhập mỗi dòng theo dạng:\n  IMEI1  IMEI2  Serial\n(các trường cách nhau bằng dấu cách)",
                    parent=win,
                )
                return
            added = self._commit_bulk_lines(text, parent=win)
            if added > 0:
                _close()

        ctk.CTkButton(btn_row, text="Hủy", width=90, command=_close).pack(side=tk.RIGHT)
        self._analyze_button(btn_row, "Thêm vào bảng", _submit).pack(side=tk.RIGHT, padx=(0, 8))

        win.protocol("WM_DELETE_WINDOW", _close)

    def _commit_bulk_lines(self, text: str, *, parent: tk.Misc | None = None) -> int:
        """Parse và thêm các dòng; trả số dòng đã thêm thành công."""
        parsed = parse_bulk_lines(text)
        if not parsed:
            messagebox.showinfo(
                "Thêm dòng",
                "Không có dòng hợp lệ (bỏ qua dòng trống và dòng bắt đầu bằng #).",
                parent=parent,
            )
            return 0

        added = 0
        duplicate = 0
        failed: list[str] = []

        for item in parsed:
            if item.record is None:
                failed.append(f"Dòng {item.line_no}: {item.error}")
                continue
            if self._add_record(item.record):
                added += 1
            else:
                duplicate += 1

        parts = [f"Đã thêm {added} dòng"]
        if duplicate:
            parts.append(f"{duplicate} trùng")
        if failed:
            parts.append(f"{len(failed)} lỗi")
        self.status_var.set(" · ".join(parts))

        if failed and added == 0:
            messagebox.showwarning(
                "Thêm dòng",
                "Không thêm được dòng nào.\n\n" + "\n".join(failed[:12]),
                parent=parent,
            )
        elif failed:
            messagebox.showwarning(
                "Thêm dòng",
                "\n".join(failed[:12]) + ("\n…" if len(failed) > 12 else ""),
                parent=parent,
            )
        return added

    def _export_excel(self) -> None:
        if not self.records:
            messagebox.showinfo("Xuất Excel", "Chưa có dữ liệu để xuất.")
            return
        default_name = f"apple_devices_{self.records[-1].captured_at.replace(':', '-').replace(' ', '_')}.xlsx"
        path = filedialog.asksaveasfilename(
            title="Lưu file Excel",
            defaultextension=".xlsx",
            initialfile=default_name,
            filetypes=[("Excel", "*.xlsx")],
        )
        if not path:
            return
        try:
            out = export_records(Path(path), self.records)
            self.status_var.set(f"Đã xuất và mở: {out}")
            _open_file(out)
        except Exception as exc:
            messagebox.showerror("Xuất Excel", str(exc))

    def _remove_rows_at_indices(self, indices: list[int]) -> None:
        if not indices:
            return
        children = list(self.tree.get_children())
        for idx in sorted(indices, reverse=True):
            if 0 <= idx < len(children):
                self.tree.delete(children[idx])
            if 0 <= idx < len(self.records):
                removed = self.records.pop(idx)
                if removed.id is not None:
                    try:
                        self.db.delete(removed.id)
                    except Exception:
                        logger.exception("Xóa SQLite thất bại")
                self._unregister_record(removed)
                self.monitor._tracked.pop(removed.device_udid, None)

        remaining_checks: set[int] = set()
        for old_idx in self._checked_rows:
            if old_idx in indices:
                continue
            shift = sum(1 for d in indices if d < old_idx)
            remaining_checks.add(old_idx - shift)
        self._checked_rows = remaining_checks
        if len(self._checked_rows) == 0:
            self.tree.heading("check", text=CHECK_OFF)

        self._selected_row = None
        sel = self.tree.selection()
        if sel:
            self._selected_row = self.tree.index(sel[0])
            self._show_record_detail(self._record_at_tree_index(self._selected_row))
        else:
            self._show_record_detail(None)

    def _delete_checked(self) -> None:
        self._commit_cell_edit()
        indices = sorted(self._checked_rows)
        if not indices:
            messagebox.showinfo("Xóa", "Tick chọn ít nhất một dòng cần xóa.")
            return
        if not messagebox.askyesno("Xác nhận", f"Xóa {len(indices)} dòng đã tick?"):
            return
        self._remove_rows_at_indices(indices)
        self.status_var.set(f"Đã xóa {len(indices)} dòng")

    def _print_checked(self) -> None:
        self._commit_cell_edit()
        records = self._checked_records()
        if not records:
            messagebox.showinfo("In", "Tick chọn ít nhất một dòng cần in.")
            return
        pdf_path = open_print_labels(
            self.root,
            records,
            print_fields=self.settings.enabled_print_fields(),
        )
        if pdf_path is not None:
            self.status_var.set(f"Đã mở PDF ({len(records)} nhãn): {pdf_path}")

    def _clear_all(self) -> None:
        if not self.records:
            return
        if not messagebox.askyesno("Xác nhận", "Xóa toàn bộ danh sách?"):
            return
        try:
            self.db.delete_all()
        except Exception:
            logger.exception("Xóa toàn bộ SQLite thất bại")
        self.records.clear()
        self._dedupe_keys.clear()
        self.monitor._completed_udids.clear()
        self.monitor._completed_serials.clear()
        self.monitor._udid_serial.clear()
        self.monitor._tracked.clear()
        self.monitor._last_udids.clear()
        self._refresh_table()

    def _on_close(self) -> None:
        self._cancel_cell_edit()
        self._usb_stop.set()
        try:
            self.db.close()
        except Exception:
            logger.debug("Đóng SQLite", exc_info=True)
        self.root.destroy()


def _maximize_window(root: ctk.CTk) -> None:
    root.update_idletasks()
    try:
        root.state("zoomed")
        return
    except tk.TclError:
        pass
    w = root.winfo_screenwidth()
    h = root.winfo_screenheight()
    root.geometry(f"{w}x{h}+0+0")


def run_app() -> None:
    ctk.set_appearance_mode("system")
    ctk.set_default_color_theme("blue")
    root = ctk.CTk()
    root.withdraw()
    root.update_idletasks()

    if get_trial_status().expired:
        show_trial_expired_dialog(root)
        root.mainloop()
        root.destroy()
        return

    app = ImeiToolApp(root)
    root.deiconify()
    root.after(50, lambda: _maximize_window(root))
    root.after(150, app._resize_columns)
    root.mainloop()
