#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


def interp(a, b, t):
    return int(a + (b - a) * t)


def make_avatar(out: Path, size: int = 1024, text: str = "ELI", variant: str = "modern"):
    out.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    # Soft projected shadow/glow, not glitter.
    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    cx = cy = size // 2
    for r in range(size // 2, size // 9, -8):
        t = r / (size / 2)
        alpha = int(42 * (1 - t) ** 1.4)
        gd.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(60, 160, 255, alpha))
    glow = glow.filter(ImageFilter.GaussianBlur(size // 32))
    img.alpha_composite(glow)

    # Main shell: layered glassy AI-face silhouette.
    shell = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(shell)
    bbox = (int(size * 0.18), int(size * 0.12), int(size * 0.82), int(size * 0.88))
    d.rounded_rectangle(bbox, radius=int(size * 0.22), fill=(10, 18, 30, 230), outline=(130, 210, 255, 210), width=max(2, size // 80))

    # Inner facial plane.
    inner = (int(size * 0.25), int(size * 0.20), int(size * 0.75), int(size * 0.78))
    d.rounded_rectangle(inner, radius=int(size * 0.16), fill=(20, 34, 52, 210), outline=(80, 150, 220, 180), width=max(1, size // 130))

    # Visor.
    visor = (int(size * 0.31), int(size * 0.33), int(size * 0.69), int(size * 0.49))
    d.rounded_rectangle(visor, radius=int(size * 0.055), fill=(6, 12, 20, 245), outline=(130, 230, 255, 230), width=max(2, size // 100))

    # Reactive eye bars.
    ey = int(size * 0.41)
    d.rounded_rectangle((int(size * 0.36), ey - size//80, int(size * 0.47), ey + size//80), radius=size//90, fill=(145, 235, 255, 245))
    d.rounded_rectangle((int(size * 0.53), ey - size//80, int(size * 0.64), ey + size//80), radius=size//90, fill=(145, 235, 255, 245))

    # Central processor linework.
    for offset, alpha in [(0, 220), (24, 130), (-24, 130)]:
        y = int(size * 0.58) + offset
        d.line((int(size * 0.34), y, int(size * 0.66), y), fill=(90, 190, 255, alpha), width=max(2, size//160))
    d.rounded_rectangle((int(size * 0.42), int(size * 0.53), int(size * 0.58), int(size * 0.64)), radius=size//50, outline=(120, 210, 255, 175), width=max(1, size//160))

    # Side sensor nodes.
    for x in [int(size*0.20), int(size*0.80)]:
        d.ellipse((x-size//35, int(size*0.45)-size//35, x+size//35, int(size*0.45)+size//35), fill=(24, 45, 70, 230), outline=(110, 210, 255, 190), width=max(1, size//180))

    # Highlight sweep.
    hl = Image.new("RGBA", (size, size), (0,0,0,0))
    hd = ImageDraw.Draw(hl)
    hd.polygon([(int(size*.25), int(size*.14)), (int(size*.52), int(size*.14)), (int(size*.34), int(size*.82)), (int(size*.15), int(size*.82))], fill=(255,255,255,28))
    hl = hl.filter(ImageFilter.GaussianBlur(size//80))
    shell.alpha_composite(hl)

    img.alpha_composite(shell)

    # Label text.
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", size // 12)
    except Exception:
        font = ImageFont.load_default()
    text_box = draw.textbbox((0, 0), text, font=font)
    tw = text_box[2] - text_box[0]
    tx = (size - tw) // 2
    ty = int(size * 0.73)
    draw.text((tx, ty), text, font=font, fill=(190, 235, 255, 230))

    # Final subtle sharpen.
    img = img.filter(ImageFilter.UnsharpMask(radius=1.2, percent=115, threshold=2))
    img.save(out)
    print(f"Wrote {out}")


def main():
    ap = argparse.ArgumentParser(description="Generate a clean modern ELI virtual avatar PNG.")
    ap.add_argument("--out", default="assets/eli_avatar_modern.png")
    ap.add_argument("--size", type=int, default=1024)
    ap.add_argument("--text", default="ELI")
    args = ap.parse_args()
    make_avatar(Path(args.out), args.size, args.text)


if __name__ == "__main__":
    main()
