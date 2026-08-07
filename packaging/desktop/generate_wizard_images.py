#!/usr/bin/env python3
"""Generate the Inno Setup wizard branding images from the ELI app icon.

The installer used to ship with no WizardImageFile at all, so every page of the
Windows wizard showed Inno's stock placeholder artwork — the one part of the install
a new user unavoidably looks at, carrying someone else's branding.

Inno Setup will not take .png or .ico for these slots: they must be BMP, and 24-bit
(an alpha channel makes Inno render them wrong). So they cannot simply be the app
icon — they have to be generated. Doing that here, from the single source icon, keeps
them reproducible and in step with the icon instead of being opaque binaries that
nobody can regenerate once the original is lost.

    python3 packaging/desktop/generate_wizard_images.py

Sizes are the ones Inno documents for each DPI step; it picks from the comma-separated
list in installer.iss by the user's scaling.
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFilter
except ImportError:
    sys.exit("Pillow required: pip install pillow")

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "eli-256.png"

# The exact colour of the icon tile's own face, sampled from inside its opaque
# bounding box. It has to match to the byte: the tile is a filled rounded rectangle,
# so any panel colour even slightly different from this draws a visible rectangular
# seam around the artwork. That is also why the backdrop is not brightened — a bloom
# behind the mark lifts the panel away from this value and the seam comes straight
# back. Depth comes from darkening the edges instead, which leaves the centre (where
# the tile actually sits) untouched.
BACKDROP = (0, 16, 21)
# How far the corners are dimmed relative to the centre.
VIGNETTE_FLOOR = 0.55

LARGE_SIZES = [(497, 314), (989, 625)]   # welcome/finish left panel, 100% and 200%
SMALL_SIZES = [(55, 55), (138, 140)]     # header corner, 100% and 250%


def _load_icon() -> Image.Image:
    if not SOURCE.is_file():
        sys.exit(f"source icon missing: {SOURCE}")
    return Image.open(SOURCE).convert("RGBA")


def _large(icon: Image.Image, size: tuple[int, int]) -> Image.Image:
    w, h = size
    canvas = Image.new("RGB", size, BACKDROP)

    # Dim toward the corners so the panel has some depth. Built as a white ellipse
    # blurred into a soft falloff, then used to interpolate between a darkened copy
    # and the flat backdrop — centre stays exactly BACKDROP, which is what keeps the
    # icon tile invisible against it.
    fall = Image.new("L", size, 0)
    r = int(max(w, h) * 0.55)
    ImageDraw.Draw(fall).ellipse(
        [w // 2 - r, h // 2 - r, w // 2 + r, h // 2 + r], fill=255
    )
    fall = fall.filter(ImageFilter.GaussianBlur(radius=max(w, h) // 5))
    dark = Image.new(
        "RGB", size, tuple(int(c * VIGNETTE_FLOOR) for c in BACKDROP)
    )
    canvas = Image.composite(canvas, dark, fall)

    # Crop to the opaque artwork before scaling — the source tile carries transparent
    # margins, and scaling those in would shrink the visible mark for no reason.
    art = icon.crop(icon.getchannel("A").getbbox())
    mark = int(min(w, h) * 0.66)
    art = art.resize((mark, mark), Image.LANCZOS)

    canvas.paste(art.convert("RGB"), ((w - mark) // 2, (h - mark) // 2),
                 art.getchannel("A"))
    return canvas


def _small(icon: Image.Image, size: tuple[int, int]) -> Image.Image:
    canvas = Image.new("RGB", size, BACKDROP)
    art = icon.resize(size, Image.LANCZOS)
    canvas.paste(art, (0, 0), art)
    return canvas


def main() -> int:
    icon = _load_icon()
    written = []
    for i, size in enumerate(LARGE_SIZES):
        p = HERE / (f"wizard_large{'' if i == 0 else f'_{size[0]}'}.bmp")
        # 'RGB' keeps it 24-bit; Inno mis-renders BMPs that carry an alpha channel.
        _large(icon, size).save(p, "BMP")
        written.append(p)
    for i, size in enumerate(SMALL_SIZES):
        p = HERE / (f"wizard_small{'' if i == 0 else f'_{size[0]}'}.bmp")
        _small(icon, size).save(p, "BMP")
        written.append(p)
    for p in written:
        print(f"[OK] {p.relative_to(HERE.parent.parent)}  ({p.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
