"""Định dạng và in nhãn thiết bị (theo cài đặt mục in + mã vạch IMEI1)."""

from __future__ import annotations

import logging
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Literal, Optional

from PIL import Image, ImageDraw, ImageFont
from PySide6.QtWidgets import QMessageBox, QWidget

from src.app_settings import PRINT_FIELD_KEYS, SIMLOCK_PRINT_LABELS, AppSettings
from src.models import DeviceRecord
from src.simlock_sync import SIMLOCK_PENDING_LABEL

logger = logging.getLogger(__name__)

PAGE_WIDTH = 1240
MARGIN = 44
HERO_FONT_MAX = 84
HERO_FONT_MIN = 48
BODY_FONT_MAX = 50
BODY_FONT_MIN = 30
IMEI_FONT_MAX = 44
LINE_SPACING = 1.22
SECTION_GAP = 14
TEXT_BARCODE_GAP = 28
BARCODE_MAX_HEIGHT = 160
BARCODE_WIDTH_RATIO = 0.82

PrintTier = Literal["hero", "body", "imei"]


@dataclass(frozen=True)
class PrintLine:
    text: str
    tier: PrintTier


def format_simlock_for_print(value: str) -> str:
    """Unlocked → Quốc Tế, Locked → Máy Lock."""
    raw = str(value or "").strip()
    if not raw or raw == SIMLOCK_PENDING_LABEL:
        return ""
    return SIMLOCK_PRINT_LABELS.get(raw, raw)


def format_fmi_for_print(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    return f"iCloud {raw}"


def format_active_for_print(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    return f"Active: {raw}"


def format_storage_for_print(value: str) -> str:
    """256 GB → 256GB."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    compact = re.sub(r"\s+", "", raw)
    return compact or raw


def format_carrier_for_print(value: str) -> str:
    """Bỏ «Unlocked» trùng với simlock đã in «Quốc Tế»."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw.lower() in ("unlocked", "unlock"):
        return ""
    return raw


def format_mdm_for_print(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    return f"MDM: {raw}"


def _field_value(record: DeviceRecord, key: str) -> str:
    getters = {
        "imei": lambda r: r.imei1,
        "model": lambda r: r.model,
        "color": lambda r: r.color,
        "storage": lambda r: format_storage_for_print(r.storage_capacity),
        "condition": lambda r: r.condition,
        "battery_health": lambda r: r.battery_health,
        "ios": lambda r: r.ios_version,
        "simlock": lambda r: format_simlock_for_print(r.simlock),
        "fmi": lambda r: format_fmi_for_print(r.fmi),
        "active": lambda r: format_active_for_print(r.active),
        "carrier": lambda r: format_carrier_for_print(r.carrier),
        "mdm": lambda r: format_mdm_for_print(r.mdm),
    }
    getter = getters.get(key)
    if getter is None:
        return ""
    return str(getter(record) or "").strip()


def _join_enabled(
    record: DeviceRecord,
    print_fields: dict[str, bool],
    keys: tuple[str, ...],
    *,
    separator: str = " · ",
) -> str:
    parts: list[str] = []
    for key in keys:
        if not print_fields.get(key, False):
            continue
        value = _field_value(record, key)
        if value:
            parts.append(value)
    return separator.join(parts)


CONDITION_PRINT_LABEL = "Ngoại hình"


def format_record_lines(
    record: DeviceRecord,
    print_fields: Optional[dict[str, bool]] = None,
) -> list[PrintLine]:
    """
    Bố cục nhãn:
      1. Model Màu Dung lượng Simlock (một dòng, chữ lớn)
      2. iCloud On/Off || Active: …
      3. Nhà mạng · % Pin · iOS (nếu bật; không in «Unlocked» trùng)
      4. Ngoại hình
      5. IMEI (+ barcode)
    """
    enabled = print_fields or {key: True for key in PRINT_FIELD_KEYS}
    lines: list[PrintLine] = []

    device_line = _join_enabled(
        record,
        enabled,
        ("model", "color", "storage", "simlock"),
        separator=" ",
    )
    if device_line:
        lines.append(PrintLine(device_line, "hero"))

    cloud_active = _join_enabled(
        record,
        enabled,
        ("fmi", "active", "mdm"),
        separator=" || ",
    )
    if cloud_active:
        lines.append(PrintLine(cloud_active, "body"))

    extras = _join_enabled(record, enabled, ("carrier", "battery_health", "ios"))
    if extras:
        lines.append(PrintLine(extras, "body"))

    if enabled.get("condition", False):
        condition = _field_value(record, "condition")
        if condition:
            lines.append(PrintLine(f"{CONDITION_PRINT_LABEL}: {condition}", "body"))

    if enabled.get("imei", False):
        imei = _field_value(record, "imei")
        if imei:
            lines.append(PrintLine(imei, "imei"))

    return lines


def _font_candidates() -> list[Path]:
    import os

    paths: list[Path] = []
    if sys.platform == "win32":
        fonts_dir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        paths.extend(
            fonts_dir / name
            for name in (
                "arial.ttf",
                "Arial.ttf",
                "segoeui.ttf",
                "Segoeui.ttf",
                "calibri.ttf",
                "Calibri.ttf",
            )
        )
    elif sys.platform == "darwin":
        paths.extend(
            Path(p)
            for p in (
                "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
                "/System/Library/Fonts/Supplemental/Arial.ttf",
                "/Library/Fonts/Arial Unicode.ttf",
            )
        )
    else:
        paths.extend(
            Path(p)
            for p in (
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/TTF/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            )
        )
    return [path for path in paths if path.is_file()]


_LABEL_FONT_PATH: Path | None = None


def _label_font_path() -> Path | None:
    global _LABEL_FONT_PATH
    if _LABEL_FONT_PATH is None:
        candidates = _font_candidates()
        _LABEL_FONT_PATH = candidates[0] if candidates else None
    return _LABEL_FONT_PATH


def _label_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    path = _label_font_path()
    if path is not None:
        try:
            return ImageFont.truetype(str(path), size)
        except OSError:
            logger.warning("Could not load label font: %s", path)
    return ImageFont.load_default()


def _content_width() -> int:
    return PAGE_WIDTH - 2 * MARGIN


def _text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont | ImageFont.ImageFont) -> int:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0]


def _fit_font_for_lines(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    *,
    max_size: int,
    min_size: int,
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if not lines:
        return _label_font(min_size)
    width = _content_width()
    for size in range(max_size, min_size - 1, -2):
        font = _label_font(size)
        if max(_text_width(draw, line, font) for line in lines) <= width:
            return font
    return _label_font(min_size)


def _line_height(font: ImageFont.FreeTypeFont | ImageFont.ImageFont) -> int:
    size = int(getattr(font, "size", BODY_FONT_MIN))
    return max(int(size * LINE_SPACING), size + 6)


def _barcode_image(imei1: str, *, target_width: int) -> Optional[Image.Image]:
    code = imei1.strip()
    if not code or target_width < 80:
        return None
    try:
        from barcode import Code128
        from barcode.writer import ImageWriter

        buf = BytesIO()
        Code128(code, writer=ImageWriter()).write(
            buf,
            options={
                "module_height": 16.0,
                "module_width": 0.32,
                "font_size": 0,
                "text_distance": 0,
                "quiet_zone": 2,
                "write_text": False,
            },
        )
        buf.seek(0)
        img = Image.open(buf).convert("RGB")
        ratio = target_width / img.width
        height = int(img.height * ratio)
        if height > BARCODE_MAX_HEIGHT:
            ratio = BARCODE_MAX_HEIGHT / img.height
            target_width = int(img.width * ratio)
            height = BARCODE_MAX_HEIGHT
        return img.resize((target_width, height), Image.Resampling.LANCZOS)
    except Exception as exc:
        logger.debug("Barcode generation failed: %s", exc)
        return None


def _resolve_fonts(
    draw: ImageDraw.ImageDraw,
    lines: list[PrintLine],
) -> dict[PrintTier, ImageFont.FreeTypeFont | ImageFont.ImageFont]:
    hero_texts = [ln.text for ln in lines if ln.tier == "hero"]
    body_texts = [ln.text for ln in lines if ln.tier == "body"]
    imei_texts = [ln.text for ln in lines if ln.tier == "imei"]

    return {
        "hero": _fit_font_for_lines(draw, hero_texts, max_size=HERO_FONT_MAX, min_size=HERO_FONT_MIN),
        "body": _fit_font_for_lines(draw, body_texts, max_size=BODY_FONT_MAX, min_size=BODY_FONT_MIN),
        "imei": _fit_font_for_lines(draw, imei_texts, max_size=IMEI_FONT_MAX, min_size=BODY_FONT_MIN),
    }


def _render_label_page(record: DeviceRecord, print_fields: dict[str, bool]) -> Image.Image:
    print_lines = format_record_lines(record, print_fields)
    if not print_lines:
        print_lines = [PrintLine("—", "body")]

    content_w = _content_width()
    probe = Image.new("RGB", (PAGE_WIDTH, 200), "white")
    probe_draw = ImageDraw.Draw(probe)
    fonts = _resolve_fonts(probe_draw, print_lines)

    block_h = 0
    prev_tier: PrintTier | None = None
    for line in print_lines:
        if prev_tier is not None and line.tier != prev_tier:
            block_h += SECTION_GAP
        block_h += _line_height(fonts[line.tier])
        prev_tier = line.tier

    show_barcode = print_fields.get("barcode", True)
    barcode_width = int(content_w * BARCODE_WIDTH_RATIO)
    barcode = (
        _barcode_image(record.imei1, target_width=barcode_width)
        if show_barcode and record.imei1
        else None
    )
    barcode_h = barcode.height if barcode else 0
    gap = TEXT_BARCODE_GAP if barcode and print_lines else 0
    total_h = block_h + gap + barcode_h
    height = max(MARGIN * 2 + total_h + 24, 320)
    y = max(MARGIN, (height - total_h) // 2)

    page = Image.new("RGB", (PAGE_WIDTH, height), "white")
    draw = ImageDraw.Draw(page)
    prev_tier = None
    for line in print_lines:
        if prev_tier is not None and line.tier != prev_tier:
            y += SECTION_GAP
        font = fonts[line.tier]
        tw = _text_width(draw, line.text, font)
        x = MARGIN + (content_w - tw) // 2
        draw.text((x, y), line.text, fill="black", font=font)
        y += _line_height(font)
        prev_tier = line.tier

    if barcode is not None:
        bx = MARGIN + (content_w - barcode.width) // 2
        page.paste(barcode, (bx, y + gap))

    return page


def build_labels_pdf(
    records: list[DeviceRecord],
    path: Optional[Path] = None,
    *,
    print_fields: Optional[dict[str, bool]] = None,
) -> Path:
    """Tạo PDF — mỗi thiết bị một trang, theo cài đặt mục in."""
    enabled = print_fields or AppSettings().enabled_print_fields()
    pages = [_render_label_page(r, enabled) for r in records]
    if not pages:
        raise ValueError("Không có nhãn để in")

    if path is None:
        import os

        fd, name = tempfile.mkstemp(suffix=".pdf", prefix="taoden-labels-")
        os.close(fd)
        path = Path(name)

    pages[0].save(
        path,
        "PDF",
        resolution=200.0,
        save_all=True,
        append_images=pages[1:] if len(pages) > 1 else [],
    )
    return path


def _labels_pdf_path() -> Path:
    import os
    from datetime import datetime

    from src.database import default_db_path

    out_dir = default_db_path().parent / "print"
    out_dir.mkdir(parents=True, exist_ok=True)

    def _is_writable(path: Path) -> bool:
        if not path.exists():
            return True
        try:
            with path.open("r+b"):
                return True
        except OSError:
            return False

    preferred = out_dir / "labels.pdf"
    if _is_writable(preferred):
        return preferred

    stamped = out_dir / f"labels_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    if _is_writable(stamped):
        return stamped

    fd, name = tempfile.mkstemp(suffix=".pdf", prefix="labels_", dir=str(out_dir))
    os.close(fd)
    return Path(name)


def open_print_labels(
    parent: Optional[QWidget],
    records: list[DeviceRecord],
    *,
    print_fields: Optional[dict[str, bool]] = None,
) -> Optional[Path]:
    """Tạo PDF nhãn và mở bằng ứng dụng mặc định (Preview trên macOS)."""
    if not records:
        return None

    enabled = print_fields or AppSettings().enabled_print_fields()
    if not any(enabled.get(key, False) for key in PRINT_FIELD_KEYS):
        QMessageBox.information(parent, "In", "Chưa chọn mục nào để in. Mở Cài đặt → In.")
        return None

    try:
        pdf_path = build_labels_pdf(records, path=_labels_pdf_path(), print_fields=enabled)
    except PermissionError:
        try:
            pdf_path = build_labels_pdf(records, path=None, print_fields=enabled)
        except Exception as exc:
            logger.exception("PDF labels failed")
            QMessageBox.critical(parent, "In", f"Không tạo được PDF nhãn:\n{exc}")
            return None
    except Exception as exc:
        logger.exception("PDF labels failed")
        QMessageBox.critical(parent, "In", f"Không tạo được PDF nhãn:\n{exc}")
        return None

    try:
        if sys.platform == "darwin":
            subprocess.run(["open", str(pdf_path)], check=False)
        elif sys.platform == "win32":
            import os

            os.startfile(pdf_path)  # type: ignore[attr-defined]
        else:
            subprocess.run(["xdg-open", str(pdf_path)], check=False)
    except Exception as exc:
        QMessageBox.critical(parent, "In", f"Không mở được PDF:\n{exc}\n\nFile:\n{pdf_path}")
        return None

    return pdf_path
