#!/usr/bin/env python3
"""Build AppIcon.icns from the same 18-unit chevron mark as the tray glyph."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
OUT = HERE / "AppIcon.icns"

SIZES = {
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


def paint(size: int) -> Image.Image:
    im = Image.new("RGBA", (size, size), (26, 29, 34, 255))
    draw = ImageDraw.Draw(im)
    pad = size * (0.10 if size <= 32 else 0.16)
    scale = (size - 2 * pad) / 18.0
    width = max(2, round((1.7 if size <= 32 else 1.5) * scale))

    def chevron(x: float) -> None:
        draw.line(
            [
                (pad + x * scale, pad + 4 * scale),
                (pad + (x + 4) * scale, pad + 9 * scale),
                (pad + x * scale, pad + 14 * scale),
            ],
            fill=(245, 247, 250, 255),
            width=width,
            joint="curve",
        )

    chevron(1.6)
    chevron(7.0)
    chevron(12.4)
    return im


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="gsd-appicon-"))
    try:
        iconset = work / "AppIcon.iconset"
        iconset.mkdir()
        for name, size in SIZES.items():
            paint(size).save(iconset / name)
        subprocess.run(["iconutil", "-c", "icns", "-o", str(OUT), str(iconset)], check=True)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print(OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
