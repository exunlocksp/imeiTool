"""Read and map DeviceEnclosureColor (USB / MobileGestalt) — English color names."""

from __future__ import annotations

import logging
from typing import Any, Optional

from pymobiledevice3.exceptions import DeprecationError
from pymobiledevice3.lockdown_service_provider import LockdownServiceProvider
from pymobiledevice3.services.diagnostics import DiagnosticsService

logger = logging.getLogger(__name__)

COLOR_GESTALT_KEYS = (
    "DeviceEnclosureColor",
    "DeviceColor",
    "DeviceEnclosureRGBColor",
)

# Universal numeric codes (fallback; meaning varies by model)
_UNIVERSAL: dict[str, str] = {
    "1": "Black",
    "2": "White",
    "3": "Gold",
    "4": "Rose Gold",
    "5": "Space Gray",
    "6": "(PRODUCT)RED",
    "7": "Yellow",
    "8": "Coral",
    "9": "Blue",
    "10": "Green",
    "11": "Purple",
    "17": "Purple",
    "18": "Green",
}

# Hex enclosure colors (iPhone X era → iPhone 17 era, Apple compare-page values)
_HEX: dict[str, str] = {
    "#000000": "Black",
    "#1b1b1b": "Black Titanium",
    "#1f2020": "Black",
    "#222930": "Midnight",
    "#232a31": "Midnight",
    "#262529": "Space Gray",
    "#272728": "Space Gray",
    "#272729": "Space Gray",
    "#2e3034": "Black",
    "#2f4452": "Blue Titanium",
    "#302e2e": "Black",
    "#32374a": "Deep Blue",
    "#353839": "Black",
    "#35393b": "Black",
    "#394c38": "Green",
    "#3b3b3c": "Black",
    "#3c3c3d": "Black Titanium",
    "#3c4042": "Black",
    "#403e3d": "Space Black",
    "#52514d": "Graphite",
    "#54524f": "Graphite",
    "#576856": "Alpine Green",
    "#594f63": "Deep Purple",
    "#837f7d": "Natural Titanium",
    "#96aed1": "Mist Blue",
    "#9aadf6": "Ultramarine",
    "#a0b4c7": "Blue",
    "#a7c1d9": "Sierra Blue",
    "#a9b689": "Sage",
    "#b0d4d2": "Teal",
    "#b41325": "(PRODUCT)RED",
    "#bfa48f": "Desert Titanium",
    "#c2bcb2": "Natural Titanium",
    "#c8caca": "Silver",
    "#cad4c5": "Green",
    "#d1cdda": "Purple",
    "#d6c8b0": "Gold",
    "#d7d9d8": "Silver",
    "#d82e2e": "(PRODUCT)RED",
    "#dfceea": "Lavender",
    "#e1e4e3": "White",
    "#e3c8ca": "Pink",
    "#e4c1b9": "Rose Gold",
    "#e4e4e2": "Silver",
    "#e4e7e8": "White",
    "#e4e8ce": "Gold",
    "#e5e0c1": "Yellow",
    "#e6ddeb": "Purple",
    "#ebf2f2": "Silver",
    "#f0f2f2": "Silver",
    "#f0f9ff": "Sky Blue",
    "#f1f2ed": "Silver",
    "#f2adda": "Pink",
    "#f2f1ed": "White Titanium",
    "#f4e8ce": "Gold",
    "#f5f5f5": "White",
    "#f77e2d": "Cosmic Orange",
    "#f9d045": "Yellow",
    "#f9e479": "Yellow",
    "#f9f6ef": "Starlight",
    "#facebd": "Gold",
    "#faf6f2": "Starlight",
    "#fc0324": "(PRODUCT)RED",
    "#fce7e6": "Soft Pink",
    "#ff6e5a": "Coral",
    "#ffcc00": "Yellow",
    "#fffcF5": "Light Gold",
    "#ffffff": "White",
    "#fcfcfc": "Cloud White",
}

_HEX["#fffcf5"] = "Light Gold"

_BY_PRODUCT: dict[tuple[str, str], str] = {}


def _add_product_map(product_types: tuple[str, ...], code_map: dict[str, str]) -> None:
    for product in product_types:
        for code, name in code_map.items():
            _BY_PRODUCT[(product, code)] = name


# --- iPhone XR / X era ---
_add_product_map(("iPhone11,8",), {"1": "Black", "2": "White", "6": "(PRODUCT)RED", "7": "Yellow", "8": "Coral", "9": "Blue"})

# --- iPhone 12 ---
_add_product_map(
    ("iPhone13,1", "iPhone13,2"),
    {"1": "Black", "2": "White", "3": "Green", "4": "Purple", "5": "(PRODUCT)RED"},
)
_add_product_map(
    ("iPhone13,3", "iPhone13,4"),
    {"1": "Graphite", "2": "Silver", "3": "Gold", "4": "Pacific Blue"},
)

# --- iPhone 13 ---
_add_product_map(
    ("iPhone14,4", "iPhone14,5"),
    {"1": "Midnight", "2": "Starlight", "3": "Blue", "4": "Pink", "5": "(PRODUCT)RED"},
)
_add_product_map(
    ("iPhone14,2", "iPhone14,3"),
    {"1": "Graphite", "2": "Silver", "3": "Gold", "4": "Sierra Blue", "5": "Alpine Green"},
)

# --- iPhone 14 ---
_add_product_map(
    ("iPhone14,7", "iPhone14,8"),
    {"1": "Midnight", "2": "Starlight", "3": "Blue", "4": "Purple", "5": "(PRODUCT)RED"},
)
_add_product_map(
    ("iPhone15,2", "iPhone15,3"),
    {"1": "Space Black", "2": "Silver", "3": "Gold", "4": "Deep Purple"},
)

# --- iPhone 15 ---
_add_product_map(
    ("iPhone15,4", "iPhone15,5"),
    {"1": "Black", "2": "Blue", "3": "Green", "4": "Yellow", "5": "Pink"},
)
_add_product_map(
    ("iPhone16,1", "iPhone16,2"),
    {"1": "Black Titanium", "2": "White Titanium", "3": "Natural Titanium", "4": "Blue Titanium"},
)

# --- iPhone 16 ---
_add_product_map(
    ("iPhone17,1", "iPhone17,2"),
    {"1": "Black Titanium", "2": "White Titanium", "3": "Natural Titanium", "4": "Desert Titanium"},
)
_add_product_map(
    ("iPhone17,3", "iPhone17,4"),
    {"1": "Black", "2": "White", "3": "Pink", "4": "Teal", "5": "Ultramarine"},
)
_add_product_map(("iPhone17,5",), {"1": "Black", "2": "White"})

# --- iPhone 17 (ProductType iPhone18,x) ---
_add_product_map(
    ("iPhone18,1", "iPhone18,2"),
    {"1": "Cosmic Orange", "2": "Silver", "3": "Deep Blue"},
)
_add_product_map(
    ("iPhone18,3",),
    {"1": "Black", "2": "White", "3": "Sage", "4": "Mist Blue", "5": "Lavender"},
)
_add_product_map(
    ("iPhone18,4",),
    {"1": "Space Black", "2": "Cloud White", "3": "Light Gold", "4": "Sky Blue"},
)
_add_product_map(
    ("iPhone18,5",),
    {"1": "Black", "2": "White", "3": "Soft Pink"},
)

# Composite codes (DeviceColor-EnclosureColor-variant), common on iCloud device images
_COMPOSITE: dict[tuple[str, str], str] = {
    ("iPhone17,1", "1-2-0"): "Black Titanium",
    ("iPhone17,1", "1-3-0"): "Natural Titanium",
    ("iPhone17,1", "1-4-0"): "Desert Titanium",
    ("iPhone17,1", "2-2-0"): "White Titanium",
    ("iPhone18,1", "1-2-0"): "Cosmic Orange",
    ("iPhone18,1", "2-2-0"): "Silver",
    ("iPhone18,1", "3-2-0"): "Deep Blue",
    ("iPhone18,2", "1-2-0"): "Cosmic Orange",
    ("iPhone18,2", "2-2-0"): "Silver",
    ("iPhone18,2", "3-2-0"): "Deep Blue",
    ("iPhone18,3", "1-1-0"): "Black",
    ("iPhone18,3", "2-2-0"): "White",
    ("iPhone18,3", "3-4-0"): "Mist Blue",
    ("iPhone18,3", "4-3-0"): "Sage",
    ("iPhone18,3", "5-5-0"): "Lavender",
}


def _normalize_code(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8", errors="replace")
        except Exception:
            return ""
    if isinstance(raw, int) and raw > 255:
        return f"#{raw & 0xFFFFFF:06x}"
    text = str(raw).strip()
    if not text:
        return ""
    if text.startswith("#"):
        return text.lower()
    if text.isdigit():
        return text
    return text.replace(" ", "").lower()


def resolve_enclosure_color(product_type: str | None, raw: Any) -> str:
    """Map DeviceEnclosureColor code → English color name."""
    code = _normalize_code(raw)
    if not code:
        return ""

    product = (product_type or "").strip()

    if product:
        if (product, code) in _COMPOSITE:
            return _COMPOSITE[(product, code)]
        if (product, code) in _BY_PRODUCT:
            return _BY_PRODUCT[(product, code)]

    if code in _HEX:
        return _HEX[code]

    if code in _UNIVERSAL:
        return _UNIVERSAL[code]

    if code.isdigit():
        return _UNIVERSAL.get(code, f"Color code {code}")

    return f"Color code {code}"


async def _lockdown_color_value(lockdown: LockdownServiceProvider, key: str) -> Any:
    try:
        return await lockdown.get_value(key=key)
    except Exception:
        return None


async def read_enclosure_color_async(
    lockdown: LockdownServiceProvider,
    product_type: str | None,
    gestalt: Optional[dict] = None,
) -> tuple[str, str]:
    """Read enclosure color over USB. Returns (english_color_name, optional_note)."""
    product = str(product_type or "")
    raw: Any = None
    source = ""

    for key in ("DeviceEnclosureColor", "DeviceColor", "DeviceEnclosureRGBColor"):
        val = await _lockdown_color_value(lockdown, key)
        if val is not None and str(val).strip() not in ("", "0"):
            raw = val
            source = key
            break

    if raw is None and gestalt:
        for key in COLOR_GESTALT_KEYS:
            val = gestalt.get(key)
            if val is not None and str(val).strip() not in ("", "0"):
                raw = val
                source = f"MG:{key}"
                break

    if raw is None:
        try:
            diag = DiagnosticsService(lockdown)
            mg = await diag.mobilegestalt(list(COLOR_GESTALT_KEYS))
            for key in COLOR_GESTALT_KEYS:
                val = mg.get(key)
                if val is not None and str(val).strip() not in ("", "0"):
                    raw = val
                    source = f"MG:{key}"
                    break
        except DeprecationError:
            return "", "Color: MobileGestalt restricted on iOS 17.4+"
        except Exception as exc:
            logger.debug("Enclosure color gestalt failed: %s", exc)
            return "", ""

    name = resolve_enclosure_color(product, raw)
    if not name:
        return "", ""
    if name.startswith("Color code"):
        return name, f"{source}={raw}" if source else ""
    return name, ""
