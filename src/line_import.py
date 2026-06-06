"""Nhập nhanh từng dòng: IMEI1 [IMEI2] [Serial] (cách nhau bằng dấu cách)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.models import DeviceRecord

LINE_IMPORT_SOURCE = "Thêm dòng"

LINE_IMPORT_HINT = (
    "Mỗi dòng một máy — ghi IMEI1, IMEI2, Serial cách nhau bằng dấu cách (space):\n"
    "  IMEI1  IMEI2  Serial\n"
    "Ví dụ:\n"
    "  352099001761481 352099001761499 F2LD1234567\n"
    "  352099001761481 F2LD1234567          ← IMEI1 + Serial (không có IMEI2)\n"
    "  352099001761481 352099001761499      ← chỉ hai IMEI\n"
    "  352099001761481                      ← chỉ IMEI1\n"
    "Dòng trống hoặc bắt đầu bằng # sẽ bỏ qua."
)

_IMEI_RE = re.compile(r"^\d{15}$")


@dataclass
class LineParseResult:
    line_no: int
    record: DeviceRecord | None
    error: str = ""


def _looks_like_imei(token: str) -> bool:
    return bool(_IMEI_RE.match(token.strip()))


def parse_line_to_record(line: str, *, source: str = LINE_IMPORT_SOURCE) -> DeviceRecord | None:
    """Parse một dòng → DeviceRecord hoặc None nếu dòng trống / comment."""
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None

    parts = stripped.split()
    if not parts:
        return None

    imei1 = ""
    imei2 = ""
    serial = ""

    if len(parts) >= 3:
        imei1, imei2, serial = parts[0], parts[1], parts[2]
    elif len(parts) == 2:
        imei1, second = parts[0], parts[1]
        if _looks_like_imei(second):
            imei2 = second
        else:
            serial = second
    else:
        imei1 = parts[0]

    record = DeviceRecord(
        imei1=imei1.strip(),
        imei2=imei2.strip(),
        serial=serial.strip(),
        source=source,
    )
    return record if record.has_data() else None


def parse_bulk_lines(text: str, *, source: str = LINE_IMPORT_SOURCE) -> list[LineParseResult]:
    results: list[LineParseResult] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        record = parse_line_to_record(line, source=source)
        if record is None:
            results.append(
                LineParseResult(
                    line_no=line_no,
                    record=None,
                    error="Không đọc được — cần ít nhất IMEI1 hoặc Serial",
                )
            )
        else:
            results.append(LineParseResult(line_no=line_no, record=record))
    return results
