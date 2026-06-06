"""OCR via macOS Vision / Live Text (Apple), không cần Tesseract."""

from __future__ import annotations

import platform
import re
import sys
from typing import Optional

from PIL import Image

_OCRMAC = None
_OCRMAC_ERROR: Optional[str] = None

if sys.platform == "darwin":
    try:
        from ocrmac import ocrmac as _ocrmac_mod

        _OCRMAC = _ocrmac_mod
    except Exception as exc:
        _OCRMAC_ERROR = str(exc)


def macos_ocr_available() -> bool:
    return _OCRMAC is not None


def macos_ocr_error() -> Optional[str]:
    return _OCRMAC_ERROR


def _macos_major() -> int:
    try:
        return int(platform.mac_ver()[0].split(".")[0])
    except (ValueError, IndexError):
        return 0


def _frameworks_to_try() -> list[str]:
    if _macos_major() >= 14:
        return ["vision", "livetext"]
    return ["vision"]


_SUPPORTED_LANGS: Optional[frozenset[str]] = None


def _vision_supported_languages() -> frozenset[str]:
    """Ngôn ngữ Vision thực sự hỗ trợ trên máy này."""
    global _SUPPORTED_LANGS
    if _SUPPORTED_LANGS is not None:
        return _SUPPORTED_LANGS
    try:
        import Vision

        req = Vision.VNRecognizeTextRequest.alloc().init()
        available = req.supportedRecognitionLanguagesAndReturnError_(None)[0]
        _SUPPORTED_LANGS = frozenset(str(x) for x in available)
    except Exception:
        _SUPPORTED_LANGS = frozenset({"en-US"})
    return _SUPPORTED_LANGS


def _language_preferences() -> list[Optional[list[str]]]:
    """
    Thử theo thứ tự: en-US (+ vi nếu có), chỉ en-US, mặc định hệ thống.
    Không dùng vi-VN — macOS thường chỉ có vi-VT.
    """
    available = _vision_supported_languages()
    prefs: list[str] = []
    for code in ("en-US", "vi-VT", "vi-VN"):
        if code in available:
            prefs.append(code)
    options: list[Optional[list[str]]] = []
    if prefs:
        options.append(prefs)
    if "en-US" in available and prefs != ["en-US"]:
        options.append(["en-US"])
    options.append(None)
    return options


def _annotations_to_lines(annotations: list) -> str:
    """Ghép từng từ Vision thành dòng theo vị trí Y (bbox chuẩn hóa 0–1)."""
    rows: list[tuple[float, float, str]] = []
    for item in annotations:
        if not item:
            continue
        text = str(item[0]).strip() if item[0] else ""
        if not text:
            continue
        bbox = item[2] if len(item) > 2 else None
        if bbox and len(bbox) >= 4:
            y = float(bbox[1]) + float(bbox[3]) / 2
            x = float(bbox[0])
        else:
            y, x = len(rows) * 0.01, 0.0
        rows.append((y, x, text))

    if not rows:
        return ""

    rows.sort(key=lambda r: (r[0], r[1]))
    line_threshold = 0.012
    lines: list[str] = []
    bucket_y: Optional[float] = None
    bucket: list[tuple[float, str]] = []

    def flush() -> None:
        nonlocal bucket, bucket_y
        if bucket:
            bucket.sort(key=lambda w: w[0])
            lines.append(" ".join(w for _, w in bucket))
        bucket = []
        bucket_y = None

    for y, x, text in rows:
        if bucket_y is None or abs(y - bucket_y) <= line_threshold:
            bucket.append((x, text))
            bucket_y = y if bucket_y is None else (bucket_y + y) / 2
        else:
            flush()
            bucket.append((x, text))
            bucket_y = y
    flush()
    return "\n".join(lines)


def ocr_image_vision(image: Image.Image) -> str:
    """Nhận dạng chữ bằng Vision / Live Text của macOS."""
    if _OCRMAC is None:
        raise RuntimeError(_OCRMAC_ERROR or "ocrmac chỉ chạy trên macOS")

    last_error: Optional[Exception] = None

    for framework in _frameworks_to_try():
        lang_tries = _language_preferences() if framework == "vision" else [None]
        for languages in lang_tries:
            try:
                kwargs: dict = {"recognition_level": "accurate"}
                if languages is not None:
                    kwargs["language_preference"] = languages
                if framework == "vision":
                    ocr = _OCRMAC.OCR(image, framework=framework, **kwargs)
                else:
                    ocr = _OCRMAC.OCR(image, framework=framework)

                annotations = ocr.recognize()
                if not annotations:
                    continue

                text = _annotations_to_lines(annotations)
                if text.strip():
                    return text

                parts = [str(item[0]).strip() for item in annotations if item and item[0]]
                if parts:
                    return "\n".join(parts)
            except Exception as exc:
                last_error = exc
                continue

    if last_error:
        raise RuntimeError(f"macOS OCR thất bại: {last_error}") from last_error
    return ""
