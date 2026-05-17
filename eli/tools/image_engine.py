
#Base install:
   # pip install pillow numpy

#Optional diffusion install:
   # pip install torch diffusers transformers accelerate safetensors


from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any
from collections import Counter
from PIL import Image, ImageDraw, ImageFilter, ImageEnhance, ImageFont
import numpy as np
import argparse
import random
import math
import json
import re
import os


Color = Tuple[int, int, int]
RGBA = Tuple[int, int, int, int]


try:
    RESAMPLE_LANCZOS = Image.Resampling.LANCZOS
except AttributeError:
    RESAMPLE_LANCZOS = Image.LANCZOS


# ============================================================
# BASIC COLOR + MATH HELPERS
# ============================================================

def clamp(x, lo=0, hi=255):
    return max(lo, min(hi, x))


def clamp01(x):
    return np.clip(x, 0.0, 1.0)


def lerp(a, b, t):
    return a + (b - a) * t


def smoothstep(t):
    return t * t * (3.0 - 2.0 * t)


def mix(a: Color, b: Color, t: float) -> Color:
    return (
        int(clamp(a[0] + (b[0] - a[0]) * t)),
        int(clamp(a[1] + (b[1] - a[1]) * t)),
        int(clamp(a[2] + (b[2] - a[2]) * t)),
    )


def rgba(c: Color, a: int) -> RGBA:
    return (c[0], c[1], c[2], int(clamp(a)))


def luminance(c: Color) -> float:
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def saturation_score(c: Color) -> float:
    return max(c) - min(c)


def lighten(c: Color, amount: float) -> Color:
    return mix(c, (255, 255, 255), amount)


def darken(c: Color, amount: float) -> Color:
    return mix(c, (0, 0, 0), amount)


def sanitize_filename(text: str, max_len: int = 72) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9_\- ]+", "", text)
    text = re.sub(r"\s+", "_", text)
    return text[:max_len] or "image"


def tokenize(text: str) -> List[str]:
    return re.findall(r"[a-zA-Z0-9']+", text.lower())


STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "with", "in", "on", "at", "to", "for",
    "from", "by", "as", "is", "are", "be", "this", "that", "these", "those",
    "image", "picture", "art", "make", "create", "generate", "design", "show",
    "style", "high", "quality", "detailed", "ultra", "beautiful"
}


def title_from_prompt(prompt: str, fallback: str = "OmniForge") -> str:
    words = [
        w for w in tokenize(prompt)
        if w not in STOPWORDS and len(w) > 2
    ]

    if not words:
        return fallback

    common = Counter(words).most_common(5)
    title_words = [w for w, _ in common[:3]]
    return " ".join(w.capitalize() for w in title_words)


# ============================================================
# PALETTE SYSTEM
# ============================================================

@dataclass
class Palette:
    name: str
    dark: Color
    mid: Color
    primary: Color
    accent: Color
    light: Color
    warm: Color

    def colors(self) -> List[Color]:
        return [self.dark, self.mid, self.primary, self.accent, self.light, self.warm]


BUILTIN_PALETTES: Dict[str, Palette] = {
    "violet_dusk": Palette(
        "violet_dusk",
        dark=(20, 23, 49),
        mid=(69, 65, 112),
        primary=(116, 102, 148),
        accent=(239, 171, 125),
        light=(255, 232, 190),
        warm=(255, 203, 129),
    ),
    "emerald_aurora": Palette(
        "emerald_aurora",
        dark=(7, 31, 38),
        mid=(23, 82, 76),
        primary=(49, 148, 119),
        accent=(126, 255, 200),
        light=(231, 255, 221),
        warm=(201, 255, 169),
    ),
    "crimson_sunset": Palette(
        "crimson_sunset",
        dark=(43, 16, 48),
        mid=(103, 42, 75),
        primary=(178, 65, 94),
        accent=(255, 157, 88),
        light=(255, 230, 177),
        warm=(255, 192, 103),
    ),
    "blue_dawn": Palette(
        "blue_dawn",
        dark=(13, 35, 72),
        mid=(50, 92, 139),
        primary=(92, 153, 193),
        accent=(229, 219, 176),
        light=(246, 252, 255),
        warm=(255, 238, 178),
    ),
    "golden_storm": Palette(
        "golden_storm",
        dark=(31, 32, 45),
        mid=(81, 73, 70),
        primary=(136, 107, 76),
        accent=(241, 177, 94),
        light=(255, 236, 180),
        warm=(255, 199, 91),
    ),
    "neon_noir": Palette(
        "neon_noir",
        dark=(8, 8, 18),
        mid=(25, 18, 54),
        primary=(67, 41, 122),
        accent=(255, 40, 168),
        light=(180, 255, 252),
        warm=(255, 211, 91),
    ),
    "monochrome_luxury": Palette(
        "monochrome_luxury",
        dark=(12, 12, 14),
        mid=(48, 46, 43),
        primary=(104, 99, 91),
        accent=(212, 176, 91),
        light=(245, 238, 221),
        warm=(255, 214, 132),
    ),
}


def palette_from_project_colors(colors: List[Color], name: str = "project_palette") -> Palette:
    if len(colors) < 3:
        return BUILTIN_PALETTES["violet_dusk"]

    colors = sorted(colors, key=lambda c: luminance(c))
    dark = darken(colors[0], 0.25)
    light = lighten(colors[-1], 0.18)

    accent = max(colors, key=saturation_score)
    primary = colors[len(colors) // 2]
    mid = mix(dark, primary, 0.62)
    warm = mix(accent, light, 0.35)

    return Palette(name, dark, mid, primary, accent, light, warm)


def choose_palette(text: str, seed: int, project_colors: Optional[List[Color]] = None) -> Palette:
    text_l = text.lower()

    if project_colors and len(project_colors) >= 3:
        return palette_from_project_colors(project_colors)

    if any(w in text_l for w in ["neon", "cyber", "synth", "nightclub", "glow"]):
        return BUILTIN_PALETTES["neon_noir"]

    if any(w in text_l for w in ["gold", "luxury", "premium", "royal", "elegant"]):
        return BUILTIN_PALETTES["monochrome_luxury"]

    if any(w in text_l for w in ["emerald", "forest", "aurora", "green", "nature"]):
        return BUILTIN_PALETTES["emerald_aurora"]

    if any(w in text_l for w in ["crimson", "red", "sunset", "fire", "volcanic"]):
        return BUILTIN_PALETTES["crimson_sunset"]

    if any(w in text_l for w in ["blue", "ocean", "dawn", "ice", "sky"]):
        return BUILTIN_PALETTES["blue_dawn"]

    names = list(BUILTIN_PALETTES.keys())
    return BUILTIN_PALETTES[names[seed % len(names)]]


# ============================================================
# NOISE SYSTEM
# ============================================================

def value_noise(width: int, height: int, cells_x: int, cells_y: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)

    cells_x = max(1, int(cells_x))
    cells_y = max(1, int(cells_y))

    grid = rng.random((cells_y + 1, cells_x + 1)).astype(np.float32)

    xs = np.linspace(0, cells_x, width, endpoint=False)
    ys = np.linspace(0, cells_y, height, endpoint=False)

    xi = np.floor(xs).astype(int)
    yi = np.floor(ys).astype(int)

    xf = xs - xi
    yf = ys - yi

    xi2 = np.clip(xi + 1, 0, cells_x)
    yi2 = np.clip(yi + 1, 0, cells_y)

    sx = smoothstep(xf)[None, :]
    sy = smoothstep(yf)[:, None]

    n00 = grid[yi[:, None], xi[None, :]]
    n10 = grid[yi[:, None], xi2[None, :]]
    n01 = grid[yi2[:, None], xi[None, :]]
    n11 = grid[yi2[:, None], xi2[None, :]]

    nx0 = lerp(n00, n10, sx)
    nx1 = lerp(n01, n11, sx)

    return lerp(nx0, nx1, sy).astype(np.float32)


def fbm(
    width: int,
    height: int,
    seed: int,
    octaves: int = 6,
    persistence: float = 0.52,
    base_cells_x: int = 2,
    base_cells_y: Optional[int] = None,
) -> np.ndarray:
    if base_cells_y is None:
        base_cells_y = max(1, int(base_cells_x * height / max(width, 1)))

    result = np.zeros((height, width), dtype=np.float32)
    amp = 1.0
    total_amp = 0.0

    for i in range(octaves):
        scale = 2 ** i
        layer = value_noise(
            width,
            height,
            max(1, base_cells_x * scale),
            max(1, base_cells_y * scale),
            seed + i * 997,
        )

        result += layer * amp
        total_amp += amp
        amp *= persistence

    return result / max(total_amp, 1e-6)


def domain_warped_fbm(
    width: int,
    height: int,
    seed: int,
    strength: float = 48.0,
    octaves: int = 6,
    base_cells: int = 2,
) -> np.ndarray:
    warp_x = fbm(width, height, seed + 100, octaves=4, base_cells_x=base_cells)
    warp_y = fbm(width, height, seed + 200, octaves=4, base_cells_x=base_cells)
    detail = fbm(width, height, seed + 300, octaves=octaves, base_cells_x=base_cells)

    yy, xx = np.mgrid[0:height, 0:width]

    wx = np.clip(xx + (warp_x - 0.5) * strength, 0, width - 1).astype(np.int32)
    wy = np.clip(yy + (warp_y - 0.5) * strength, 0, height - 1).astype(np.int32)

    return detail[wy, wx]


# ============================================================
# IMAGE HELPERS
# ============================================================

def make_vertical_gradient(width: int, height: int, top: Color, middle: Color, bottom: Color, middle_at=0.58) -> Image.Image:
    arr = np.zeros((height, width, 3), dtype=np.uint8)

    top_f = np.array(top, dtype=np.float32)
    mid_f = np.array(middle, dtype=np.float32)
    bot_f = np.array(bottom, dtype=np.float32)

    for y in range(height):
        t = y / max(1, height - 1)

        if t < middle_at:
            lt = t / max(1e-6, middle_at)
            color = top_f + (mid_f - top_f) * lt
        else:
            lt = (t - middle_at) / max(1e-6, 1.0 - middle_at)
            color = mid_f + (bot_f - mid_f) * lt

        arr[y, :, :] = np.clip(color, 0, 255)

    return Image.fromarray(arr, "RGB")


def add_radial_glow(
    img: Image.Image,
    center: Tuple[int, int],
    color: Color,
    radius: int,
    strength: int,
    squash_y: float = 1.0,
):
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer, "RGBA")

    step = max(4, radius // 48)

    for r in range(radius, 0, -step):
        a = int(strength * (r / radius) ** 2)
        ry = int(r * squash_y)

        d.ellipse(
            [
                center[0] - r,
                center[1] - ry,
                center[0] + r,
                center[1] + ry,
            ],
            fill=rgba(color, a),
        )

    img.alpha_composite(layer)


def draw_wrapped_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    xy: Tuple[int, int],
    max_width: int,
    fill: RGBA,
    font: ImageFont.ImageFont,
    line_spacing: int = 6,
    align: str = "center",
):
    words = text.split()
    lines = []
    current = ""

    for word in words:
        trial = word if not current else current + " " + word

        try:
            bbox = draw.textbbox((0, 0), trial, font=font)
            tw = bbox[2] - bbox[0]
        except Exception:
            tw = len(trial) * 8

        if tw <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = word

    if current:
        lines.append(current)

    x, y = xy

    for line in lines:
        try:
            bbox = draw.textbbox((0, 0), line, font=font)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
        except Exception:
            tw = len(line) * 8
            th = 12

        if align == "center":
            tx = x - tw // 2
        elif align == "right":
            tx = x - tw
        else:
            tx = x

        draw.text((tx, y), line, font=font, fill=fill)
        y += th + line_spacing


def downsample_if_needed(img: Image.Image, out_w: int, out_h: int, ss: int) -> Image.Image:
    if ss > 1:
        img = img.resize((out_w, out_h), RESAMPLE_LANCZOS)
    return img


# ============================================================
# PROJECT INPUT ANALYSIS
# ============================================================

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"}
TEXT_EXTS = {".txt", ".md", ".json", ".csv", ".yaml", ".yml"}


@dataclass
class ProjectContext:
    text: str
    tags: List[str]
    colors: List[Color]
    files: List[str]


def dominant_colors_from_image(path: Path, max_colors: int = 6) -> List[Color]:
    try:
        img = Image.open(path).convert("RGBA")
        bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
        bg.alpha_composite(img)
        img = bg.convert("RGB")

        img.thumbnail((120, 120), RESAMPLE_LANCZOS)

        quantized = img.quantize(colors=max_colors)
        palette = quantized.getpalette()
        counts = quantized.getcolors(maxcolors=120 * 120)

        if not counts:
            return []

        counts.sort(reverse=True)

        colors = []
        for count, index in counts[:max_colors]:
            base = index * 3
            c = tuple(palette[base:base + 3])
            if len(c) == 3:
                colors.append((int(c[0]), int(c[1]), int(c[2])))

        return colors

    except Exception:
        return []


def analyze_project_folder(path: Optional[str]) -> ProjectContext:
    if not path:
        return ProjectContext(text="", tags=[], colors=[], files=[])

    root = Path(path)
    if not root.exists():
        raise FileNotFoundError(f"Project folder does not exist: {path}")

    text_chunks = []
    tags = []
    colors = []
    files = []

    for p in root.rglob("*"):
        if not p.is_file():
            continue

        files.append(str(p))
        suffix = p.suffix.lower()

        tags.extend(tokenize(p.stem.replace("_", " ").replace("-", " ")))

        if suffix in TEXT_EXTS:
            try:
                content = p.read_text(errors="ignore")
                text_chunks.append(content[:8000])
            except Exception:
                pass

        elif suffix in IMAGE_EXTS:
            colors.extend(dominant_colors_from_image(p, max_colors=5))

    clean_tags = [
        t for t in tags
        if t not in STOPWORDS and len(t) > 2
    ]

    color_counts = Counter(colors)
    common_colors = [c for c, _ in color_counts.most_common(12)]

    return ProjectContext(
        text="\n".join(text_chunks),
        tags=clean_tags[:100],
        colors=common_colors,
        files=files[:200],
    )


# ============================================================
# SCENE SPEC + PROMPT INTERPRETER
# ============================================================

@dataclass
class SceneSpec:
    prompt: str
    negative_prompt: str
    scene_type: str
    style: str
    title: str
    width: int
    height: int
    seed: int
    variant: int
    supersample: int
    palette: Palette
    project_tags: List[str]


SCENE_KEYWORDS = {
    "landscape": {
        "landscape", "world", "mountain", "lake", "island", "forest", "castle",
        "terrain", "fantasy", "waterfall", "valley", "sky", "horizon", "nature"
    },
    "poster": {
        "poster", "cover", "album", "movie", "flyer", "advertisement", "print",
        "campaign", "editorial", "magazine"
    },
    "abstract": {
        "abstract", "pattern", "generative", "fractal", "flow", "texture",
        "wallpaper", "motion", "chaos", "waves"
    },
    "emblem": {
        "logo", "emblem", "badge", "crest", "icon", "seal", "symbol", "mark"
    },
    "product": {
        "product", "bottle", "perfume", "package", "box", "cosmetic", "luxury",
        "label", "brand", "mockup"
    },
    "cityscape": {
        "city", "street", "skyline", "urban", "tower", "skyscraper", "metropolis",
        "cyberpunk", "building", "neon"
    },
    "space": {
        "space", "planet", "galaxy", "nebula", "star", "cosmos", "moon", "asteroid",
        "spaceship", "orbit"
    },
}


def infer_scene_type(text: str, forced: str = "auto") -> str:
    if forced != "auto":
        return forced

    tokens = set(tokenize(text))
    scores = {}

    for scene, keywords in SCENE_KEYWORDS.items():
        scores[scene] = len(tokens & keywords)

    best_scene, best_score = max(scores.items(), key=lambda kv: kv[1])

    if best_score == 0:
        if any(w in tokens for w in {"brand", "campaign", "sale", "launch"}):
            return "poster"
        return "landscape"

    return best_scene


def infer_style(text: str) -> str:
    t = text.lower()

    if any(w in t for w in ["cinematic", "film", "epic", "dramatic"]):
        return "cinematic"

    if any(w in t for w in ["minimal", "clean", "simple", "modern"]):
        return "minimal"

    if any(w in t for w in ["luxury", "premium", "elegant"]):
        return "luxury"

    if any(w in t for w in ["neon", "cyber", "futuristic"]):
        return "neon"

    if any(w in t for w in ["fantasy", "magic", "mythic"]):
        return "fantasy"

    return "balanced"


class PromptInterpreter:
    def build_spec(
        self,
        query: str,
        project: ProjectContext,
        args,
        variant: int,
    ) -> SceneSpec:
        combined_text = " ".join([
            query or "",
            project.text or "",
            " ".join(project.tags[:50]),
        ]).strip()

        if not combined_text:
            combined_text = "cinematic fantasy landscape with atmospheric light"

        scene_type = infer_scene_type(combined_text, forced=args.type)
        style = infer_style(combined_text)

        seed = args.seed + variant * 7919
        palette = choose_palette(combined_text, seed, project.colors)

        title = args.title or title_from_prompt(combined_text)

        return SceneSpec(
            prompt=combined_text,
            negative_prompt=args.negative or "low quality, cluttered, ugly composition, unreadable text",
            scene_type=scene_type,
            style=style,
            title=title,
            width=args.width,
            height=args.height,
            seed=seed,
            variant=variant,
            supersample=max(1, args.supersample),
            palette=palette,
            project_tags=project.tags[:50],
        )


# ============================================================
# PROCEDURAL RENDER CONTEXT
# ============================================================

class RenderContext:
    def __init__(self, spec: SceneSpec):
        self.spec = spec
        self.ss = max(1, spec.supersample)

        self.out_w = spec.width
        self.out_h = spec.height
        self.w = spec.width * self.ss
        self.h = spec.height * self.ss

        self.seed = spec.seed
        self.rng = np.random.default_rng(spec.seed)
        self.py = random.Random(spec.seed)

        self.p = spec.palette
        self.tokens = set(tokenize(spec.prompt))

    def scaled(self, value: float) -> int:
        return int(value * self.ss)


# ============================================================
# PROCEDURAL RENDERERS
# ============================================================

def render_landscape(ctx: RenderContext) -> Image.Image:
    w, h = ctx.w, ctx.h
    p = ctx.p
    rng = ctx.rng
    py = ctx.py

    horizon = int(h * rng.uniform(0.52, 0.60))
    sun = (
        int(w * rng.uniform(0.18, 0.82)),
        int(h * rng.uniform(0.14, 0.31)),
    )

    img = make_vertical_gradient(
        w,
        h,
        top=p.dark,
        middle=mix(p.mid, p.primary, 0.45),
        bottom=mix(p.accent, p.light, 0.25),
        middle_at=0.62,
    ).convert("RGBA")

    add_radial_glow(img, sun, p.warm, int(min(w, h) * 0.42), 22)

    d = ImageDraw.Draw(img, "RGBA")
    sr = int(w * rng.uniform(0.022, 0.044))
    d.ellipse([sun[0] - sr, sun[1] - sr, sun[0] + sr, sun[1] + sr], fill=rgba(p.light, 230))
    d.ellipse([sun[0] - sr // 2, sun[1] - sr // 2, sun[0] + sr // 2, sun[1] + sr // 2], fill=rgba((255, 255, 240), 255))

    # Clouds.
    cloud_noise = domain_warped_fbm(
        w,
        h,
        seed=ctx.seed + 301,
        strength=w * 0.045,
        octaves=7,
        base_cells=2,
    )

    y = np.arange(h)[:, None]
    sky_fade = clamp01((horizon - y) / (h * 0.45))
    top_fade = np.linspace(1.0, 0.0, h)[:, None]

    mask = cloud_noise * sky_fade * top_fade
    mask = clamp01((mask - 0.22) * 3.5)
    alpha = (mask * 115).astype(np.uint8)

    clouds = np.zeros((h, w, 4), dtype=np.uint8)
    cloud_c = mix(p.light, p.accent, 0.25)
    clouds[:, :, 0] = cloud_c[0]
    clouds[:, :, 1] = cloud_c[1]
    clouds[:, :, 2] = cloud_c[2]
    clouds[:, :, 3] = alpha

    cloud_img = Image.fromarray(clouds, "RGBA").filter(ImageFilter.GaussianBlur(ctx.scaled(5)))
    img.alpha_composite(cloud_img)

    # Mountains.
    for i in range(3):
        base_y = int(horizon + h * (i * 0.065 - 0.025))
        amp = int(h * (0.15 + i * 0.035) * rng.uniform(0.85, 1.2))
        points = 10 + i * 4

        control_x = np.linspace(0, w - 1, points)
        control_y = np.array([base_y - py.random() * amp for _ in range(points)])
        ridge = np.interp(np.arange(w), control_x, control_y)
        ridge += np.sin(np.linspace(0, math.pi * (2.5 + i), w)) * amp * 0.10

        layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer, "RGBA")

        mountain_c = darken(mix(p.mid, p.dark, 0.25 + i * 0.16), 0.04)
        fill = rgba(mountain_c, 135 + i * 38)

        polygon = [(0, h)]
        polygon.extend([(x, int(ridge[x])) for x in range(w)])
        polygon.append((w, h))

        ld.polygon(polygon, fill=fill)

        for x in range(0, w, ctx.scaled(4)):
            yy = int(ridge[x])
            ld.line(
                [(x, yy), (x + ctx.scaled(3), yy + ctx.scaled(2))],
                fill=rgba(p.light, 20 + i * 7),
                width=max(1, ctx.scaled(1)),
            )

        layer = layer.filter(ImageFilter.GaussianBlur(ctx.scaled(max(0.6, 2.8 - i))))
        img.alpha_composite(layer)

    # Water reflection.
    water_h = h - horizon
    reflection = img.crop((0, 0, w, horizon)).transpose(Image.FLIP_TOP_BOTTOM)
    reflection = reflection.resize((w, water_h), RESAMPLE_LANCZOS)

    refl = np.array(reflection).astype(np.float32)

    ripple = value_noise(w, water_h, 24, 9, ctx.seed + 808)

    for yy in range(water_h):
        shift = int(
            math.sin(yy * 0.045 / ctx.ss) * 7 * ctx.ss
            + math.sin(yy * 0.013 / ctx.ss + 2.4) * 12 * ctx.ss
            + (ripple[yy, w // 2] - 0.5) * 18 * ctx.ss
        )
        refl[yy] = np.roll(refl[yy], shift, axis=0)

    water_grad = make_vertical_gradient(
        w,
        water_h,
        top=mix(p.mid, p.primary, 0.35),
        middle=mix(p.dark, p.primary, 0.35),
        bottom=darken(p.dark, 0.15),
        middle_at=0.45,
    ).convert("RGBA")

    water_arr = np.array(water_grad).astype(np.float32)
    depth = np.linspace(0.72, 0.22, water_h)[:, None, None]
    blended = refl * depth + water_arr * (1.0 - depth)
    blended[:, :, 3] = 255

    water = Image.fromarray(np.clip(blended, 0, 255).astype(np.uint8), "RGBA")
    wd = ImageDraw.Draw(water, "RGBA")

    for _ in range(int(160 * w * h / (1400 * 900 * ctx.ss * ctx.ss))):
        yy = py.randint(5, max(6, water_h - 8))
        xx = py.randint(0, w)
        length = py.randint(ctx.scaled(30), ctx.scaled(190))
        wd.line(
            [(xx, yy), (min(w, xx + length), yy)],
            fill=rgba(p.light, py.randint(10, 44)),
            width=max(1, ctx.scaled(1)),
        )

    img.alpha_composite(water, (0, horizon))

    # Floating island.
    if "island" in ctx.tokens or "fantasy" in ctx.tokens or py.random() < 0.85:
        cx = int(w * rng.uniform(0.42, 0.58))
        cy = int(h * rng.uniform(0.43, 0.53))
        top_width = int(w * rng.uniform(0.27, 0.38))

        island = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        idr = ImageDraw.Draw(island, "RGBA")

        top_points = []
        for i in range(28):
            t = i / 27
            x = cx - top_width // 2 + int(t * top_width)
            wobble = math.sin(t * math.pi * 6) * ctx.scaled(12) + py.randint(-ctx.scaled(8), ctx.scaled(8))
            yv = cy + int(wobble)
            top_points.append((x, yv))

        bottom_tip = (cx + ctx.scaled(10), cy + int(h * 0.28))

        dirt_poly = top_points + [
            (cx + int(top_width * 0.47), cy + int(h * 0.06)),
            (cx + int(top_width * 0.27), cy + int(h * 0.18)),
            bottom_tip,
            (cx - int(top_width * 0.27), cy + int(h * 0.18)),
            (cx - int(top_width * 0.47), cy + int(h * 0.06)),
        ]

        idr.polygon(dirt_poly, fill=rgba(darken(p.mid, 0.18), 255))

        for _ in range(120):
            x1 = py.randint(cx - int(top_width * 0.44), cx + int(top_width * 0.44))
            y1 = py.randint(cy + ctx.scaled(16), cy + int(h * 0.23))
            x2 = x1 + py.randint(-ctx.scaled(40), ctx.scaled(40))
            y2 = y1 + py.randint(ctx.scaled(12), ctx.scaled(48))
            idr.line([(x1, y1), (x2, y2)], fill=rgba(darken(p.dark, 0.05), py.randint(35, 95)), width=py.randint(1, max(2, ctx.scaled(3))))

        grass_poly = top_points + [
            (cx + top_width // 2 - ctx.scaled(20), cy + ctx.scaled(42)),
            (cx - top_width // 2 + ctx.scaled(20), cy + ctx.scaled(42)),
        ]

        idr.polygon(grass_poly, fill=rgba(mix(p.primary, p.accent, 0.18), 255))

        for x, yv in top_points[::2]:
            idr.line(
                [(x - ctx.scaled(8), yv - ctx.scaled(1)), (x + ctx.scaled(10), yv - ctx.scaled(4))],
                fill=rgba(lighten(p.primary, 0.35), 235),
                width=max(1, ctx.scaled(2)),
            )

        # Roots.
        for _ in range(32):
            sx = py.randint(cx - int(top_width * 0.41), cx + int(top_width * 0.41))
            sy = cy + py.randint(ctx.scaled(25), ctx.scaled(55))
            length = py.randint(ctx.scaled(45), ctx.scaled(155))
            pts = []
            for j in range(6):
                pts.append((sx + py.randint(-ctx.scaled(16), ctx.scaled(16)), sy + int(length * j / 5)))
            idr.line(pts, fill=(45, 30, 25, 170), width=py.randint(1, max(2, ctx.scaled(3))))

        # Crystals.
        for _ in range(py.randint(8, 15)):
            x = py.randint(cx - int(top_width * 0.36), cx + int(top_width * 0.36))
            yv = cy + py.randint(-ctx.scaled(18), ctx.scaled(12))
            ch = py.randint(ctx.scaled(40), ctx.scaled(105))
            cw = py.randint(ctx.scaled(16), ctx.scaled(34))
            col = py.choice([p.accent, p.light, p.warm])

            crystal = [
                (x, yv - ch),
                (x + cw // 2, yv - ch // 3),
                (x + cw // 3, yv + ctx.scaled(10)),
                (x - cw // 3, yv + ctx.scaled(10)),
                (x - cw // 2, yv - ch // 3),
            ]
            idr.polygon(crystal, fill=rgba(col, 175), outline=rgba(p.light, 130))
            idr.line([(x, yv - ch), (x, yv + ctx.scaled(6))], fill=rgba((255, 255, 255), 95), width=max(1, ctx.scaled(1)))

        # Trees.
        for _ in range(py.randint(12, 22)):
            x = py.randint(cx - int(top_width * 0.40), cx + int(top_width * 0.40))
            yv = cy + py.randint(-ctx.scaled(25), ctx.scaled(8))
            th = py.randint(ctx.scaled(25), ctx.scaled(46))
            idr.line([(x, yv), (x + py.randint(-ctx.scaled(5), ctx.scaled(5)), yv - th)], fill=(54, 34, 26, 255), width=py.randint(max(2, ctx.scaled(3)), max(3, ctx.scaled(5))))

            for _ in range(7):
                ox = py.randint(-ctx.scaled(18), ctx.scaled(18))
                oy = py.randint(-ctx.scaled(16), ctx.scaled(12))
                rr = py.randint(ctx.scaled(9), ctx.scaled(18))
                leaf = mix(p.primary, p.light, py.random() * 0.25)
                idr.ellipse([x + ox - rr, yv - th + oy - rr, x + ox + rr, yv - th + oy + rr], fill=rgba(leaf, 230))

        # Optional castle or tower.
        if {"castle", "tower", "temple", "city"} & ctx.tokens:
            bx = cx - ctx.scaled(45)
            by = cy - ctx.scaled(55)
            building_c = rgba(darken(p.dark, 0.02), 220)
            idr.rectangle([bx, by, bx + ctx.scaled(90), cy], fill=building_c)
            for tx in [bx, bx + ctx.scaled(35), bx + ctx.scaled(70)]:
                idr.rectangle([tx, by - ctx.scaled(45), tx + ctx.scaled(20), cy], fill=building_c)
                idr.polygon([(tx - ctx.scaled(5), by - ctx.scaled(45)), (tx + ctx.scaled(10), by - ctx.scaled(70)), (tx + ctx.scaled(25), by - ctx.scaled(45))], fill=rgba(p.accent, 200))

        # Glow under island.
        glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow, "RGBA")
        max_r = int(w * 0.14)
        for rr in range(max_r, 0, -ctx.scaled(10)):
            gd.ellipse(
                [cx - rr, cy + ctx.scaled(120) - rr // 2, cx + rr, cy + ctx.scaled(120) + rr // 2],
                fill=rgba(p.accent, int(38 * (rr / max_r) ** 2)),
            )

        img.alpha_composite(glow)
        img.alpha_composite(island)

    # Particles and birds.
    particle_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    pd = ImageDraw.Draw(particle_layer, "RGBA")

    for _ in range(420):
        x = py.randint(0, w)
        yv = py.randint(0, h)
        rr = py.choice([1, 1, 1, 2, 2, 3]) * ctx.ss
        dist = math.dist((x, yv), sun)
        sun_bonus = max(0.0, 1.0 - dist / (650 * ctx.ss))
        a = int(py.randint(10, 68) * (0.45 + sun_bonus))
        pd.ellipse([x - rr, yv - rr, x + rr, yv + rr], fill=rgba(p.light, a))

    for _ in range(py.randint(5, 22)):
        x = py.randint(0, w)
        yv = py.randint(int(h * 0.11), max(int(h * 0.12), horizon - int(h * 0.07)))
        size = py.randint(ctx.scaled(5), ctx.scaled(17))
        pd.line([(x - size, yv), (x, yv - size // 2), (x + size, yv)], fill=rgba(p.dark, py.randint(70, 135)), width=max(1, ctx.scaled(1)))

    particle_layer = particle_layer.filter(ImageFilter.GaussianBlur(max(0.4, ctx.ss * 0.4)))
    img.alpha_composite(particle_layer)

    return finish_image(ctx, img)


def render_space(ctx: RenderContext) -> Image.Image:
    w, h = ctx.w, ctx.h
    p = ctx.p
    py = ctx.py

    bg = make_vertical_gradient(w, h, darken(p.dark, 0.25), p.dark, darken(p.mid, 0.20), 0.55).convert("RGBA")

    nebula = domain_warped_fbm(w, h, ctx.seed + 444, strength=w * 0.08, octaves=7, base_cells=2)
    nebula = clamp01((nebula - 0.30) * 2.4)

    arr = np.zeros((h, w, 4), dtype=np.uint8)
    c1 = p.primary
    c2 = p.accent

    arr[:, :, 0] = (c1[0] * (1 - nebula) + c2[0] * nebula).astype(np.uint8)
    arr[:, :, 1] = (c1[1] * (1 - nebula) + c2[1] * nebula).astype(np.uint8)
    arr[:, :, 2] = (c1[2] * (1 - nebula) + c2[2] * nebula).astype(np.uint8)
    arr[:, :, 3] = (nebula * 115).astype(np.uint8)

    bg.alpha_composite(Image.fromarray(arr, "RGBA").filter(ImageFilter.GaussianBlur(ctx.scaled(4))))

    d = ImageDraw.Draw(bg, "RGBA")

    for _ in range(int(1200 * w * h / (1400 * 900 * ctx.ss * ctx.ss))):
        x = py.randint(0, w)
        y = py.randint(0, h)
        r = py.choice([1, 1, 1, 2]) * ctx.ss
        a = py.randint(75, 240)
        d.ellipse([x - r, y - r, x + r, y + r], fill=rgba(p.light, a))

    planet_count = 1 if "planet" in ctx.tokens else py.randint(1, 3)

    for _ in range(planet_count):
        cx = py.randint(int(w * 0.18), int(w * 0.85))
        cy = py.randint(int(h * 0.18), int(h * 0.70))
        r = py.randint(int(min(w, h) * 0.055), int(min(w, h) * 0.16))

        add_radial_glow(bg, (cx, cy), p.accent, r * 4, 20, squash_y=1.0)

        planet = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        pd = ImageDraw.Draw(planet, "RGBA")

        pd.ellipse([cx - r, cy - r, cx + r, cy + r], fill=rgba(mix(p.primary, p.light, 0.25), 255))

        shadow_offset = int(r * 0.35)
        pd.ellipse([cx - r + shadow_offset, cy - r, cx + r + shadow_offset, cy + r], fill=rgba(darken(p.dark, 0.1), 145))

        for i in range(8):
            yy = cy - r + int((2 * r) * i / 8)
            pd.arc([cx - r, yy - r // 3, cx + r, yy + r // 3], 0, 180, fill=rgba(p.light, 30), width=max(1, ctx.scaled(1)))

        if py.random() < 0.5 or "ring" in ctx.tokens:
            pd.ellipse([cx - int(r * 1.8), cy - int(r * 0.45), cx + int(r * 1.8), cy + int(r * 0.45)], outline=rgba(p.warm, 120), width=max(2, ctx.scaled(3)))

        bg.alpha_composite(planet)

    return finish_image(ctx, bg)


def render_cityscape(ctx: RenderContext) -> Image.Image:
    w, h = ctx.w, ctx.h
    p = ctx.p
    py = ctx.py
    rng = ctx.rng

    horizon = int(h * rng.uniform(0.53, 0.68))

    img = make_vertical_gradient(w, h, p.dark, p.mid, mix(p.primary, p.accent, 0.3), 0.55).convert("RGBA")

    sun = (int(w * rng.uniform(0.15, 0.85)), int(h * rng.uniform(0.16, 0.30)))
    add_radial_glow(img, sun, p.accent, int(min(w, h) * 0.36), 26)

    d = ImageDraw.Draw(img, "RGBA")

    # Buildings.
    x = -ctx.scaled(30)
    while x < w + ctx.scaled(30):
        bw = py.randint(ctx.scaled(35), ctx.scaled(110))
        bh = py.randint(int(h * 0.18), int(h * 0.58))
        y = horizon - bh
        c = darken(mix(p.dark, p.mid, py.random() * 0.4), py.random() * 0.12)

        d.rectangle([x, y, x + bw, horizon + ctx.scaled(10)], fill=rgba(c, 235))

        if py.random() < 0.38:
            d.polygon([(x, y), (x + bw // 2, y - py.randint(ctx.scaled(25), ctx.scaled(95))), (x + bw, y)], fill=rgba(c, 235))

        win_w = max(ctx.scaled(3), bw // py.randint(8, 14))
        win_h = max(ctx.scaled(4), ctx.scaled(8))

        for wx in range(x + ctx.scaled(7), x + bw - ctx.scaled(7), win_w * 2):
            for wy in range(y + ctx.scaled(12), horizon - ctx.scaled(10), win_h * 2):
                if py.random() < 0.50:
                    wc = p.accent if "neon" in ctx.tokens or ctx.spec.style == "neon" else p.warm
                    d.rectangle([wx, wy, wx + win_w, wy + win_h], fill=rgba(wc, py.randint(75, 210)))

        x += bw + py.randint(ctx.scaled(2), ctx.scaled(8))

    # Foreground road or water.
    if "water" in ctx.tokens or py.random() < 0.45:
        water_h = h - horizon
        refl = img.crop((0, int(h * 0.20), w, horizon)).transpose(Image.FLIP_TOP_BOTTOM)
        refl = refl.resize((w, water_h), RESAMPLE_LANCZOS)
        arr = np.array(refl).astype(np.float32)

        for yy in range(water_h):
            arr[yy] = np.roll(arr[yy], int(math.sin(yy * 0.035) * 12 * ctx.ss), axis=0)

        grad = np.array(make_vertical_gradient(w, water_h, p.mid, p.dark, darken(p.dark, 0.2), 0.5).convert("RGBA")).astype(np.float32)
        depth = np.linspace(0.6, 0.18, water_h)[:, None, None]
        final = arr * depth + grad * (1 - depth)
        final[:, :, 3] = 255

        img.alpha_composite(Image.fromarray(np.clip(final, 0, 255).astype(np.uint8), "RGBA"), (0, horizon))
    else:
        d.rectangle([0, horizon, w, h], fill=rgba(darken(p.dark, 0.15), 255))
        for i in range(16):
            yy = horizon + int((h - horizon) * i / 16)
            d.line([(0, yy), (w, yy + ctx.scaled(35))], fill=rgba(p.light, 14), width=max(1, ctx.scaled(1)))

    # Neon signs.
    for _ in range(20):
        x = py.randint(0, w)
        y = py.randint(int(h * 0.25), horizon)
        length = py.randint(ctx.scaled(18), ctx.scaled(90))
        color = py.choice([p.accent, p.light, p.warm])
        d.line([(x, y), (x + length, y)], fill=rgba(color, py.randint(90, 220)), width=max(1, ctx.scaled(3)))

    return finish_image(ctx, img)


def render_abstract(ctx: RenderContext) -> Image.Image:
    w, h = ctx.w, ctx.h
    p = ctx.p
    py = ctx.py

    img = make_vertical_gradient(w, h, p.dark, p.mid, p.primary, 0.55).convert("RGBA")

    noise = domain_warped_fbm(w, h, ctx.seed + 777, strength=w * 0.10, octaves=8, base_cells=3)
    arr = np.zeros((h, w, 4), dtype=np.uint8)

    c1 = np.array(p.primary)
    c2 = np.array(p.accent)
    c3 = np.array(p.light)

    mask = clamp01((noise - 0.18) * 1.4)
    color = c1[None, None, :] * (1 - mask[:, :, None]) + c2[None, None, :] * mask[:, :, None]
    color = color * 0.75 + c3[None, None, :] * (mask[:, :, None] ** 3) * 0.25

    arr[:, :, :3] = np.clip(color, 0, 255).astype(np.uint8)
    arr[:, :, 3] = (mask * 170).astype(np.uint8)

    img.alpha_composite(Image.fromarray(arr, "RGBA").filter(ImageFilter.GaussianBlur(ctx.scaled(2))))

    d = ImageDraw.Draw(img, "RGBA")

    for _ in range(90):
        cx = py.randint(-w // 10, int(w * 1.1))
        cy = py.randint(-h // 10, int(h * 1.1))
        r = py.randint(ctx.scaled(20), ctx.scaled(220))
        col = py.choice([p.primary, p.accent, p.light, p.warm])
        a = py.randint(12, 70)

        if py.random() < 0.5:
            d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=rgba(col, a), width=py.randint(1, max(2, ctx.scaled(5))))
        else:
            points = []
            sides = py.randint(3, 8)
            for i in range(sides):
                ang = math.tau * i / sides + py.random() * 0.3
                points.append((cx + int(math.cos(ang) * r), cy + int(math.sin(ang) * r)))
            d.polygon(points, outline=rgba(col, a), fill=rgba(col, a // 4))

    # Flow lines.
    for _ in range(160):
        x = py.randint(0, w)
        y = py.randint(0, h)
        pts = []
        angle = py.random() * math.tau

        for _j in range(28):
            pts.append((x, y))
            angle += (py.random() - 0.5) * 0.5
            x += int(math.cos(angle) * ctx.scaled(12))
            y += int(math.sin(angle) * ctx.scaled(12))
            if x < 0 or x >= w or y < 0 or y >= h:
                break

        if len(pts) > 1:
            d.line(pts, fill=rgba(py.choice([p.accent, p.light, p.warm]), py.randint(20, 90)), width=max(1, ctx.scaled(1)))

    return finish_image(ctx, img)


def render_poster(ctx: RenderContext) -> Image.Image:
    w, h = ctx.w, ctx.h
    p = ctx.p
    py = ctx.py

    img = make_vertical_gradient(w, h, p.dark, p.mid, mix(p.primary, p.accent, 0.25), 0.66).convert("RGBA")
    d = ImageDraw.Draw(img, "RGBA")

    add_radial_glow(img, (int(w * 0.72), int(h * 0.26)), p.accent, int(min(w, h) * 0.42), 26)

    # Graphic ribbons.
    for _ in range(18):
        x1 = py.randint(-w // 3, w)
        y1 = py.randint(0, h)
        x2 = x1 + py.randint(ctx.scaled(120), ctx.scaled(520))
        y2 = y1 + py.randint(-ctx.scaled(220), ctx.scaled(220))
        width = py.randint(ctx.scaled(12), ctx.scaled(55))
        col = py.choice([p.primary, p.accent, p.warm, p.light])
        d.line([(x1, y1), (x2, y2)], fill=rgba(col, py.randint(35, 120)), width=width)

    # Central design plate.
    margin = int(min(w, h) * 0.08)
    plate = [margin, margin, w - margin, h - margin]
    d.rounded_rectangle(plate, radius=ctx.scaled(36), outline=rgba(p.light, 95), width=max(2, ctx.scaled(3)), fill=rgba(darken(p.dark, 0.08), 90))

    # Abstract hero shape.
    cx, cy = w // 2, int(h * 0.44)
    max_r = int(min(w, h) * 0.22)

    for i in range(9):
        r = max_r - i * ctx.scaled(18)
        if r <= 0:
            continue
        col = [p.accent, p.primary, p.warm, p.light][i % 4]
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=rgba(col, 155 - i * 12), width=max(1, ctx.scaled(4)))

    sides = 7
    points = []
    for i in range(sides):
        a = math.tau * i / sides - math.pi / 2
        rr = max_r * (0.78 + 0.22 * math.sin(i * 2.1 + ctx.seed))
        points.append((cx + int(math.cos(a) * rr), cy + int(math.sin(a) * rr)))
    d.polygon(points, fill=rgba(p.accent, 90), outline=rgba(p.light, 150))

    # Typography.
    try:
        font_title = ImageFont.truetype("DejaVuSans-Bold.ttf", ctx.scaled(58))
        font_sub = ImageFont.truetype("DejaVuSans.ttf", ctx.scaled(22))
    except Exception:
        font_title = ImageFont.load_default()
        font_sub = ImageFont.load_default()

    title = ctx.spec.title.upper()
    subtitle = " / ".join(ctx.project_tags[:5]) if ctx.project_tags else ctx.spec.style.upper() + " GENERATIVE IMAGE"

    draw_wrapped_text(
        d,
        title,
        (w // 2, int(h * 0.70)),
        max_width=int(w * 0.76),
        fill=rgba(p.light, 245),
        font=font_title,
        line_spacing=ctx.scaled(8),
        align="center",
    )

    draw_wrapped_text(
        d,
        subtitle[:110],
        (w // 2, int(h * 0.84)),
        max_width=int(w * 0.70),
        fill=rgba(mix(p.light, p.accent, 0.30), 180),
        font=font_sub,
        line_spacing=ctx.scaled(5),
        align="center",
    )

    return finish_image(ctx, img)


def render_emblem(ctx: RenderContext) -> Image.Image:
    w, h = ctx.w, ctx.h
    p = ctx.p
    py = ctx.py

    img = make_vertical_gradient(w, h, darken(p.dark, 0.08), p.mid, p.dark, 0.5).convert("RGBA")
    d = ImageDraw.Draw(img, "RGBA")

    cx, cy = w // 2, h // 2
    r = int(min(w, h) * 0.31)

    add_radial_glow(img, (cx, cy), p.accent, int(r * 1.8), 24)

    for i in range(5):
        rr = r - i * ctx.scaled(18)
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], outline=rgba([p.light, p.accent, p.warm, p.primary, p.light][i], 190 - i * 25), width=max(2, ctx.scaled(3)))

    # Crest polygon.
    crest = [
        (cx, cy - r),
        (cx + int(r * 0.70), cy - int(r * 0.35)),
        (cx + int(r * 0.56), cy + int(r * 0.56)),
        (cx, cy + r),
        (cx - int(r * 0.56), cy + int(r * 0.56)),
        (cx - int(r * 0.70), cy - int(r * 0.35)),
    ]
    d.polygon(crest, fill=rgba(darken(p.dark, 0.05), 185), outline=rgba(p.light, 165))

    tokens = ctx.tokens

    if "leaf" in tokens or "nature" in tokens or "forest" in tokens:
        for side in [-1, 1]:
            for i in range(8):
                y = cy + int((i - 4) * r * 0.10)
                x = cx + side * int(r * 0.18)
                d.ellipse([x, y - ctx.scaled(15), x + side * int(r * 0.38), y + ctx.scaled(15)], fill=rgba(p.accent, 140), outline=rgba(p.light, 120))
        d.line([(cx, cy - int(r * 0.45)), (cx, cy + int(r * 0.50))], fill=rgba(p.light, 160), width=max(2, ctx.scaled(3)))

    elif "wave" in tokens or "ocean" in tokens or "water" in tokens:
        for i in range(6):
            yy = cy - int(r * 0.25) + i * int(r * 0.11)
            d.arc([cx - int(r * 0.52), yy - int(r * 0.14), cx + int(r * 0.52), yy + int(r * 0.18)], 0, 180, fill=rgba(p.accent, 175), width=max(2, ctx.scaled(4)))

    elif "star" in tokens or "space" in tokens:
        points = []
        for i in range(14):
            a = math.tau * i / 14 - math.pi / 2
            rr = r * (0.50 if i % 2 == 0 else 0.20)
            points.append((cx + int(math.cos(a) * rr), cy + int(math.sin(a) * rr)))
        d.polygon(points, fill=rgba(p.warm, 185), outline=rgba(p.light, 210))

    else:
        # Default crystal/diamond mark.
        diamond = [
            (cx, cy - int(r * 0.55)),
            (cx + int(r * 0.42), cy),
            (cx, cy + int(r * 0.55)),
            (cx - int(r * 0.42), cy),
        ]
        d.polygon(diamond, fill=rgba(p.accent, 165), outline=rgba(p.light, 220))
        d.line([(cx, cy - int(r * 0.55)), (cx, cy + int(r * 0.55))], fill=rgba(p.light, 125), width=max(1, ctx.scaled(2)))
        d.line([(cx - int(r * 0.42), cy), (cx + int(r * 0.42), cy)], fill=rgba(p.light, 95), width=max(1, ctx.scaled(2)))

    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", ctx.scaled(34))
    except Exception:
        font = ImageFont.load_default()

    draw_wrapped_text(
        d,
        ctx.spec.title.upper(),
        (cx, cy + int(r * 1.18)),
        max_width=int(w * 0.70),
        fill=rgba(p.light, 225),
        font=font,
        line_spacing=ctx.scaled(5),
        align="center",
    )

    return finish_image(ctx, img)


def render_product(ctx: RenderContext) -> Image.Image:
    w, h = ctx.w, ctx.h
    p = ctx.p
    py = ctx.py

    img = make_vertical_gradient(w, h, darken(p.dark, 0.05), p.mid, darken(p.dark, 0.20), 0.55).convert("RGBA")

    add_radial_glow(img, (int(w * 0.58), int(h * 0.32)), p.accent, int(min(w, h) * 0.40), 28)

    d = ImageDraw.Draw(img, "RGBA")

    # Floor.
    floor_y = int(h * 0.76)
    d.rectangle([0, floor_y, w, h], fill=rgba(darken(p.dark, 0.12), 215))

    # Product silhouette.
    cx = w // 2
    base_y = int(h * 0.75)

    product_type = "box"
    if "bottle" in ctx.tokens or "perfume" in ctx.tokens or "cosmetic" in ctx.tokens:
        product_type = "bottle"

    shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow, "RGBA")
    sd.ellipse([cx - int(w * 0.20), base_y - ctx.scaled(20), cx + int(w * 0.20), base_y + ctx.scaled(30)], fill=(0, 0, 0, 110))
    shadow = shadow.filter(ImageFilter.GaussianBlur(ctx.scaled(18)))
    img.alpha_composite(shadow)

    if product_type == "bottle":
        bw = int(w * 0.18)
        bh = int(h * 0.46)
        x1 = cx - bw // 2
        y1 = base_y - bh

        d.rounded_rectangle([x1, y1, x1 + bw, base_y], radius=ctx.scaled(32), fill=rgba(lighten(p.dark, 0.08), 245), outline=rgba(p.light, 120), width=max(2, ctx.scaled(2)))
        d.rectangle([cx - bw // 5, y1 - ctx.scaled(50), cx + bw // 5, y1 + ctx.scaled(15)], fill=rgba(darken(p.dark, 0.02), 245), outline=rgba(p.light, 95))
        d.rectangle([cx - bw // 3, y1 - ctx.scaled(75), cx + bw // 3, y1 - ctx.scaled(45)], fill=rgba(p.accent, 220))

        label = [x1 + ctx.scaled(18), y1 + int(bh * 0.44), x1 + bw - ctx.scaled(18), y1 + int(bh * 0.72)]
        d.rounded_rectangle(label, radius=ctx.scaled(10), fill=rgba(mix(p.light, p.accent, 0.18), 230))
    else:
        bw = int(w * 0.28)
        bh = int(h * 0.44)
        x1 = cx - bw // 2
        y1 = base_y - bh

        side = int(bw * 0.25)

        front = [(x1, y1), (x1 + bw, y1), (x1 + bw, base_y), (x1, base_y)]
        side_poly = [(x1 + bw, y1), (x1 + bw + side, y1 - ctx.scaled(35)), (x1 + bw + side, base_y - ctx.scaled(40)), (x1 + bw, base_y)]
        top_poly = [(x1, y1), (x1 + side, y1 - ctx.scaled(35)), (x1 + bw + side, y1 - ctx.scaled(35)), (x1 + bw, y1)]

        d.polygon(front, fill=rgba(lighten(p.dark, 0.10), 245), outline=rgba(p.light, 95))
        d.polygon(side_poly, fill=rgba(darken(p.mid, 0.10), 245), outline=rgba(p.light, 75))
        d.polygon(top_poly, fill=rgba(lighten(p.mid, 0.10), 245), outline=rgba(p.light, 75))

        label = [x1 + ctx.scaled(28), y1 + int(bh * 0.33), x1 + bw - ctx.scaled(28), y1 + int(bh * 0.68)]
        d.rounded_rectangle(label, radius=ctx.scaled(12), fill=rgba(mix(p.light, p.accent, 0.14), 235))

    try:
        font_title = ImageFont.truetype("DejaVuSans-Bold.ttf", ctx.scaled(30))
        font_small = ImageFont.truetype("DejaVuSans.ttf", ctx.scaled(14))
    except Exception:
        font_title = ImageFont.load_default()
        font_small = ImageFont.load_default()

    draw_wrapped_text(
        d,
        ctx.spec.title.upper(),
        ((label[0] + label[2]) // 2, label[1] + ctx.scaled(18)),
        max_width=label[2] - label[0] - ctx.scaled(20),
        fill=rgba(darken(p.dark, 0.08), 245),
        font=font_title,
        line_spacing=ctx.scaled(4),
        align="center",
    )

    draw_wrapped_text(
        d,
        ctx.spec.style.upper(),
        ((label[0] + label[2]) // 2, label[3] - ctx.scaled(34)),
        max_width=label[2] - label[0] - ctx.scaled(20),
        fill=rgba(darken(p.dark, 0.05), 170),
        font=font_small,
        line_spacing=ctx.scaled(2),
        align="center",
    )

    # Decorative particles.
    for _ in range(120):
        x = py.randint(0, w)
        y = py.randint(0, int(h * 0.75))
        rr = py.choice([1, 1, 2, 3]) * ctx.ss
        d.ellipse([x - rr, y - rr, x + rr, y + rr], fill=rgba(py.choice([p.accent, p.light, p.warm]), py.randint(15, 80)))

    return finish_image(ctx, img)


def finish_image(ctx: RenderContext, img: Image.Image) -> Image.Image:
    arr = np.array(img).astype(np.int16)

    grain_strength = 4 if ctx.spec.style != "minimal" else 2
    grain = ctx.rng.normal(0, grain_strength, arr.shape).astype(np.int16)
    arr[:, :, :3] += grain[:, :, :3]
    arr = np.clip(arr, 0, 255).astype(np.uint8)

    img = Image.fromarray(arr, "RGBA")

    # Vignette.
    yy, xx = np.mgrid[0:ctx.h, 0:ctx.w]
    dx = (xx - ctx.w / 2) / (ctx.w / 2)
    dy = (yy - ctx.h / 2) / (ctx.h / 2)
    dist = np.sqrt(dx * dx + dy * dy)

    vignette = clamp01((dist - 0.38) / 0.78)
    vig_alpha = (vignette * 135).astype(np.uint8)

    vig = np.zeros((ctx.h, ctx.w, 4), dtype=np.uint8)
    vig[:, :, 3] = vig_alpha

    img.alpha_composite(Image.fromarray(vig, "RGBA"))

    img = img.filter(ImageFilter.UnsharpMask(radius=max(1.0, 1.25 * ctx.ss), percent=105, threshold=3))
    img = ImageEnhance.Contrast(img).enhance(1.05)
    img = ImageEnhance.Color(img).enhance(1.06)

    img = downsample_if_needed(img, ctx.out_w, ctx.out_h, ctx.ss)
    return img.convert("RGB")


# ============================================================
# BACKENDS
# ============================================================

class ProceduralBackend:
    def generate(self, spec: SceneSpec) -> Image.Image:
        ctx = RenderContext(spec)

        if spec.scene_type == "space":
            return render_space(ctx)

        if spec.scene_type == "cityscape":
            return render_cityscape(ctx)

        if spec.scene_type == "abstract":
            return render_abstract(ctx)

        if spec.scene_type == "poster":
            return render_poster(ctx)

        if spec.scene_type == "emblem":
            return render_emblem(ctx)

        if spec.scene_type == "product":
            return render_product(ctx)

        return render_landscape(ctx)


class DiffusionBackend:
    """
    Optional backend.

    Requires:
        pip install torch diffusers transformers accelerate safetensors

    Use a local model folder or compatible model id:
        --backend diffusion --model ./models/my_model

    This wrapper is intentionally simple.
    The procedural engine still handles query/project/spec logic.
    """

    def __init__(self, model: str, device: str = "auto"):
        if not model:
            raise ValueError("--model is required for diffusion backend")

        try:
            import torch
            from diffusers import StableDiffusionXLPipeline
        except Exception as e:
            raise RuntimeError(
                "Diffusion backend requires torch and diffusers. "
                "Install with: pip install torch diffusers transformers accelerate safetensors"
            ) from e

        self.torch = torch

        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"

        dtype = torch.float16 if device == "cuda" else torch.float32

        self.pipe = StableDiffusionXLPipeline.from_pretrained(
            model,
            torch_dtype=dtype,
            use_safetensors=True,
        )

        self.pipe.to(device)
        self.device = device

        if hasattr(self.pipe, "enable_attention_slicing"):
            self.pipe.enable_attention_slicing()

    def generate(self, spec: SceneSpec) -> Image.Image:
        generator = self.torch.Generator(device=self.device).manual_seed(spec.seed)

        prompt = (
            f"{spec.prompt}, {spec.style} style, professional composition, "
            f"rich lighting, coherent details, high quality"
        )

        image = self.pipe(
            prompt=prompt,
            negative_prompt=spec.negative_prompt,
            width=spec.width,
            height=spec.height,
            num_inference_steps=36,
            guidance_scale=7.2,
            generator=generator,
        ).images[0]

        return image.convert("RGB")


def build_backend(args):
    if args.backend == "procedural":
        return ProceduralBackend()

    if args.backend == "diffusion":
        return DiffusionBackend(args.model, args.device)

    # Auto mode uses diffusion only if a model path/id is provided.
    if args.backend == "auto" and args.model:
        try:
            return DiffusionBackend(args.model, args.device)
        except Exception as e:
            print(f"[warning] Could not load diffusion backend: {e}")
            print("[warning] Falling back to procedural backend.")

    return ProceduralBackend()


# ============================================================
# OUTPUT HELPERS
# ============================================================

def save_spec_json(spec: SceneSpec, path: Path):
    data = asdict(spec)
    data["palette"] = asdict(spec.palette)

    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def make_contact_sheet(paths: List[Path], output_path: Path, thumb_w: int = 360):
    if not paths:
        return

    images = [Image.open(p).convert("RGB") for p in paths]

    aspect = images[0].height / images[0].width
    thumb_h = int(thumb_w * aspect)

    count = len(images)
    cols = math.ceil(math.sqrt(count))
    rows = math.ceil(count / cols)

    sheet = Image.new("RGB", (cols * thumb_w, rows * thumb_h), (18, 18, 24))

    for i, img in enumerate(images):
        thumb = img.resize((thumb_w, thumb_h), RESAMPLE_LANCZOS)
        x = (i % cols) * thumb_w
        y = (i // cols) * thumb_h
        sheet.paste(thumb, (x, y))

    sheet.save(output_path, quality=95)


# ============================================================
# MAIN GENERATION
# ============================================================

def read_query(args) -> str:
    query = args.query or ""

    if args.query_file:
        qf = Path(args.query_file)
        if qf.exists():
            query += "\n" + qf.read_text(errors="ignore")

    return query.strip()


def generate_batch(args):
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    query = read_query(args)
    project = analyze_project_folder(args.project)

    interpreter = PromptInterpreter()
    backend = build_backend(args)

    saved = []

    for i in range(args.count):
        spec = interpreter.build_spec(
            query=query,
            project=project,
            args=args,
            variant=i,
        )

        image = backend.generate(spec)

        name_bits = [
            args.prefix,
            f"{i:03d}",
            spec.scene_type,
            spec.palette.name,
            f"seed{spec.seed}",
        ]

        if args.name_from_prompt:
            name_bits.insert(1, sanitize_filename(spec.title, 36))

        base_name = "_".join(name_bits)
        out_path = out_dir / f"{base_name}.png"

        image.save(out_path, quality=95)
        saved.append(out_path)

        if args.save_specs:
            save_spec_json(spec, out_dir / f"{base_name}.json")

        print(f"Saved: {out_path}")

    if args.sheet:
        sheet_path = out_dir / f"{args.prefix}_contact_sheet.png"
        make_contact_sheet(saved, sheet_path)
        print(f"Saved: {sheet_path}")


# ============================================================
# CLI
# ============================================================

def parse_args():
    parser = argparse.ArgumentParser(
        description="OmniForge procedural + optional diffusion image engine."
    )

    parser.add_argument("--query", type=str, default="", help="Text query/prompt.")
    parser.add_argument("--query-file", type=str, default="", help="Path to a text file containing a query.")
    parser.add_argument("--project", type=str, default="", help="Folder containing images/text/project references.")

    parser.add_argument("--type", type=str, default="auto", choices=[
        "auto",
        "landscape",
        "poster",
        "abstract",
        "emblem",
        "product",
        "cityscape",
        "space",
    ])

    parser.add_argument("--backend", type=str, default="procedural", choices=[
        "procedural",
        "diffusion",
        "auto",
    ])

    parser.add_argument("--model", type=str, default="", help="Optional local diffusion model folder or compatible model id.")
    parser.add_argument("--device", type=str, default="auto", help="auto, cuda, cpu, etc.")

    parser.add_argument("--negative", type=str, default="", help="Negative prompt for diffusion backend.")
    parser.add_argument("--title", type=str, default="", help="Optional title for poster/product/emblem outputs.")

    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--seed", type=int, default=77)

    parser.add_argument("--width", type=int, default=1400)
    parser.add_argument("--height", type=int, default=900)
    parser.add_argument("--supersample", type=int, default=1)

    parser.add_argument("--out", type=str, default="renders")
    parser.add_argument("--prefix", type=str, default="omniforge")

    parser.add_argument("--sheet", action="store_true")
    parser.add_argument("--save-specs", action="store_true")
    parser.add_argument("--name-from-prompt", action="store_true")

    args = parser.parse_args()

    if args.count < 1:
        raise ValueError("--count must be at least 1")

    if args.width % 8 != 0 or args.height % 8 != 0:
        print("[warning] Width and height are usually best when divisible by 8.")

    return args


if __name__ == "__main__":
    generate_batch(parse_args())
