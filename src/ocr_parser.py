from __future__ import annotations

import re
import sys
from typing import Optional

from PIL import Image, ImageEnhance

from src.models import DeviceRecord

try:
    import pytesseract
except ImportError:
    pytesseract = None  # type: ignore

if sys.platform == "darwin":
    from src import macos_ocr
else:
    macos_ocr = None  # type: ignore

if sys.platform != "darwin":
    from src.bundle_paths import configure_tesseract

    configure_tesseract()

# OCR hay nhầm I / l / 1
_IME_LABEL = r"IME[I1lí|]"
_UI_NOISE = (
    "không tìm thấy",
    "phân tích ocr",
    "chọn ảnh",
    "dán ảnh",
    "đã copy",
    "xóa tất cả",
    "xuất excel",
    "bấm vào ô",
    "rút cáp",
    "hoàn thành",
    "ảnh / dán",
    "ctr+v",
    "⌘v",
    "ảnh quá nhỏ",
    "ocr cần ảnh",
    "độ phân giải cao",
    "file gốc",
    "imei tool",
    "apple imei",
    "taoden imei",
    "rút cấp giữ dòng",
    "bấm vào ô trong bảng",
)


def _luhn_check(digits: str) -> bool:
    if not digits.isdigit() or len(digits) != 15:
        return False
    total = 0
    reverse = digits[::-1]
    for i, ch in enumerate(reverse):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


_OCR_MIN_SHORT_SIDE = 1200


def _prepare_image(image: Image.Image) -> Image.Image:
    """Chỉ phóng to ảnh nhỏ cho OCR — không bao giờ thu nhỏ."""
    img = image.convert("RGB").copy()
    w, h = img.size
    short = min(w, h)
    if short < _OCR_MIN_SHORT_SIDE:
        scale = _OCR_MIN_SHORT_SIDE / short
        img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
    img = ImageEnhance.Contrast(img).enhance(1.15)
    return img


def _normalize_text(text: str) -> str:
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    text = text.replace("|", "I")
    return text


def _filter_device_text(text: str) -> str:
    """Bỏ dòng UI app, giữ vùng thông tin máy."""
    kept: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        low = stripped.lower()
        if any(noise in low for noise in _UI_NOISE):
            continue
        upper = stripped.upper()
        if (
            re.search(rf"{_IME_LABEL}|SERIAL|MODEL|IPHONE|IPAD|\d{{15}}", upper)
            or ("SERIAL" in upper and "NUMBER" in upper)
        ):
            kept.append(stripped)
            continue
        if re.match(r"^[A-Z0-9][A-Z0-9\s\-]{8,}$", upper) and "IPHONE" in upper:
            kept.append(stripped)
    return "\n".join(kept) if kept else text


def _compact(text: str) -> str:
    return re.sub(r"\s+", " ", text.upper()).strip()


def _find_imeis_from_labels(text: str) -> list[str]:
    imeis: list[str] = []
    imei1_m = re.search(
        rf"(?<!2){_IME_LABEL}\s*Number\s*:?\s*(\d{{15}})",
        text,
        re.IGNORECASE,
    )
    imei2_m = re.search(
        rf"{_IME_LABEL}\s*2\s*Number\s*:?\s*(\d{{15}})",
        text,
        re.IGNORECASE,
    )
    if imei1_m:
        imeis.append(imei1_m.group(1))
    if imei2_m:
        d2 = imei2_m.group(1)
        if d2 not in imeis:
            imeis.append(d2)

    if len(imeis) < 2:
        for pattern in (
            rf"{_IME_LABEL}\s*2\s*Number\s*:?\s*(\d[\d\s]{{13,18}}\d)",
            rf"(?<!2){_IME_LABEL}\s*Number\s*:?\s*(\d[\d\s]{{13,18}}\d)",
        ):
            for match in re.finditer(pattern, text, re.IGNORECASE):
                digits = re.sub(r"\D", "", match.group(1))
                if len(digits) == 15 and digits not in imeis:
                    imeis.append(digits)
    return imeis


def _find_imeis_loose(text: str) -> list[str]:
    candidates: list[str] = []
    for match in re.finditer(r"\d[\d\s\-]{13,22}\d", text):
        digits = re.sub(r"\D", "", match.group())
        if len(digits) == 15:
            candidates.append(digits)
    for match in re.finditer(r"\b(\d{15})\b", text):
        candidates.append(match.group(1))

    seen: set[str] = set()
    valid: list[str] = []
    for imei in candidates:
        if imei in seen:
            continue
        seen.add(imei)
        if _luhn_check(imei):
            valid.append(imei)
    return valid


def _find_imeis(text: str) -> list[str]:
    labeled = _find_imeis_from_labels(text)
    if labeled:
        return labeled[:2]
    return _find_imeis_loose(text)[:2]


_SERIAL_SKIP = frozenset({
    "DESCRIPTION",
    "ACTIVATED",
    "NUMBER",
    "POLICY",
    "RESELLER",
    "PURCHASE",
    "CARRIER",
    "LOCKED",
    "STATUS",
    "FLEX",
})


def _find_serial(text: str) -> str:
    patterns = [
        r"Serial\s*Number\s*:?\s*([A-Z0-9]{10,14})",
        r"Serial\s*Number\s*:?\s*Number\s*:?\s*([A-Z0-9]{10,14})",
        r"(?:số\s*serial)\s*:?\s*([A-Z0-9]{10,14})",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            serial = m.group(1).upper()
            if serial not in _SERIAL_SKIP:
                return serial

    # Serial + IMEI2 dính một dòng (Vision hay gộp)
    m = re.search(
        r"Serial\s+"
        + _IME_LABEL
        + r"\s*2\s*Number\s*:?\s*(?:Number\s*:?\s*)?([A-Z][A-Z0-9]{9,11})\s+(\d{15})",
        text,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).upper()

    m = re.search(
        r"Serial.{0,50}?([A-Z][A-Z0-9]{9,11})(?:\s+\d{15}|\s|$)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if m:
        cand = m.group(1).upper()
        if cand not in _SERIAL_SKIP:
            return cand

    upper = text.upper()
    for token in re.findall(r"\b[A-Z0-9]{10,12}\b", upper):
        if token.isdigit() or token in _SERIAL_SKIP:
            continue
        if token.startswith(("IME", "MODEL", "IPHONE", "IPAD", "DEMO", "ACTIV", "PURCH", "US")):
            continue
        if re.match(r"^[A-Z][A-Z0-9]{9,11}$", token):
            return token
    return ""


def _find_model(text: str) -> str:
    m = re.search(
        r"Model\s*Description\s*:?\s*(.+?)(?=\s*"
        + _IME_LABEL
        + r"\s*2?\s*Number|\s*Serial\s*Number|$)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()

    m = re.search(
        r"(IPHONE\s+(?:AIR|\d+)[^\n]{0,120}?)(?=\s*"
        + _IME_LABEL
        + r"|\s*Serial|$)",
        text,
        re.IGNORECASE,
    )
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()

    patterns = [
        r"(iPhone\s*Air(?:\s+[\w\s\-]+)?)",
        r"(iPhone\s*(?:SE|\d+(?:\s*(?:Pro|Plus|mini|Max|e)[\w\s\-]*)*))",
        r"(iPad[^\n]{0,60})",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return re.sub(r"\s+", " ", m.group(1)).strip()
    return ""


def parse_text_to_record(text: str, source: str = "Ảnh", *, raw_text: str | None = None) -> DeviceRecord:
    normalized = _normalize_text(text)
    filtered = _filter_device_text(normalized)
    raw_norm = _normalize_text(raw_text) if raw_text else normalized

    imeis = _find_imeis(filtered) or _find_imeis(raw_norm)
    serial = _find_serial(filtered) or _find_serial(raw_norm)
    model = _find_model(filtered) or _find_model(raw_norm)
    return DeviceRecord(
        imei1=imeis[0] if len(imeis) > 0 else "",
        imei2=imeis[1] if len(imeis) > 1 else "",
        serial=serial,
        model=model,
        source=source,
        note="OCR/thủ công" if source != "USB" else "",
    )


def ocr_engine_name() -> str:
    if sys.platform == "darwin" and macos_ocr and macos_ocr.macos_ocr_available():
        return "macOS Vision"
    if tesseract_available():
        return "Tesseract"
    return ""


def ocr_available() -> bool:
    if sys.platform == "darwin" and macos_ocr and macos_ocr.macos_ocr_available():
        return True
    return tesseract_available()


def tesseract_available() -> bool:
    if pytesseract is None:
        return False
    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def _ocr_tesseract(image: Image.Image, lang: Optional[str] = None) -> str:
    if pytesseract is None:
        raise RuntimeError("pytesseract chưa được cài đặt")

    if lang is None:
        langs: list[str] = []
        try:
            available = pytesseract.get_languages(config="")
            if "vie" in available:
                langs.append("vie")
            if "eng" in available:
                langs.append("eng")
        except Exception:
            langs = ["eng"]
        lang = "+".join(langs) if langs else "eng"

    return pytesseract.image_to_string(image, lang=lang)


def ocr_image(image: Image.Image, lang: Optional[str] = None) -> str:
    prepared = _prepare_image(image)
    if sys.platform == "darwin" and macos_ocr and macos_ocr.macos_ocr_available():
        text = macos_ocr.ocr_image_vision(prepared)
        if text.strip():
            return text

    return _ocr_tesseract(prepared, lang=lang)


def parse_image(image: Image.Image, source: str = "Ảnh") -> DeviceRecord:
    engine = ocr_engine_name() or "OCR"
    try:
        text = ocr_image(image)
    except Exception as exc:
        return DeviceRecord(source=source, note=f"{engine} lỗi: {exc}")

    record = parse_text_to_record(text, source=source, raw_text=text)
    if not record.has_data():
        record.note = (
            f"Không nhận dạng được ({engine}). "
            "Chỉ chụp vùng Cài đặt → Giới thiệu (tránh chụp cả cửa sổ app)."
        )
    elif engine:
        record.note = engine
    return record
