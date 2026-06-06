from __future__ import annotations

from pathlib import Path
from typing import Iterable

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from src.models import DeviceRecord

HEADERS = [
    "Thời gian",
    "Nguồn",
    "IMEI 1",
    "IMEI 2",
    "Serial",
    "Model",
    "iOS",
    "Màu",
    "Bộ nhớ",
    "Hình thức",
    "% Pin",
    "Lần sạc",
]


def export_records(path: Path, records: Iterable[DeviceRecord]) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "Thiết bị Apple"

    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="1F4E79")
    for col, title in enumerate(HEADERS, start=1):
        cell = ws.cell(row=1, column=col, value=title)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")

    row_idx = 2
    for rec in records:
        ws.cell(row=row_idx, column=1, value=rec.captured_at)
        ws.cell(row=row_idx, column=2, value=rec.source)
        ws.cell(row=row_idx, column=3, value=rec.imei1)
        ws.cell(row=row_idx, column=4, value=rec.imei2)
        ws.cell(row=row_idx, column=5, value=rec.serial)
        ws.cell(row=row_idx, column=6, value=rec.model)
        ws.cell(row=row_idx, column=7, value=rec.ios_version)
        ws.cell(row=row_idx, column=8, value=rec.color)
        ws.cell(row=row_idx, column=9, value=rec.storage_capacity)
        ws.cell(row=row_idx, column=10, value=rec.condition)
        ws.cell(row=row_idx, column=11, value=rec.battery_health)
        ws.cell(row=row_idx, column=12, value=rec.cycle_count)
        row_idx += 1

    widths = [20, 10, 18, 18, 16, 24, 10, 16, 12, 14, 10, 10]
    for i, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = width

    ws.freeze_panes = "A2"
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path
