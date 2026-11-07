#!/usr/bin/env python3
"""Draw the JARVIS mark (same design as ui/theme.draw_logo) into assets/jarvis.ico.

    python build/make_icon.py
"""
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "jarvis.ico"
BG = (13, 17, 23, 255)
ACCENT = (0, 212, 255, 255)
SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]


def draw(size: int) -> Image.Image:
    scale = 4                                    # supersample, then downsize: smooth edges
    s = size * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * 0.22), fill=BG)
    m = s * 0.2
    width = max(scale * 2, int(s * 0.09))
    # Qt angles are counter-clockwise from 3 o'clock; PIL's are clockwise. Qt: start 60°, span 300°
    # → PIL: from -60-300 = -360 (0°) … to -60: the gap sits between 300° and 360° (upper right).
    d.arc([m, m, s - m, s - m], start=0, end=300, fill=ACCENT, width=width)
    r = s * 0.11
    d.ellipse([s / 2 - r, s / 2 - r, s / 2 + r, s / 2 + r], fill=ACCENT)
    return img.resize((size, size), Image.LANCZOS)


def main() -> Path:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    base = draw(256)
    base.save(OUT, format="ICO", sizes=[(n, n) for n in SIZES],
              append_images=[draw(n) for n in SIZES if n != 256])
    draw(256).save(OUT.with_suffix(".png"))
    return OUT


if __name__ == "__main__":
    print(f"Wrote {main()}")
