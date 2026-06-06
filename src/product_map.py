"""Map Apple ProductType identifiers to marketing names.

Synced with pymobiledevice3 ``irecv_devices`` (iPhone through iPhone 17 series).
Internal IDs: ``iPhone17,*`` = iPhone 16 line; ``iPhone18,*`` = iPhone 17 line.
"""

from __future__ import annotations

PRODUCT_TYPE_NAMES: dict[str, str] = {
    # iPhone 2G – 4s
    "iPhone1,1": "iPhone 2G",
    "iPhone1,2": "iPhone 3G",
    "iPhone2,1": "iPhone 3Gs",
    "iPhone3,1": "iPhone 4",
    "iPhone3,2": "iPhone 4",
    "iPhone3,3": "iPhone 4",
    "iPhone4,1": "iPhone 4s",
    # iPhone 5 – 5s
    "iPhone5,1": "iPhone 5",
    "iPhone5,2": "iPhone 5",
    "iPhone5,3": "iPhone 5c",
    "iPhone5,4": "iPhone 5c",
    "iPhone6,1": "iPhone 5s",
    "iPhone6,2": "iPhone 5s",
    # iPhone 6 – SE (1st)
    "iPhone7,1": "iPhone 6 Plus",
    "iPhone7,2": "iPhone 6",
    "iPhone8,1": "iPhone 6s",
    "iPhone8,2": "iPhone 6s Plus",
    "iPhone8,4": "iPhone SE (1st gen)",
    # iPhone 7 – X
    "iPhone9,1": "iPhone 7",
    "iPhone9,2": "iPhone 7 Plus",
    "iPhone9,3": "iPhone 7",
    "iPhone9,4": "iPhone 7 Plus",
    "iPhone10,1": "iPhone 8",
    "iPhone10,2": "iPhone 8 Plus",
    "iPhone10,3": "iPhone X",
    "iPhone10,4": "iPhone 8",
    "iPhone10,5": "iPhone 8 Plus",
    "iPhone10,6": "iPhone X",
    # iPhone XS – 11
    "iPhone11,2": "iPhone XS",
    "iPhone11,4": "iPhone XS Max",
    "iPhone11,6": "iPhone XS Max",
    "iPhone11,8": "iPhone XR",
    "iPhone12,1": "iPhone 11",
    "iPhone12,3": "iPhone 11 Pro",
    "iPhone12,5": "iPhone 11 Pro Max",
    "iPhone12,8": "iPhone SE (2nd gen)",
    # iPhone 12 – 13
    "iPhone13,1": "iPhone 12 mini",
    "iPhone13,2": "iPhone 12",
    "iPhone13,3": "iPhone 12 Pro",
    "iPhone13,4": "iPhone 12 Pro Max",
    "iPhone14,2": "iPhone 13 Pro",
    "iPhone14,3": "iPhone 13 Pro Max",
    "iPhone14,4": "iPhone 13 mini",
    "iPhone14,5": "iPhone 13",
    "iPhone14,6": "iPhone SE (3rd gen)",
    "iPhone14,7": "iPhone 14",
    "iPhone14,8": "iPhone 14 Plus",
    # iPhone 14 Pro – 15
    "iPhone15,2": "iPhone 14 Pro",
    "iPhone15,3": "iPhone 14 Pro Max",
    "iPhone15,4": "iPhone 15",
    "iPhone15,5": "iPhone 15 Plus",
    "iPhone16,1": "iPhone 15 Pro",
    "iPhone16,2": "iPhone 15 Pro Max",
    # iPhone 16 (ProductType iPhone17,x)
    "iPhone17,1": "iPhone 16 Pro",
    "iPhone17,2": "iPhone 16 Pro Max",
    "iPhone17,3": "iPhone 16",
    "iPhone17,4": "iPhone 16 Plus",
    "iPhone17,5": "iPhone 16e",
    # iPhone 17 series (ProductType iPhone18,x)
    "iPhone18,1": "iPhone 17 Pro",
    "iPhone18,2": "iPhone 17 Pro Max",
    "iPhone18,3": "iPhone 17",
    "iPhone18,4": "iPhone Air",
    "iPhone18,5": "iPhone 17e",
    # iPad (common retail models)
    "iPad6,11": "iPad (5th gen)",
    "iPad7,5": "iPad (6th gen)",
    "iPad11,6": "iPad (8th gen)",
    "iPad13,18": "iPad (10th gen)",
    "iPad13,1": "iPad Air (4th gen)",
    "iPad14,1": "iPad mini (6th gen)",
}


def resolve_model_name(product_type: str | None, model_number: str | None = None) -> str:
    if product_type:
        name = PRODUCT_TYPE_NAMES.get(product_type)
        if name:
            return name
        if product_type.startswith(("iPhone", "iPad", "iPod")):
            return product_type.replace(",", " ")
    if model_number:
        return model_number
    return product_type or ""
