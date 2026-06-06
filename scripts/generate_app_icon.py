#!/usr/bin/env python3
"""Tạo logo phích cắm (PNG + .icns cho macOS)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
ICONSET = ASSETS / "AppIcon.iconset"

# Nền xanh đậm + phích cắm trắng (gợi cắm USB / nguồn thiết bị)
BG = (26, 86, 168)
BG_EDGE = (18, 62, 128)
PLUG = (248, 250, 252)
SHADOW = (14, 52, 102)


def _rounded_rect(draw: ImageDraw.ImageDraw, box: tuple, radius: int, fill) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill)


def draw_plug_icon(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    m = size // 16
    _rounded_rect(draw, (m, m, size - m, size - m), radius=size // 5, fill=BG)
    _rounded_rect(
        draw,
        (m + size // 32, m + size // 32, size - m - size // 64, size - m - size // 64),
        radius=size // 6,
        fill=BG_EDGE,
    )

    cx, cy = size // 2, size // 2
    body_w = size * 0.36
    body_h = size * 0.30
    prong_w = size * 0.09
    prong_h = size * 0.22
    gap = size * 0.11

    # Thân phích (phía trên)
    body_box = (
        cx - body_w / 2,
        cy - body_h * 0.15,
        cx + body_w / 2,
        cy + body_h * 0.85,
    )
    _rounded_rect(draw, body_box, radius=int(size * 0.06), fill=PLUG)

    # Hai chân phích
    for side in (-1, 1):
        px = cx + side * (gap / 2 + prong_w / 2)
        prong_box = (
            px - prong_w / 2,
            cy + body_h * 0.55,
            px + prong_w / 2,
            cy + body_h * 0.55 + prong_h,
        )
        _rounded_rect(draw, prong_box, radius=int(prong_w / 3), fill=PLUG)

    # Cáp (gợi USB) — hình chữ nhật trên thân
    cable_w = size * 0.14
    cable_h = size * 0.12
    cable_box = (
        cx - cable_w / 2,
        cy - body_h * 0.55,
        cx + cable_w / 2,
        cy - body_h * 0.15,
    )
    _rounded_rect(draw, cable_box, radius=int(size * 0.03), fill=SHADOW)
    _rounded_rect(
        draw,
        (
            cx - cable_w / 2 + size * 0.02,
            cy - body_h * 0.52,
            cx + cable_w / 2 - size * 0.02,
            cy - body_h * 0.18,
        ),
        radius=int(size * 0.02),
        fill=PLUG,
    )

    return img


def _save_rgb_png(image: Image.Image, path: Path) -> None:
    flat = Image.new("RGB", image.size, BG)
    flat.paste(image, mask=image.split()[3])
    flat.save(path, format="PNG")


def write_pngs() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    sizes = {
        "icon_1024.png": 1024,
        "logo_48.png": 48,
        "logo_64.png": 64,
        "logo_128.png": 128,
    }
    master = draw_plug_icon(1024)
    master.save(ASSETS / "icon_1024.png")
    for name, px in sizes.items():
        if name == "icon_1024.png":
            continue
        draw_plug_icon(px).save(ASSETS / name)

    # iconset cho macOS
    if ICONSET.exists():
        import shutil

        shutil.rmtree(ICONSET)
    ICONSET.mkdir(parents=True)
    iconset_map = {
        "icon_16x16.png": 16,
        "icon_16x16@2x.png": 32,
        "icon_32x32.png": 32,
        "icon_32x32@2x.png": 64,
        "icon_128x128.png": 128,
        "icon_128x128@2x.png": 256,
        "icon_256x256.png": 256,
        "icon_256x256@2x.png": 512,
        "icon_512x512.png": 512,
        "icon_512x512@2x.png": 1024,
    }
    for filename, px in iconset_map.items():
        _save_rgb_png(draw_plug_icon(px), ICONSET / filename)

    icns_path = ASSETS / "AppIcon.icns"
    if sys.platform == "darwin":
        subprocess.run(
            ["iconutil", "-c", "icns", str(ICONSET), "-o", str(icns_path)],
            check=True,
        )
        print(f"Wrote {icns_path}")
    else:
        print("Skip .icns (iconutil chỉ có trên macOS)")
    print(f"Assets in {ASSETS}")


if __name__ == "__main__":
    write_pngs()
