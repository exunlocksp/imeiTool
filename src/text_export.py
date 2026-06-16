from __future__ import annotations

from pathlib import Path
from typing import Iterable

from src.export_common import record_export_value
from src.models import DeviceRecord


def export_records_text(
    path: Path,
    records: Iterable[DeviceRecord],
    fields: list[str],
) -> Path:
    lines: list[str] = []
    for record in records:
        line = "\t".join(record_export_value(record, key) for key in fields)
        lines.append(line)

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return path
