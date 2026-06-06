"""Lấy ảnh từ clipboard — ưu tiên bản đầy đủ trên macOS (Retina)."""

from __future__ import annotations

import io
import sys
from pathlib import Path
from typing import Optional, Union

from PIL import Image

ClipboardData = Union[Image.Image, list[str], None]


def _image_grab() -> type:
    from PIL import ImageGrab

    return ImageGrab


def clipboard_has_image() -> bool:
    """Kiểm tra nhanh — tránh decode ảnh khi clipboard chỉ có chữ."""
    if sys.platform == "darwin":
        try:
            from AppKit import NSPasteboard

            pb = NSPasteboard.generalPasteboard()
            types = {str(t) for t in (pb.types() or [])}
            image_markers = (
                "public.tiff",
                "public.png",
                "public.jpeg",
                "Apple PNG pasteboard type",
                "NeXT TIFF v4.0 pasteboard type",
            )
            return any(any(m in t for m in image_markers) for t in types)
        except Exception:
            pass
    try:
        data = _image_grab().grabclipboard()
    except Exception:
        return False
    if data is None:
        return False
    if isinstance(data, Image.Image):
        return True
    if isinstance(data, list) and data:
        return Path(data[0]).is_file()
    return False


def clipboard_image() -> Optional[Image.Image]:
    if not clipboard_has_image():
        return None
    if sys.platform == "darwin":
        img = _darwin_pasteboard_image()
        if img is not None:
            return img
    return _image_from_grab(_image_grab().grabclipboard())


def _image_from_grab(data: ClipboardData) -> Optional[Image.Image]:
    if data is None:
        return None
    if isinstance(data, list):
        if not data:
            return None
        path = Path(data[0])
        if path.is_file():
            return Image.open(path).convert("RGB")
        return None
    if isinstance(data, Image.Image):
        return data.convert("RGB")
    return None


def _rep_pixel_size(rep) -> tuple[int, int]:
    for attr_w, attr_h in (("pixelsWide", "pixelsHigh"),):
        w = getattr(rep, attr_w, None)
        h = getattr(rep, attr_h, None)
        if callable(w):
            w, h = w(), h()
        if w and h:
            return int(w), int(h)
    size = rep.size()
    return int(size.width), int(size.height)


def _pil_from_nsimage(ns_image) -> Optional[Image.Image]:
    """Chuyển NSImage → PIL, ưu tiên representation có nhiều pixel nhất."""
    try:
        from AppKit import NSBitmapImageRep
    except ImportError:
        NSBitmapImageRep = None  # type: ignore

    best_rep = None
    best_pixels = 0
    for rep in ns_image.representations():
        pw, ph = _rep_pixel_size(rep)
        pixels = pw * ph
        if pixels > best_pixels:
            best_pixels = pixels
            best_rep = rep

    if best_rep is not None and NSBitmapImageRep is not None:
        try:
            data = best_rep.representationUsingType_properties_(
                NSBitmapImageRep.NSPNGFileType, None
            )
            if data:
                return Image.open(io.BytesIO(bytes(data))).convert("RGB")
        except Exception:
            pass

    tiff = ns_image.TIFFRepresentation()
    if tiff:
        return Image.open(io.BytesIO(bytes(tiff))).convert("RGB")
    return None


def _darwin_pasteboard_image() -> Optional[Image.Image]:
    try:
        from AppKit import NSImage, NSPasteboard
    except ImportError:
        return None

    pb = NSPasteboard.generalPasteboard()

    ns_image = NSImage.alloc().initWithPasteboard_(pb)
    if ns_image is not None:
        img = _pil_from_nsimage(ns_image)
        if img is not None:
            return img

    for paste_type in (
        "public.tiff",
        "NeXT TIFF v4.0 pasteboard type",
        "public.png",
        "Apple PNG pasteboard type",
        "public.jpeg",
    ):
        data = pb.dataForType_(paste_type)
        if not data:
            continue
        buf = bytes(data)
        try:
            return Image.open(io.BytesIO(buf)).convert("RGB")
        except Exception:
            ns_image = NSImage.alloc().initWithData_(buf)
            if ns_image is None:
                continue
            img = _pil_from_nsimage(ns_image)
            if img is not None:
                return img

    return _image_from_grab(_image_grab().grabclipboard())
