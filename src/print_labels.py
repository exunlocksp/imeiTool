"""Định dạng và in nhãn thiết bị (theo cài đặt mục in + mã vạch IMEI1)."""

from __future__ import annotations

import logging
import subprocess
import sys
import tempfile
import tkinter as tk
from io import BytesIO
from pathlib import Path
from tkinter import messagebox
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

from src.app_settings import PRINT_FIELD_KEYS, AppSettings
from src.models import DeviceRecord

logger = logging.getLogger(__name__)

PAGE_WIDTH = 1240
PAGE_MIN_HEIGHT = 900
MARGIN = 48
FONT_MAX = 76
FONT_MIN = 40
LINE_SPACING = 1.28
TEXT_BARCODE_GAP = 36
BARCODE_MAX_HEIGHT = 200
BARCODE_WIDTH_RATIO = 0.88

_PRINT_VALUE_GETTERS = {
    "imei": lambda r: r.imei1,
    "model": lambda r: r.model,
    "color": lambda r: r.color,
    "storage": lambda r: r.storage_capacity,
    "battery_health": lambda r: r.battery_health,
    "ios": lambda r: r.ios_version,
}


def format_record_lines(record: DeviceRecord, print_fields: Optional[dict[str, bool]] = None) -> list[str]:
    """Mỗi mục in (trừ barcode) một dòng — chỉ giá trị, không gộp."""
    enabled = print_fields or {key: True for key in PRINT_FIELD_KEYS}
    lines: list[str] = []
    for key in PRINT_FIELD_KEYS:
        if key == "barcode":
            continue
        if not enabled.get(key, True):
            continue
        getter = _PRINT_VALUE_GETTERS.get(key)
        if getter is None:
            continue
        value = str(getter(record) or "").strip()
        if value:
            lines.append(value)
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


def _fit_font(draw: ImageDraw.ImageDraw, lines: list[str]) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Chọn cỡ chữ lớn nhất sao cho dòng dài nhất vừa full chiều ngang."""
    if not lines:
        return _label_font(FONT_MIN)
    width = _content_width()
    for size in range(FONT_MAX, FONT_MIN - 1, -1):
        font = _label_font(size)
        if max(_text_width(draw, line, font) for line in lines) <= width:
            return font
    return _label_font(FONT_MIN)


def _barcode_image(imei1: str, *, target_width: int) -> Optional[Image.Image]:
    """Code128 — chỉ vạch, không kèm chữ IMEI bên dưới."""
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
                "module_height": 18.0,
                "module_width": 0.35,
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


def _render_label_page(record: DeviceRecord, print_fields: dict[str, bool]) -> Image.Image:
    lines = format_record_lines(record, print_fields)
    content_w = _content_width()

    probe = Image.new("RGB", (PAGE_WIDTH, 200), "white")
    probe_draw = ImageDraw.Draw(probe)
    font = _fit_font(probe_draw, lines)
    font_size = int(getattr(font, "size", FONT_MIN))
    line_height = max(int(font_size * LINE_SPACING), 36)

    show_barcode = print_fields.get("barcode", True)
    barcode_width = int(content_w * BARCODE_WIDTH_RATIO)
    barcode = (
        _barcode_image(record.imei1, target_width=barcode_width)
        if show_barcode and record.imei1
        else None
    )

    text_h = len(lines) * line_height
    barcode_h = barcode.height if barcode else 0
    gap = TEXT_BARCODE_GAP if barcode and lines else 0
    block_h = text_h + gap + barcode_h
    height = max(PAGE_MIN_HEIGHT, MARGIN * 2 + block_h)
    y = max(MARGIN, (height - block_h) // 2)

    page = Image.new("RGB", (PAGE_WIDTH, height), "white")
    draw = ImageDraw.Draw(page)
    for line in lines:
        tw = _text_width(draw, line, font)
        x = MARGIN + (content_w - tw) // 2
        draw.text((x, y), line, fill="black", font=font)
        y += line_height

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
    parent: tk.Misc,
    records: list[DeviceRecord],
    *,
    print_fields: Optional[dict[str, bool]] = None,
) -> Optional[Path]:
    """Tạo PDF nhãn và mở bằng ứng dụng mặc định (Preview trên macOS)."""
    if not records:
        return None

    enabled = print_fields or AppSettings().enabled_print_fields()
    if not any(enabled.get(key, False) for key in PRINT_FIELD_KEYS):
        messagebox.showinfo("In", "Chưa chọn mục nào để in. Mở Cài đặt → In.", parent=parent)
        return None

    try:
        pdf_path = build_labels_pdf(records, path=_labels_pdf_path(), print_fields=enabled)
    except PermissionError:
        try:
            pdf_path = build_labels_pdf(records, path=None, print_fields=enabled)
        except Exception as exc:
            logger.exception("PDF labels failed")
            messagebox.showerror("In", f"Không tạo được PDF nhãn:\n{exc}", parent=parent)
            return None
    except Exception as exc:
        logger.exception("PDF labels failed")
        messagebox.showerror("In", f"Không tạo được PDF nhãn:\n{exc}", parent=parent)
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
        messagebox.showerror(
            "In",
            f"Không mở được PDF:\n{exc}\n\nFile:\n{pdf_path}",
            parent=parent,
        )
        return None

    return pdf_path
