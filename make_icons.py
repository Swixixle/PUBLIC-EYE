#!/usr/bin/env python3
"""One-shot PWA icons for PUBLIC EYE (run from repo root)."""
from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFont


def make_icon(size: int, path: str) -> None:
    img = Image.new("RGB", (size, size), "#111827")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
            size // 3,
        )
    except OSError:
        font = ImageFont.load_default()
    text = "PE"
    bbox = draw.textbbox((0, 0), text, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((size - w) / 2, (size - h) / 2), text, fill="#F9FAFB", font=font)
    img.save(path)


def main() -> None:
    root = os.path.dirname(os.path.abspath(__file__))
    static = os.path.join(root, "apps", "api", "static")
    os.makedirs(static, exist_ok=True)
    make_icon(192, os.path.join(static, "icon-192.png"))
    make_icon(512, os.path.join(static, "icon-512.png"))
    print("Wrote apps/api/static/icon-192.png and icon-512.png")


if __name__ == "__main__":
    main()
