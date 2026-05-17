
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import random
import re
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Literal

from eli.tools.image_engine.runtime_paths import image_outputs_dir, image_logs_dir
try:
    import numpy as np
except ImportError:
    np = None  # type: ignore[assignment]

try:
    from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont
except ImportError:
    Image = ImageDraw = ImageEnhance = ImageFilter = ImageFont = None  # type: ignore[assignment]


Color = tuple[int, int, int]
RGBA = tuple[int, int, int, int]
SceneName = Literal["auto", "landscape", "poster", "abstract", "emblem", "product", "cityscape", "space"]

try:
    RESAMPLE = Image.Resampling.LANCZOS
except AttributeError:  # pragma: no cover
    RESAMPLE = Image.LANCZOS


# -----------------------------------------------------------------------------
# Paths and logging
# -----------------------------------------------------------------------------

def package_root() -> Path:
    """Return the image-engine tool root.

    Expected layout:
        image_engine/
            assets/
            image_engine/
            logs/
            outputs/
            presets/
            projects/
    """
    return Path(__file__).resolve().parents[1]


def resolve_tool_path(value: str | Path | None, default_subdir: str) -> Path:
    root = package_root()
    if value:
        p = Path(value).expanduser()
        return p if p.is_absolute() else (Path.cwd() / p).resolve()
    return (root / default_subdir).resolve()


def configure_logging(log_dir: Path, verbose: bool = False) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    level = logging.DEBUG if verbose else logging.INFO
    handlers: list[logging.Handler] = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_dir / "image_engine.log", encoding="utf-8"),
    ]
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=handlers,
        force=True,
    )


# -----------------------------------------------------------------------------
# General helpers
# -----------------------------------------------------------------------------

def clamp(x: float | int, lo: int = 0, hi: int = 255) -> int:
    return int(max(lo, min(hi, x)))


def clamp01(x: np.ndarray | float) -> np.ndarray | float:
    return np.clip(x, 0.0, 1.0)


def smoothstep(x: np.ndarray | float) -> np.ndarray | float:
    return x * x * (3.0 - 2.0 * x)


def lerp(a: Any, b: Any, t: Any) -> Any:
    return a + (b - a) * t


def mix(a: Color, b: Color, t: float) -> Color:
    return (
        clamp(a[0] + (b[0] - a[0]) * t),
        clamp(a[1] + (b[1] - a[1]) * t),
        clamp(a[2] + (b[2] - a[2]) * t),
    )


def rgba(color: Color, alpha: int | float) -> RGBA:
    return color[0], color[1], color[2], clamp(alpha)


def lighten(color: Color, amount: float) -> Color:
    return mix(color, (255, 255, 255), amount)


def darken(color: Color, amount: float) -> Color:
    return mix(color, (0, 0, 0), amount)


def luminance(color: Color) -> float:
    return 0.2126 * color[0] + 0.7152 * color[1] + 0.0722 * color[2]


def saturation_span(color: Color) -> int:
    return max(color) - min(color)


def sanitize_filename(text: str, max_len: int = 72) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9_\- ]+", "", text)
    text = re.sub(r"\s+", "_", text).strip("_")
    return text[:max_len] or "image"


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z0-9']+", text.lower())


STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "with", "in", "on", "at", "to", "for",
    "from", "by", "as", "is", "are", "be", "this", "that", "these", "those",
    "image", "picture", "art", "make", "create", "generate", "design", "show",
    "style", "high", "quality", "detailed", "ultra", "beautiful", "render",
}


def title_from_prompt(prompt: str, fallback: str = "Generated Image") -> str:
    words = [w for w in tokenize(prompt) if w not in STOPWORDS and len(w) > 2]
    if not words:
        return fallback
    ranked = Counter(words).most_common(5)
    return " ".join(word.capitalize() for word, _ in ranked[:3])


def get_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except Exception:
            continue
    return ImageFont.load_default()


# -----------------------------------------------------------------------------
# Palette system
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class Palette:
    name: str
    dark: Color
    mid: Color
    primary: Color
    accent: Color
    light: Color
    warm: Color

    def as_list(self) -> list[Color]:
        return [self.dark, self.mid, self.primary, self.accent, self.light, self.warm]


PALETTES: dict[str, Palette] = {
    "violet_dusk": Palette("violet_dusk", (20, 23, 49), (69, 65, 112), (116, 102, 148), (239, 171, 125), (255, 232, 190), (255, 203, 129)),
    "emerald_aurora": Palette("emerald_aurora", (7, 31, 38), (23, 82, 76), (49, 148, 119), (126, 255, 200), (231, 255, 221), (201, 255, 169)),
    "crimson_sunset": Palette("crimson_sunset", (43, 16, 48), (103, 42, 75), (178, 65, 94), (255, 157, 88), (255, 230, 177), (255, 192, 103)),
    "blue_dawn": Palette("blue_dawn", (13, 35, 72), (50, 92, 139), (92, 153, 193), (229, 219, 176), (246, 252, 255), (255, 238, 178)),
    "golden_storm": Palette("golden_storm", (31, 32, 45), (81, 73, 70), (136, 107, 76), (241, 177, 94), (255, 236, 180), (255, 199, 91)),
    "neon_noir": Palette("neon_noir", (8, 8, 18), (25, 18, 54), (67, 41, 122), (255, 40, 168), (180, 255, 252), (255, 211, 91)),
    "monochrome_luxury": Palette("monochrome_luxury", (12, 12, 14), (48, 46, 43), (104, 99, 91), (212, 176, 91), (245, 238, 221), (255, 214, 132)),
    "solar_glass": Palette("solar_glass", (18, 20, 26), (55, 67, 86), (106, 153, 181), (255, 196, 92), (245, 248, 235), (255, 221, 139)),
    "rose_steel": Palette("rose_steel", (18, 16, 22), (61, 60, 72), (116, 116, 136), (238, 104, 135), (245, 231, 231), (255, 179, 135)),
}


def palette_from_project_colors(colors: list[Color], name: str = "project_palette") -> Palette:
    if len(colors) < 3:
        return PALETTES["violet_dusk"]

    ranked = sorted(colors, key=luminance)
    dark = darken(ranked[0], 0.24)
    light = lighten(ranked[-1], 0.18)
    accent = max(ranked, key=saturation_span)
    primary = ranked[len(ranked) // 2]
    mid = mix(dark, primary, 0.62)
    warm = mix(accent, light, 0.35)
    return Palette(name, dark, mid, primary, accent, light, warm)


def choose_palette(text: str, seed: int, preferred: str = "auto", project_colors: list[Color] | None = None) -> Palette:
    if preferred != "auto":
        if preferred not in PALETTES:
            raise ValueError(f"Unknown palette: {preferred}. Choose from: {', '.join(sorted(PALETTES))}")
        return PALETTES[preferred]

    if project_colors and len(project_colors) >= 3:
        return palette_from_project_colors(project_colors)

    t = text.lower()
    rules: list[tuple[str, Iterable[str]]] = [
        ("neon_noir", ("neon", "cyber", "synth", "nightclub", "glow", "electric")),
        ("monochrome_luxury", ("gold", "luxury", "premium", "royal", "elegant", "black tie")),
        ("emerald_aurora", ("emerald", "forest", "aurora", "green", "nature", "botanical")),
        ("crimson_sunset", ("crimson", "red", "sunset", "fire", "volcanic", "ember")),
        ("blue_dawn", ("blue", "ocean", "dawn", "ice", "sky", "arctic")),
        ("solar_glass", ("solar", "glass", "clean", "bright", "minimal")),
        ("rose_steel", ("rose", "steel", "fashion", "editorial")),
    ]
    for palette_name, words in rules:
        if any(word in t for word in words):
            return PALETTES[palette_name]

    names = sorted(PALETTES)
    return PALETTES[names[abs(seed) % len(names)]]


# -----------------------------------------------------------------------------
# Project scan
# -----------------------------------------------------------------------------

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
TEXT_EXTS = {".txt", ".md", ".json", ".csv", ".yaml", ".yml", ".toml"}


@dataclass
class ProjectContext:
    text: str
    tags: list[str]
    colors: list[Color]
    files: list[str]


def dominant_colors_from_image(path: Path, max_colors: int = 6) -> list[Color]:
    try:
        with Image.open(path) as source:
            image = source.convert("RGBA")
            backing = Image.new("RGBA", image.size, (255, 255, 255, 255))
            backing.alpha_composite(image)
            rgb = backing.convert("RGB")
            rgb.thumbnail((128, 128), RESAMPLE)
            quantized = rgb.quantize(colors=max_colors, method=Image.Quantize.MEDIANCUT)
            palette = quantized.getpalette() or []
            counts = quantized.getcolors(maxcolors=128 * 128) or []
    except Exception as exc:
        logging.debug("Skipping image color scan for %s: %s", path, exc)
        return []

    counts.sort(reverse=True)
    colors: list[Color] = []
    for _, idx in counts[:max_colors]:
        base = int(idx) * 3
        sample = palette[base:base + 3]
        if len(sample) == 3:
            colors.append((int(sample[0]), int(sample[1]), int(sample[2])))
    return colors


def analyze_project_folder(path: str | Path | None, *, max_files: int = 350, max_text_chars: int = 80_000) -> ProjectContext:
    if not path:
        return ProjectContext(text="", tags=[], colors=[], files=[])

    root = Path(path).expanduser()
    if not root.exists():
        raise FileNotFoundError(f"Project folder does not exist: {root}")

    files: list[str] = []
    text_chunks: list[str] = []
    tags: list[str] = []
    colors: list[Color] = []
    scanned = 0
    text_budget = max_text_chars

    for p in root.rglob("*"):
        if scanned >= max_files:
            break
        if not p.is_file():
            continue

        scanned += 1
        files.append(str(p))
        suffix = p.suffix.lower()
        tags.extend(tokenize(p.stem.replace("_", " ").replace("-", " ")))

        if suffix in TEXT_EXTS and text_budget > 0:
            try:
                chunk = p.read_text(errors="ignore")[:min(10_000, text_budget)]
                text_chunks.append(chunk)
                text_budget -= len(chunk)
            except Exception as exc:
                logging.debug("Skipping text scan for %s: %s", p, exc)
        elif suffix in IMAGE_EXTS:
            colors.extend(dominant_colors_from_image(p, max_colors=5))

    clean_tags = [t for t in tags if t not in STOPWORDS and len(t) > 2]
    common_tags = [tag for tag, _ in Counter(clean_tags).most_common(120)]
    common_colors = [color for color, _ in Counter(colors).most_common(14)]

    return ProjectContext(
        text="\n".join(text_chunks),
        tags=common_tags,
        colors=common_colors,
        files=files,
    )


# -----------------------------------------------------------------------------
# Scene model
# -----------------------------------------------------------------------------

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
    project_tags: list[str]
    output_format: str


SCENE_KEYWORDS: dict[str, set[str]] = {
    "landscape": {"landscape", "world", "mountain", "lake", "island", "forest", "castle", "terrain", "fantasy", "waterfall", "valley", "sky", "horizon", "nature", "garden", "cliff"},
    "poster": {"poster", "cover", "album", "movie", "flyer", "advertisement", "print", "campaign", "editorial", "magazine", "banner"},
    "abstract": {"abstract", "pattern", "generative", "fractal", "flow", "texture", "wallpaper", "motion", "chaos", "waves", "gradient"},
    "emblem": {"logo", "emblem", "badge", "crest", "icon", "seal", "symbol", "mark", "insignia"},
    "product": {"product", "bottle", "perfume", "package", "box", "cosmetic", "luxury", "label", "mockup", "container"},
    "cityscape": {"city", "street", "skyline", "urban", "tower", "skyscraper", "metropolis", "cyberpunk", "building", "neon", "downtown"},
    "space": {"space", "planet", "galaxy", "nebula", "star", "cosmos", "moon", "asteroid", "spaceship", "orbit"},
}


def infer_scene_type(text: str, forced: str = "auto") -> str:
    if forced != "auto":
        return forced
    words = set(tokenize(text))
    scores = {name: len(words & keys) for name, keys in SCENE_KEYWORDS.items()}
    best_name, best_score = max(scores.items(), key=lambda item: item[1])
    if best_score <= 0:
        return "poster" if {"brand", "campaign", "sale", "launch"} & words else "landscape"
    return best_name


def infer_style(text: str) -> str:
    t = text.lower()
    if any(word in t for word in ("cinematic", "film", "epic", "dramatic")):
        return "cinematic"
    if any(word in t for word in ("minimal", "clean", "simple", "modern")):
        return "minimal"
    if any(word in t for word in ("luxury", "premium", "elegant")):
        return "luxury"
    if any(word in t for word in ("neon", "cyber", "futuristic")):
        return "neon"
    if any(word in t for word in ("fantasy", "magic", "mythic")):
        return "fantasy"
    return "balanced"


class PromptInterpreter:
    def build(self, query: str, project: ProjectContext, args: argparse.Namespace, variant: int) -> SceneSpec:
        combined = " ".join([query or "", project.text or "", " ".join(project.tags[:60])]).strip()
        if not combined:
            combined = "cinematic atmospheric landscape with soft light and crisp composition"

        seed = int(args.seed) + variant * 7919
        palette = choose_palette(
            combined,
            seed,
            preferred=args.palette,
            project_colors=project.colors,
        )
        scene_type = infer_scene_type(combined, forced=args.type)
        style = args.style if args.style != "auto" else infer_style(combined)

        return SceneSpec(
            prompt=combined,
            negative_prompt=args.negative or "low quality, cluttered composition, unreadable text, malformed detail",
            scene_type=scene_type,
            style=style,
            title=args.title or title_from_prompt(combined),
            width=args.width,
            height=args.height,
            seed=seed,
            variant=variant,
            supersample=max(1, args.supersample),
            palette=palette,
            project_tags=project.tags[:60],
            output_format=args.format.lower(),
        )


# -----------------------------------------------------------------------------
# Noise and image helpers
# -----------------------------------------------------------------------------

def value_noise(width: int, height: int, cells_x: int, cells_y: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    cells_x = max(1, int(cells_x))
    cells_y = max(1, int(cells_y))
    grid = rng.random((cells_y + 1, cells_x + 1), dtype=np.float32)

    xs = np.linspace(0, cells_x, width, endpoint=False)
    ys = np.linspace(0, cells_y, height, endpoint=False)
    xi = np.floor(xs).astype(np.int32)
    yi = np.floor(ys).astype(np.int32)
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

    return lerp(lerp(n00, n10, sx), lerp(n01, n11, sx), sy).astype(np.float32)


def fbm(width: int, height: int, seed: int, *, octaves: int = 6, persistence: float = 0.52, base_cells_x: int = 2, base_cells_y: int | None = None) -> np.ndarray:
    if base_cells_y is None:
        base_cells_y = max(1, int(base_cells_x * height / max(width, 1)))

    result = np.zeros((height, width), dtype=np.float32)
    amp = 1.0
    total = 0.0

    for octave in range(max(1, octaves)):
        scale = 2 ** octave
        result += value_noise(
            width,
            height,
            base_cells_x * scale,
            max(1, base_cells_y * scale),
            seed + octave * 997,
        ) * amp
        total += amp
        amp *= persistence

    return result / max(total, 1e-8)


def warped_fbm(width: int, height: int, seed: int, *, strength: float = 48.0, octaves: int = 6, base_cells: int = 2) -> np.ndarray:
    wx = fbm(width, height, seed + 101, octaves=4, base_cells_x=base_cells)
    wy = fbm(width, height, seed + 211, octaves=4, base_cells_x=base_cells)
    detail = fbm(width, height, seed + 307, octaves=octaves, base_cells_x=base_cells)

    yy, xx = np.mgrid[0:height, 0:width]
    sx = np.clip(xx + (wx - 0.5) * strength, 0, width - 1).astype(np.int32)
    sy = np.clip(yy + (wy - 0.5) * strength, 0, height - 1).astype(np.int32)
    return detail[sy, sx]


def vertical_gradient(width: int, height: int, top: Color, mid: Color, bottom: Color, mid_at: float = 0.55) -> Image.Image:
    rows = np.zeros((height, width, 3), dtype=np.uint8)
    top_f = np.asarray(top, dtype=np.float32)
    mid_f = np.asarray(mid, dtype=np.float32)
    bot_f = np.asarray(bottom, dtype=np.float32)

    for y in range(height):
        t = y / max(1, height - 1)
        if t < mid_at:
            k = t / max(mid_at, 1e-6)
            c = lerp(top_f, mid_f, k)
        else:
            k = (t - mid_at) / max(1.0 - mid_at, 1e-6)
            c = lerp(mid_f, bot_f, k)
        rows[y, :, :] = np.clip(c, 0, 255)
    return Image.fromarray(rows, "RGB")


def add_radial_glow(img: Image.Image, center: tuple[int, int], color: Color, radius: int, strength: int, squash_y: float = 1.0) -> None:
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer, "RGBA")
    step = max(4, radius // 52)
    for r in range(radius, 0, -step):
        alpha = int(strength * (r / max(radius, 1)) ** 2)
        ry = int(r * squash_y)
        draw.ellipse(
            [center[0] - r, center[1] - ry, center[0] + r, center[1] + ry],
            fill=rgba(color, alpha),
        )
    img.alpha_composite(layer)


def draw_wrapped_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    xy: tuple[int, int],
    max_width: int,
    fill: RGBA,
    font: ImageFont.ImageFont,
    *,
    line_spacing: int = 6,
    align: str = "center",
) -> None:
    words = text.split()
    lines: list[str] = []
    line = ""

    for word in words:
        trial = word if not line else f"{line} {word}"
        try:
            box = draw.textbbox((0, 0), trial, font=font)
            width = box[2] - box[0]
        except Exception:
            width = len(trial) * 8

        if width <= max_width or not line:
            line = trial
        else:
            lines.append(line)
            line = word

    if line:
        lines.append(line)

    x, y = xy
    for line in lines:
        try:
            box = draw.textbbox((0, 0), line, font=font)
            tw = box[2] - box[0]
            th = box[3] - box[1]
        except Exception:
            tw, th = len(line) * 8, 14

        if align == "right":
            tx = x - tw
        elif align == "left":
            tx = x
        else:
            tx = x - tw // 2

        draw.text((tx, y), line, font=font, fill=fill)
        y += th + line_spacing


def resize_final(img: Image.Image, width: int, height: int, supersample: int) -> Image.Image:
    if supersample > 1:
        img = img.resize((width, height), RESAMPLE)
    return img.convert("RGB")


@dataclass
class RenderContext:
    spec: SceneSpec

    def __post_init__(self) -> None:
        self.ss = max(1, self.spec.supersample)
        self.out_w = self.spec.width
        self.out_h = self.spec.height
        self.w = self.out_w * self.ss
        self.h = self.out_h * self.ss
        self.seed = self.spec.seed
        self.rng = np.random.default_rng(self.seed)
        self.random = random.Random(self.seed)
        self.palette = self.spec.palette
        self.tokens = set(tokenize(self.spec.prompt))

    def scale(self, value: float) -> int:
        return max(1, int(value * self.ss))


def finish_image(ctx: RenderContext, img: Image.Image) -> Image.Image:
    arr = np.asarray(img.convert("RGBA")).astype(np.int16)
    grain_strength = 2 if ctx.spec.style == "minimal" else 4
    grain = ctx.rng.normal(0, grain_strength, arr.shape).astype(np.int16)
    arr[:, :, :3] += grain[:, :, :3]
    arr = np.clip(arr, 0, 255).astype(np.uint8)
    img = Image.fromarray(arr, "RGBA")

    yy, xx = np.mgrid[0:ctx.h, 0:ctx.w]
    dx = (xx - ctx.w / 2) / max(ctx.w / 2, 1)
    dy = (yy - ctx.h / 2) / max(ctx.h / 2, 1)
    distance = np.sqrt(dx * dx + dy * dy)
    vignette = clamp01((distance - 0.40) / 0.72)
    layer = np.zeros((ctx.h, ctx.w, 4), dtype=np.uint8)
    layer[:, :, 3] = (vignette * 125).astype(np.uint8)
    img.alpha_composite(Image.fromarray(layer, "RGBA"))

    img = img.filter(ImageFilter.UnsharpMask(radius=max(1.0, 1.1 * ctx.ss), percent=105, threshold=3))
    img = ImageEnhance.Contrast(img).enhance(1.05)
    img = ImageEnhance.Color(img).enhance(1.06)
    return resize_final(img, ctx.out_w, ctx.out_h, ctx.ss)


# -----------------------------------------------------------------------------
# Procedural renderers
# -----------------------------------------------------------------------------

def render_landscape(ctx: RenderContext) -> Image.Image:
    w, h, p, rng, py = ctx.w, ctx.h, ctx.palette, ctx.rng, ctx.random
    horizon = int(h * rng.uniform(0.52, 0.62))
    sun = (int(w * rng.uniform(0.18, 0.82)), int(h * rng.uniform(0.13, 0.31)))

    img = vertical_gradient(w, h, p.dark, mix(p.mid, p.primary, 0.44), mix(p.accent, p.light, 0.22), 0.62).convert("RGBA")
    add_radial_glow(img, sun, p.warm, int(min(w, h) * 0.44), 24)

    draw = ImageDraw.Draw(img, "RGBA")
    sun_r = int(w * rng.uniform(0.018, 0.042))
    draw.ellipse([sun[0] - sun_r, sun[1] - sun_r, sun[0] + sun_r, sun[1] + sun_r], fill=rgba(p.light, 235))
    draw.ellipse([sun[0] - sun_r // 2, sun[1] - sun_r // 2, sun[0] + sun_r // 2, sun[1] + sun_r // 2], fill=rgba((255, 255, 245), 250))

    clouds = warped_fbm(w, h, ctx.seed + 301, strength=w * 0.045, octaves=7, base_cells=2)
    y = np.arange(h)[:, None]
    sky_fade = clamp01((horizon - y) / (h * 0.45))
    top_fade = np.linspace(1.0, 0.0, h)[:, None]
    cloud_mask = clamp01((clouds * sky_fade * top_fade - 0.20) * 3.4)
    cloud_arr = np.zeros((h, w, 4), dtype=np.uint8)
    cc = mix(p.light, p.accent, 0.25)
    cloud_arr[:, :, 0], cloud_arr[:, :, 1], cloud_arr[:, :, 2] = cc
    cloud_arr[:, :, 3] = (cloud_mask * 116).astype(np.uint8)
    img.alpha_composite(Image.fromarray(cloud_arr, "RGBA").filter(ImageFilter.GaussianBlur(ctx.scale(5))))

    for layer_idx in range(3):
        base_y = int(horizon + h * (layer_idx * 0.065 - 0.025))
        amp = int(h * (0.15 + layer_idx * 0.035) * rng.uniform(0.82, 1.20))
        points = 10 + layer_idx * 4
        xs = np.linspace(0, w - 1, points)
        ys = np.array([base_y - py.random() * amp for _ in range(points)])
        ridge = np.interp(np.arange(w), xs, ys)
        ridge += np.sin(np.linspace(0, math.pi * (2.4 + layer_idx), w)) * amp * 0.10

        layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer, "RGBA")
        color = darken(mix(p.mid, p.dark, 0.25 + layer_idx * 0.16), 0.04)
        poly = [(0, h)] + [(x, int(ridge[x])) for x in range(w)] + [(w, h)]
        ld.polygon(poly, fill=rgba(color, 132 + layer_idx * 40))

        for x in range(0, w, ctx.scale(4)):
            yy = int(ridge[x])
            ld.line([(x, yy), (x + ctx.scale(3), yy + ctx.scale(2))], fill=rgba(p.light, 20 + layer_idx * 7), width=ctx.scale(1))

        img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(ctx.scale(max(0.6, 2.8 - layer_idx)))))

    # Reflection / foreground water.
    water_h = h - horizon
    reflection = img.crop((0, 0, w, horizon)).transpose(Image.FLIP_TOP_BOTTOM).resize((w, water_h), RESAMPLE)
    refl = np.asarray(reflection).astype(np.float32)
    ripple = value_noise(w, water_h, 24, 9, ctx.seed + 808)
    for yy in range(water_h):
        shift = int(math.sin(yy * 0.045 / ctx.ss) * 7 * ctx.ss + math.sin(yy * 0.013 / ctx.ss + 2.4) * 12 * ctx.ss + (ripple[yy, w // 2] - 0.5) * 18 * ctx.ss)
        refl[yy] = np.roll(refl[yy], shift, axis=0)

    water_grad = np.asarray(vertical_gradient(w, water_h, mix(p.mid, p.primary, 0.35), mix(p.dark, p.primary, 0.35), darken(p.dark, 0.15), 0.45).convert("RGBA")).astype(np.float32)
    depth = np.linspace(0.72, 0.22, water_h)[:, None, None]
    water = refl * depth + water_grad * (1.0 - depth)
    water[:, :, 3] = 255
    water_img = Image.fromarray(np.clip(water, 0, 255).astype(np.uint8), "RGBA")
    wd = ImageDraw.Draw(water_img, "RGBA")
    shimmer_count = max(24, int(150 * w * h / (1400 * 900 * ctx.ss * ctx.ss)))
    for _ in range(shimmer_count):
        yy = py.randint(5, max(6, water_h - 8))
        xx = py.randint(0, w)
        length = py.randint(ctx.scale(30), ctx.scale(190))
        wd.line([(xx, yy), (min(w, xx + length), yy)], fill=rgba(p.light, py.randint(10, 44)), width=ctx.scale(1))
    img.alpha_composite(water_img, (0, horizon))

    if "island" in ctx.tokens or "fantasy" in ctx.tokens or py.random() < 0.84:
        _draw_floating_island(ctx, img)

    particle_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    pd = ImageDraw.Draw(particle_layer, "RGBA")
    for _ in range(380):
        x, yy = py.randint(0, w), py.randint(0, h)
        r = py.choice([1, 1, 1, 2, 2, 3]) * ctx.ss
        dist = math.dist((x, yy), sun)
        bonus = max(0.0, 1.0 - dist / max(650 * ctx.ss, 1))
        pd.ellipse([x - r, yy - r, x + r, yy + r], fill=rgba(p.light, int(py.randint(10, 68) * (0.45 + bonus))))
    for _ in range(py.randint(5, 22)):
        x = py.randint(0, w)
        yy = py.randint(int(h * 0.11), max(int(h * 0.12), horizon - int(h * 0.07)))
        size = py.randint(ctx.scale(5), ctx.scale(17))
        pd.line([(x - size, yy), (x, yy - size // 2), (x + size, yy)], fill=rgba(p.dark, py.randint(70, 135)), width=ctx.scale(1))
    img.alpha_composite(particle_layer.filter(ImageFilter.GaussianBlur(max(0.4, ctx.ss * 0.4))))

    return finish_image(ctx, img)


def _draw_floating_island(ctx: RenderContext, img: Image.Image) -> None:
    w, h, p, rng, py = ctx.w, ctx.h, ctx.palette, ctx.rng, ctx.random
    cx = int(w * rng.uniform(0.42, 0.58))
    cy = int(h * rng.uniform(0.43, 0.53))
    top_width = int(w * rng.uniform(0.27, 0.38))

    island = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(island, "RGBA")
    top_points: list[tuple[int, int]] = []
    for i in range(28):
        t = i / 27
        x = cx - top_width // 2 + int(t * top_width)
        wobble = math.sin(t * math.pi * 6) * ctx.scale(12) + py.randint(-ctx.scale(8), ctx.scale(8))
        top_points.append((x, cy + int(wobble)))

    bottom_tip = (cx + ctx.scale(10), cy + int(h * 0.28))
    stone_poly = top_points + [
        (cx + int(top_width * 0.47), cy + int(h * 0.06)),
        (cx + int(top_width * 0.27), cy + int(h * 0.18)),
        bottom_tip,
        (cx - int(top_width * 0.27), cy + int(h * 0.18)),
        (cx - int(top_width * 0.47), cy + int(h * 0.06)),
    ]
    draw.polygon(stone_poly, fill=rgba(darken(p.mid, 0.18), 255))

    for _ in range(110):
        x1 = py.randint(cx - int(top_width * 0.44), cx + int(top_width * 0.44))
        y1 = py.randint(cy + ctx.scale(16), cy + int(h * 0.23))
        x2 = x1 + py.randint(-ctx.scale(40), ctx.scale(40))
        y2 = y1 + py.randint(ctx.scale(12), ctx.scale(48))
        draw.line([(x1, y1), (x2, y2)], fill=rgba(darken(p.dark, 0.05), py.randint(35, 95)), width=py.randint(1, max(2, ctx.scale(3))))

    grass_poly = top_points + [(cx + top_width // 2 - ctx.scale(20), cy + ctx.scale(42)), (cx - top_width // 2 + ctx.scale(20), cy + ctx.scale(42))]
    draw.polygon(grass_poly, fill=rgba(mix(p.primary, p.accent, 0.18), 255))

    for x, y in top_points[::2]:
        draw.line([(x - ctx.scale(8), y - ctx.scale(1)), (x + ctx.scale(10), y - ctx.scale(4))], fill=rgba(lighten(p.primary, 0.35), 235), width=ctx.scale(2))

    for _ in range(32):
        sx = py.randint(cx - int(top_width * 0.41), cx + int(top_width * 0.41))
        sy = cy + py.randint(ctx.scale(25), ctx.scale(55))
        length = py.randint(ctx.scale(45), ctx.scale(155))
        pts = [(sx + py.randint(-ctx.scale(16), ctx.scale(16)), sy + int(length * j / 5)) for j in range(6)]
        draw.line(pts, fill=(45, 30, 25, 170), width=py.randint(1, max(2, ctx.scale(3))))

    for _ in range(py.randint(8, 15)):
        x = py.randint(cx - int(top_width * 0.36), cx + int(top_width * 0.36))
        y = cy + py.randint(-ctx.scale(18), ctx.scale(12))
        ch = py.randint(ctx.scale(40), ctx.scale(105))
        cw = py.randint(ctx.scale(16), ctx.scale(34))
        color = py.choice([p.accent, p.light, p.warm])
        crystal = [(x, y - ch), (x + cw // 2, y - ch // 3), (x + cw // 3, y + ctx.scale(10)), (x - cw // 3, y + ctx.scale(10)), (x - cw // 2, y - ch // 3)]
        draw.polygon(crystal, fill=rgba(color, 175), outline=rgba(p.light, 130))
        draw.line([(x, y - ch), (x, y + ctx.scale(6))], fill=rgba((255, 255, 255), 95), width=ctx.scale(1))

    for _ in range(py.randint(12, 22)):
        x = py.randint(cx - int(top_width * 0.40), cx + int(top_width * 0.40))
        y = cy + py.randint(-ctx.scale(25), ctx.scale(8))
        trunk_h = py.randint(ctx.scale(25), ctx.scale(46))
        draw.line([(x, y), (x + py.randint(-ctx.scale(5), ctx.scale(5)), y - trunk_h)], fill=(54, 34, 26, 255), width=py.randint(max(2, ctx.scale(3)), max(3, ctx.scale(5))))
        for _ in range(7):
            ox = py.randint(-ctx.scale(18), ctx.scale(18))
            oy = py.randint(-ctx.scale(16), ctx.scale(12))
            r = py.randint(ctx.scale(9), ctx.scale(18))
            leaf = mix(p.primary, p.light, py.random() * 0.25)
            draw.ellipse([x + ox - r, y - trunk_h + oy - r, x + ox + r, y - trunk_h + oy + r], fill=rgba(leaf, 230))

    if {"castle", "tower", "temple", "city"} & ctx.tokens:
        bx = cx - ctx.scale(45)
        by = cy - ctx.scale(55)
        building_c = rgba(darken(p.dark, 0.02), 220)
        draw.rectangle([bx, by, bx + ctx.scale(90), cy], fill=building_c)
        for tx in [bx, bx + ctx.scale(35), bx + ctx.scale(70)]:
            draw.rectangle([tx, by - ctx.scale(45), tx + ctx.scale(20), cy], fill=building_c)
            draw.polygon([(tx - ctx.scale(5), by - ctx.scale(45)), (tx + ctx.scale(10), by - ctx.scale(70)), (tx + ctx.scale(25), by - ctx.scale(45))], fill=rgba(p.accent, 200))

    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow, "RGBA")
    max_r = int(w * 0.14)
    for r in range(max_r, 0, ctx.scale(-10)):
        gd.ellipse([cx - r, cy + ctx.scale(120) - r // 2, cx + r, cy + ctx.scale(120) + r // 2], fill=rgba(p.accent, int(38 * (r / max(max_r, 1)) ** 2)))
    img.alpha_composite(glow)
    img.alpha_composite(island)


def render_space(ctx: RenderContext) -> Image.Image:
    w, h, p, py = ctx.w, ctx.h, ctx.palette, ctx.random
    img = vertical_gradient(w, h, darken(p.dark, 0.25), p.dark, darken(p.mid, 0.20), 0.55).convert("RGBA")
    nebula = clamp01((warped_fbm(w, h, ctx.seed + 444, strength=w * 0.08, octaves=7, base_cells=2) - 0.30) * 2.4)

    arr = np.zeros((h, w, 4), dtype=np.uint8)
    c1, c2 = np.asarray(p.primary), np.asarray(p.accent)
    color = c1[None, None, :] * (1 - nebula[:, :, None]) + c2[None, None, :] * nebula[:, :, None]
    arr[:, :, :3] = np.clip(color, 0, 255).astype(np.uint8)
    arr[:, :, 3] = (nebula * 116).astype(np.uint8)
    img.alpha_composite(Image.fromarray(arr, "RGBA").filter(ImageFilter.GaussianBlur(ctx.scale(4))))

    draw = ImageDraw.Draw(img, "RGBA")
    for _ in range(max(200, int(1150 * w * h / (1400 * 900 * ctx.ss * ctx.ss)))):
        x, y = py.randint(0, w), py.randint(0, h)
        r = py.choice([1, 1, 1, 2]) * ctx.ss
        draw.ellipse([x - r, y - r, x + r, y + r], fill=rgba(p.light, py.randint(75, 240)))

    planet_count = 1 if "planet" in ctx.tokens else py.randint(1, 3)
    for _ in range(planet_count):
        cx = py.randint(int(w * 0.18), int(w * 0.85))
        cy = py.randint(int(h * 0.18), int(h * 0.70))
        r = py.randint(int(min(w, h) * 0.055), int(min(w, h) * 0.16))
        add_radial_glow(img, (cx, cy), p.accent, r * 4, 20)

        planet = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        pd = ImageDraw.Draw(planet, "RGBA")
        pd.ellipse([cx - r, cy - r, cx + r, cy + r], fill=rgba(mix(p.primary, p.light, 0.25), 255))
        shadow_offset = int(r * 0.35)
        pd.ellipse([cx - r + shadow_offset, cy - r, cx + r + shadow_offset, cy + r], fill=rgba(darken(p.dark, 0.10), 145))
        for i in range(8):
            yy = cy - r + int((2 * r) * i / 8)
            pd.arc([cx - r, yy - r // 3, cx + r, yy + r // 3], 0, 180, fill=rgba(p.light, 30), width=ctx.scale(1))
        if py.random() < 0.52 or "ring" in ctx.tokens:
            pd.ellipse([cx - int(r * 1.8), cy - int(r * 0.45), cx + int(r * 1.8), cy + int(r * 0.45)], outline=rgba(p.warm, 120), width=ctx.scale(3))
        img.alpha_composite(planet)

    return finish_image(ctx, img)


def render_cityscape(ctx: RenderContext) -> Image.Image:
    w, h, p, py, rng = ctx.w, ctx.h, ctx.palette, ctx.random, ctx.rng
    horizon = int(h * rng.uniform(0.53, 0.68))
    img = vertical_gradient(w, h, p.dark, p.mid, mix(p.primary, p.accent, 0.30), 0.55).convert("RGBA")
    sun = (int(w * rng.uniform(0.15, 0.85)), int(h * rng.uniform(0.16, 0.30)))
    add_radial_glow(img, sun, p.accent, int(min(w, h) * 0.36), 26)
    draw = ImageDraw.Draw(img, "RGBA")

    x = -ctx.scale(30)
    while x < w + ctx.scale(30):
        bw = py.randint(ctx.scale(35), ctx.scale(110))
        bh = py.randint(int(h * 0.18), int(h * 0.58))
        y = horizon - bh
        c = darken(mix(p.dark, p.mid, py.random() * 0.4), py.random() * 0.12)
        draw.rectangle([x, y, x + bw, horizon + ctx.scale(10)], fill=rgba(c, 235))
        if py.random() < 0.38:
            draw.polygon([(x, y), (x + bw // 2, y - py.randint(ctx.scale(25), ctx.scale(95))), (x + bw, y)], fill=rgba(c, 235))

        win_w = max(ctx.scale(3), bw // py.randint(8, 14))
        win_h = max(ctx.scale(4), ctx.scale(8))
        for wx in range(x + ctx.scale(7), x + bw - ctx.scale(7), win_w * 2):
            for wy in range(y + ctx.scale(12), horizon - ctx.scale(10), win_h * 2):
                if py.random() < 0.50:
                    wc = p.accent if "neon" in ctx.tokens or ctx.spec.style == "neon" else p.warm
                    draw.rectangle([wx, wy, wx + win_w, wy + win_h], fill=rgba(wc, py.randint(75, 210)))
        x += bw + py.randint(ctx.scale(2), ctx.scale(8))

    if "water" in ctx.tokens or py.random() < 0.45:
        water_h = h - horizon
        refl = img.crop((0, int(h * 0.20), w, horizon)).transpose(Image.FLIP_TOP_BOTTOM).resize((w, water_h), RESAMPLE)
        arr = np.asarray(refl).astype(np.float32)
        for yy in range(water_h):
            arr[yy] = np.roll(arr[yy], int(math.sin(yy * 0.035) * 12 * ctx.ss), axis=0)
        grad = np.asarray(vertical_gradient(w, water_h, p.mid, p.dark, darken(p.dark, 0.20), 0.5).convert("RGBA")).astype(np.float32)
        depth = np.linspace(0.60, 0.18, water_h)[:, None, None]
        final = arr * depth + grad * (1 - depth)
        final[:, :, 3] = 255
        img.alpha_composite(Image.fromarray(np.clip(final, 0, 255).astype(np.uint8), "RGBA"), (0, horizon))
    else:
        draw.rectangle([0, horizon, w, h], fill=rgba(darken(p.dark, 0.15), 255))
        for i in range(16):
            yy = horizon + int((h - horizon) * i / 16)
            draw.line([(0, yy), (w, yy + ctx.scale(35))], fill=rgba(p.light, 14), width=ctx.scale(1))

    for _ in range(20):
        x = py.randint(0, w)
        y = py.randint(int(h * 0.25), horizon)
        length = py.randint(ctx.scale(18), ctx.scale(90))
        draw.line([(x, y), (x + length, y)], fill=rgba(py.choice([p.accent, p.light, p.warm]), py.randint(90, 220)), width=ctx.scale(3))

    return finish_image(ctx, img)


def render_abstract(ctx: RenderContext) -> Image.Image:
    w, h, p, py = ctx.w, ctx.h, ctx.palette, ctx.random
    img = vertical_gradient(w, h, p.dark, p.mid, p.primary, 0.55).convert("RGBA")
    noise = warped_fbm(w, h, ctx.seed + 777, strength=w * 0.10, octaves=8, base_cells=3)

    mask = clamp01((noise - 0.18) * 1.4)
    c1, c2, c3 = np.asarray(p.primary), np.asarray(p.accent), np.asarray(p.light)
    color = c1[None, None, :] * (1 - mask[:, :, None]) + c2[None, None, :] * mask[:, :, None]
    color = color * 0.75 + c3[None, None, :] * (mask[:, :, None] ** 3) * 0.25
    arr = np.zeros((h, w, 4), dtype=np.uint8)
    arr[:, :, :3] = np.clip(color, 0, 255).astype(np.uint8)
    arr[:, :, 3] = (mask * 170).astype(np.uint8)
    img.alpha_composite(Image.fromarray(arr, "RGBA").filter(ImageFilter.GaussianBlur(ctx.scale(2))))

    draw = ImageDraw.Draw(img, "RGBA")
    for _ in range(90):
        cx = py.randint(-w // 10, int(w * 1.1))
        cy = py.randint(-h // 10, int(h * 1.1))
        r = py.randint(ctx.scale(20), ctx.scale(220))
        color = py.choice([p.primary, p.accent, p.light, p.warm])
        alpha = py.randint(12, 70)
        if py.random() < 0.5:
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=rgba(color, alpha), width=py.randint(1, max(2, ctx.scale(5))))
        else:
            sides = py.randint(3, 8)
            points = []
            for i in range(sides):
                angle = math.tau * i / sides + py.random() * 0.3
                points.append((cx + int(math.cos(angle) * r), cy + int(math.sin(angle) * r)))
            draw.polygon(points, outline=rgba(color, alpha), fill=rgba(color, alpha // 4))

    for _ in range(160):
        x, y = py.randint(0, w), py.randint(0, h)
        angle = py.random() * math.tau
        pts = []
        for _ in range(28):
            pts.append((x, y))
            angle += (py.random() - 0.5) * 0.5
            x += int(math.cos(angle) * ctx.scale(12))
            y += int(math.sin(angle) * ctx.scale(12))
            if x < 0 or x >= w or y < 0 or y >= h:
                break
        if len(pts) > 1:
            draw.line(pts, fill=rgba(py.choice([p.accent, p.light, p.warm]), py.randint(20, 90)), width=ctx.scale(1))

    return finish_image(ctx, img)


def render_poster(ctx: RenderContext) -> Image.Image:
    w, h, p, py = ctx.w, ctx.h, ctx.palette, ctx.random
    img = vertical_gradient(w, h, p.dark, p.mid, mix(p.primary, p.accent, 0.25), 0.66).convert("RGBA")
    draw = ImageDraw.Draw(img, "RGBA")
    add_radial_glow(img, (int(w * 0.72), int(h * 0.26)), p.accent, int(min(w, h) * 0.42), 26)

    for _ in range(18):
        x1 = py.randint(-w // 3, w)
        y1 = py.randint(0, h)
        x2 = x1 + py.randint(ctx.scale(120), ctx.scale(520))
        y2 = y1 + py.randint(-ctx.scale(220), ctx.scale(220))
        width = py.randint(ctx.scale(12), ctx.scale(55))
        draw.line([(x1, y1), (x2, y2)], fill=rgba(py.choice([p.primary, p.accent, p.warm, p.light]), py.randint(35, 120)), width=width)

    margin = int(min(w, h) * 0.08)
    plate = [margin, margin, w - margin, h - margin]
    draw.rounded_rectangle(plate, radius=ctx.scale(36), outline=rgba(p.light, 95), width=ctx.scale(3), fill=rgba(darken(p.dark, 0.08), 90))

    cx, cy = w // 2, int(h * 0.44)
    max_r = int(min(w, h) * 0.22)
    for i in range(9):
        r = max_r - i * ctx.scale(18)
        if r <= 0:
            continue
        color = [p.accent, p.primary, p.warm, p.light][i % 4]
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=rgba(color, 155 - i * 12), width=ctx.scale(4))

    points = []
    sides = 7
    for i in range(sides):
        angle = math.tau * i / sides - math.pi / 2
        rr = max_r * (0.78 + 0.22 * math.sin(i * 2.1 + ctx.seed))
        points.append((cx + int(math.cos(angle) * rr), cy + int(math.sin(angle) * rr)))
    draw.polygon(points, fill=rgba(p.accent, 90), outline=rgba(p.light, 150))

    font_title = get_font(ctx.scale(58), bold=True)
    font_sub = get_font(ctx.scale(22), bold=False)
    subtitle = " / ".join(ctx.spec.project_tags[:5]) if ctx.spec.project_tags else f"{ctx.spec.style.upper()} GENERATED IMAGE"

    draw_wrapped_text(draw, ctx.spec.title.upper(), (w // 2, int(h * 0.70)), int(w * 0.76), rgba(p.light, 245), font_title, line_spacing=ctx.scale(8))
    draw_wrapped_text(draw, subtitle[:110], (w // 2, int(h * 0.84)), int(w * 0.70), rgba(mix(p.light, p.accent, 0.30), 180), font_sub, line_spacing=ctx.scale(5))

    return finish_image(ctx, img)


def render_emblem(ctx: RenderContext) -> Image.Image:
    w, h, p, py = ctx.w, ctx.h, ctx.palette, ctx.random
    img = vertical_gradient(w, h, darken(p.dark, 0.08), p.mid, p.dark, 0.5).convert("RGBA")
    draw = ImageDraw.Draw(img, "RGBA")
    cx, cy = w // 2, h // 2
    r = int(min(w, h) * 0.31)
    add_radial_glow(img, (cx, cy), p.accent, int(r * 1.8), 24)

    for i, color in enumerate([p.light, p.accent, p.warm, p.primary, p.light]):
        rr = r - i * ctx.scale(18)
        if rr > 0:
            draw.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], outline=rgba(color, 190 - i * 25), width=ctx.scale(3))

    crest = [
        (cx, cy - r),
        (cx + int(r * 0.70), cy - int(r * 0.35)),
        (cx + int(r * 0.56), cy + int(r * 0.56)),
        (cx, cy + r),
        (cx - int(r * 0.56), cy + int(r * 0.56)),
        (cx - int(r * 0.70), cy - int(r * 0.35)),
    ]
    draw.polygon(crest, fill=rgba(darken(p.dark, 0.05), 185), outline=rgba(p.light, 165))

    tokens = ctx.tokens
    if {"leaf", "nature", "forest", "botanical"} & tokens:
        for side in (-1, 1):
            for i in range(8):
                y = cy + int((i - 4) * r * 0.10)
                x = cx + side * int(r * 0.18)
                draw.ellipse([x, y - ctx.scale(15), x + side * int(r * 0.38), y + ctx.scale(15)], fill=rgba(p.accent, 140), outline=rgba(p.light, 120))
        draw.line([(cx, cy - int(r * 0.45)), (cx, cy + int(r * 0.50))], fill=rgba(p.light, 160), width=ctx.scale(3))
    elif {"wave", "ocean", "water"} & tokens:
        for i in range(6):
            yy = cy - int(r * 0.25) + i * int(r * 0.11)
            draw.arc([cx - int(r * 0.52), yy - int(r * 0.14), cx + int(r * 0.52), yy + int(r * 0.18)], 0, 180, fill=rgba(p.accent, 175), width=ctx.scale(4))
    elif {"star", "space", "cosmos"} & tokens:
        points = []
        for i in range(14):
            angle = math.tau * i / 14 - math.pi / 2
            rr = r * (0.50 if i % 2 == 0 else 0.20)
            points.append((cx + int(math.cos(angle) * rr), cy + int(math.sin(angle) * rr)))
        draw.polygon(points, fill=rgba(p.warm, 185), outline=rgba(p.light, 210))
    else:
        diamond = [(cx, cy - int(r * 0.55)), (cx + int(r * 0.42), cy), (cx, cy + int(r * 0.55)), (cx - int(r * 0.42), cy)]
        draw.polygon(diamond, fill=rgba(p.accent, 165), outline=rgba(p.light, 220))
        draw.line([(cx, cy - int(r * 0.55)), (cx, cy + int(r * 0.55))], fill=rgba(p.light, 125), width=ctx.scale(2))
        draw.line([(cx - int(r * 0.42), cy), (cx + int(r * 0.42), cy)], fill=rgba(p.light, 95), width=ctx.scale(2))

    font = get_font(ctx.scale(34), bold=True)
    draw_wrapped_text(draw, ctx.spec.title.upper(), (cx, cy + int(r * 1.18)), int(w * 0.70), rgba(p.light, 225), font, line_spacing=ctx.scale(5))
    return finish_image(ctx, img)


def render_product(ctx: RenderContext) -> Image.Image:
    w, h, p, py = ctx.w, ctx.h, ctx.palette, ctx.random
    img = vertical_gradient(w, h, darken(p.dark, 0.05), p.mid, darken(p.dark, 0.20), 0.55).convert("RGBA")
    add_radial_glow(img, (int(w * 0.58), int(h * 0.32)), p.accent, int(min(w, h) * 0.40), 28)
    draw = ImageDraw.Draw(img, "RGBA")

    floor_y = int(h * 0.76)
    draw.rectangle([0, floor_y, w, h], fill=rgba(darken(p.dark, 0.12), 215))
    cx, base_y = w // 2, int(h * 0.75)

    shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow, "RGBA")
    sd.ellipse([cx - int(w * 0.20), base_y - ctx.scale(20), cx + int(w * 0.20), base_y + ctx.scale(30)], fill=(0, 0, 0, 110))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(ctx.scale(18))))

    product_type = "bottle" if {"bottle", "perfume", "cosmetic"} & ctx.tokens else "box"
    if product_type == "bottle":
        bw, bh = int(w * 0.18), int(h * 0.46)
        x1, y1 = cx - bw // 2, base_y - bh
        draw.rounded_rectangle([x1, y1, x1 + bw, base_y], radius=ctx.scale(32), fill=rgba(lighten(p.dark, 0.08), 245), outline=rgba(p.light, 120), width=ctx.scale(2))
        draw.rectangle([cx - bw // 5, y1 - ctx.scale(50), cx + bw // 5, y1 + ctx.scale(15)], fill=rgba(darken(p.dark, 0.02), 245), outline=rgba(p.light, 95))
        draw.rectangle([cx - bw // 3, y1 - ctx.scale(75), cx + bw // 3, y1 - ctx.scale(45)], fill=rgba(p.accent, 220))
        lm = min(ctx.scale(18), max(2, bw // 5))
        label = [x1 + lm, y1 + int(bh * 0.44), x1 + bw - lm, y1 + int(bh * 0.72)]
        if label[2] <= label[0]:
            label[0], label[2] = x1 + 2, x1 + bw - 2
        draw.rounded_rectangle(label, radius=min(ctx.scale(10), max(2, (label[2] - label[0]) // 4)), fill=rgba(mix(p.light, p.accent, 0.18), 230))
    else:
        bw, bh = int(w * 0.28), int(h * 0.44)
        x1, y1 = cx - bw // 2, base_y - bh
        side = int(bw * 0.25)
        front = [(x1, y1), (x1 + bw, y1), (x1 + bw, base_y), (x1, base_y)]
        side_poly = [(x1 + bw, y1), (x1 + bw + side, y1 - ctx.scale(35)), (x1 + bw + side, base_y - ctx.scale(40)), (x1 + bw, base_y)]
        top_poly = [(x1, y1), (x1 + side, y1 - ctx.scale(35)), (x1 + bw + side, y1 - ctx.scale(35)), (x1 + bw, y1)]
        draw.polygon(front, fill=rgba(lighten(p.dark, 0.10), 245), outline=rgba(p.light, 95))
        draw.polygon(side_poly, fill=rgba(darken(p.mid, 0.10), 245), outline=rgba(p.light, 75))
        draw.polygon(top_poly, fill=rgba(lighten(p.mid, 0.10), 245), outline=rgba(p.light, 75))
        lm = min(ctx.scale(28), max(2, bw // 5))
        label = [x1 + lm, y1 + int(bh * 0.33), x1 + bw - lm, y1 + int(bh * 0.68)]
        if label[2] <= label[0]:
            label[0], label[2] = x1 + 2, x1 + bw - 2
        draw.rounded_rectangle(label, radius=min(ctx.scale(12), max(2, (label[2] - label[0]) // 4)), fill=rgba(mix(p.light, p.accent, 0.14), 235))

    font_title = get_font(max(8, min(ctx.scale(30), (label[2] - label[0]) // 4)), bold=True)
    font_small = get_font(max(7, min(ctx.scale(14), (label[2] - label[0]) // 8)), bold=False)
    draw_wrapped_text(draw, ctx.spec.title.upper(), ((label[0] + label[2]) // 2, label[1] + ctx.scale(18)), label[2] - label[0] - ctx.scale(20), rgba(darken(p.dark, 0.08), 245), font_title, line_spacing=ctx.scale(4))
    draw_wrapped_text(draw, ctx.spec.style.upper(), ((label[0] + label[2]) // 2, label[3] - ctx.scale(34)), label[2] - label[0] - ctx.scale(20), rgba(darken(p.dark, 0.05), 170), font_small, line_spacing=ctx.scale(2))

    for _ in range(120):
        x, y = py.randint(0, w), py.randint(0, int(h * 0.75))
        r = py.choice([1, 1, 2, 3]) * ctx.ss
        draw.ellipse([x - r, y - r, x + r, y + r], fill=rgba(py.choice([p.accent, p.light, p.warm]), py.randint(15, 80)))

    return finish_image(ctx, img)


# -----------------------------------------------------------------------------
# Backends
# -----------------------------------------------------------------------------

class ProceduralBackend:
    def generate(self, spec: SceneSpec) -> Image.Image:
        ctx = RenderContext(spec)
        renderers: dict[str, Callable[[RenderContext], Image.Image]] = {
            "space": render_space,
            "cityscape": render_cityscape,
            "abstract": render_abstract,
            "poster": render_poster,
            "emblem": render_emblem,
            "product": render_product,
            "landscape": render_landscape,
        }
        return renderers.get(spec.scene_type, render_landscape)(ctx)


class DiffusionBackend:
    """Optional local model backend.

    Requires optional packages:
        torch, diffusers, transformers, accelerate, safetensors
    """

    def __init__(self, model: str, device: str = "auto", *, steps: int = 36, guidance: float = 7.2):
        if not model:
            raise ValueError("--model is required when using the diffusion backend")

        try:
            import torch
            from diffusers import DiffusionPipeline
        except Exception as exc:
            raise RuntimeError(
                "The optional model backend requires torch, diffusers, transformers, accelerate, and safetensors."
            ) from exc

        self.torch = torch
        self.steps = int(steps)
        self.guidance = float(guidance)

        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        self.device = device
        dtype = torch.float16 if device == "cuda" else torch.float32

        self.pipe = DiffusionPipeline.from_pretrained(model, torch_dtype=dtype, use_safetensors=True)
        self.pipe.to(device)
        if hasattr(self.pipe, "enable_attention_slicing"):
            self.pipe.enable_attention_slicing()

    def generate(self, spec: SceneSpec) -> Image.Image:
        generator = self.torch.Generator(device=self.device).manual_seed(spec.seed)
        prompt = f"{spec.prompt}, {spec.style} style, professional composition, rich lighting, coherent detail"
        image = self.pipe(
            prompt=prompt,
            negative_prompt=spec.negative_prompt,
            width=spec.width,
            height=spec.height,
            num_inference_steps=self.steps,
            guidance_scale=self.guidance,
            generator=generator,
        ).images[0]
        return image.convert("RGB")


def build_backend(args: argparse.Namespace) -> ProceduralBackend | DiffusionBackend:
    if args.backend == "procedural":
        return ProceduralBackend()
    if args.backend == "diffusion":
        return DiffusionBackend(args.model, args.device, steps=args.steps, guidance=args.guidance)
    if args.model:
        try:
            return DiffusionBackend(args.model, args.device, steps=args.steps, guidance=args.guidance)
        except Exception as exc:
            logging.warning("Could not initialize optional model backend: %s", exc)
            logging.warning("Using procedural backend instead.")
    return ProceduralBackend()


# -----------------------------------------------------------------------------
# Output
# -----------------------------------------------------------------------------

def spec_to_jsonable(spec: SceneSpec) -> dict[str, Any]:
    data = asdict(spec)
    data["palette"] = asdict(spec.palette)
    return data


def save_json(data: dict[str, Any], path: Path) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def save_image(image: Image.Image, path: Path, fmt: str) -> None:
    fmt = fmt.lower()
    if fmt == "jpg":
        fmt = "jpeg"
    if fmt == "png":
        image.save(path)
    elif fmt in {"jpeg", "webp"}:
        image.save(path, quality=95, optimize=True)
    else:
        raise ValueError(f"Unsupported format: {fmt}")


def make_contact_sheet(paths: list[Path], output_path: Path, thumb_w: int = 360) -> None:
    if not paths:
        return

    images: list[Image.Image] = []
    try:
        for p in paths:
            with Image.open(p) as src:
                images.append(src.convert("RGB"))

        aspect = images[0].height / max(images[0].width, 1)
        thumb_h = max(1, int(thumb_w * aspect))
        cols = math.ceil(math.sqrt(len(images)))
        rows = math.ceil(len(images) / cols)

        sheet = Image.new("RGB", (cols * thumb_w, rows * thumb_h), (18, 18, 24))
        for idx, img in enumerate(images):
            thumb = img.resize((thumb_w, thumb_h), RESAMPLE)
            sheet.paste(thumb, ((idx % cols) * thumb_w, (idx // cols) * thumb_h))
        sheet.save(output_path, quality=95)
    finally:
        for img in images:
            img.close()


def read_query(args: argparse.Namespace) -> str:
    parts = [args.query or ""]
    if args.query_file:
        qpath = Path(args.query_file).expanduser()
        if not qpath.exists():
            raise FileNotFoundError(f"Query file does not exist: {qpath}")
        parts.append(qpath.read_text(errors="ignore"))
    return "\n".join(part for part in parts if part).strip()


def output_extension(fmt: str) -> str:
    return "jpg" if fmt.lower() in {"jpeg", "jpg"} else fmt.lower()


def generate_batch(args: argparse.Namespace) -> list[Path]:
    out_dir = resolve_tool_path(args.out, str(image_outputs_dir()))
    log_dir = resolve_tool_path(args.logs, str(image_logs_dir()))
    configure_logging(log_dir, verbose=args.verbose)

    out_dir.mkdir(parents=True, exist_ok=True)
    query = read_query(args)
    project = analyze_project_folder(args.project)
    backend = build_backend(args)
    interpreter = PromptInterpreter()

    saved: list[Path] = []
    manifest: list[dict[str, Any]] = []

    for i in range(args.count):
        spec = interpreter.build(query, project, args, i)
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

        ext = output_extension(args.format)
        image_path = out_dir / f"{base_name}.{ext}"
        save_image(image, image_path, args.format)

        record = {
            "path": str(image_path),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "spec": spec_to_jsonable(spec),
        }
        manifest.append(record)
        saved.append(image_path)

        if args.save_specs:
            save_json(record, out_dir / f"{base_name}.json")

        logging.info("Saved: %s", image_path)

    if args.sheet:
        sheet_path = out_dir / f"{args.prefix}_contact_sheet.jpg"
        make_contact_sheet(saved, sheet_path)
        logging.info("Saved: %s", sheet_path)

    if args.manifest:
        save_json({"items": manifest}, out_dir / f"{args.prefix}_manifest.json")
        logging.info("Saved: %s", out_dir / f"{args.prefix}_manifest.json")

    return saved


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------

def load_preset(name_or_path: str) -> dict[str, Any]:
    if not name_or_path:
        return {}

    candidate = Path(name_or_path).expanduser()
    if not candidate.exists():
        candidate = package_root() / "presets" / f"{name_or_path}.json"
    if not candidate.exists():
        raise FileNotFoundError(f"Preset not found: {name_or_path}")
    return json.loads(candidate.read_text(encoding="utf-8"))


def apply_preset_defaults(args: argparse.Namespace, parser: argparse.ArgumentParser) -> argparse.Namespace:
    preset = load_preset(args.preset)
    if not preset:
        return args

    defaults = {
        action.dest: action.default
        for action in parser._actions
        if action.dest not in {"help"} and action.default is not argparse.SUPPRESS
    }
    for key, value in preset.items():
        if not hasattr(args, key):
            continue
        if getattr(args, key) == defaults.get(key):
            setattr(args, key, value)
    return args


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Procedural image generation with optional local model support.")
    parser.add_argument("--query", type=str, default="", help="Text prompt.")
    parser.add_argument("--query-file", type=str, default="", help="Text file containing a prompt.")
    parser.add_argument("--project", type=str, default="", help="Folder containing image/text references.")
    parser.add_argument("--preset", type=str, default="", help="Preset JSON file or preset name from presets/.")

    parser.add_argument("--type", type=str, default="auto", choices=["auto", "landscape", "poster", "abstract", "emblem", "product", "cityscape", "space"])
    parser.add_argument("--style", type=str, default="auto", choices=["auto", "balanced", "cinematic", "minimal", "luxury", "neon", "fantasy"])
    parser.add_argument("--palette", type=str, default="auto", choices=["auto", *sorted(PALETTES.keys())])

    parser.add_argument("--backend", type=str, default="procedural", choices=["procedural", "diffusion", "auto"])
    parser.add_argument("--model", type=str, default="", help="Optional local model folder or compatible model identifier.")
    parser.add_argument("--device", type=str, default="auto", help="auto, cuda, cpu, etc.")
    parser.add_argument("--steps", type=int, default=36, help="Sampling steps for optional model backend.")
    parser.add_argument("--guidance", type=float, default=7.2, help="Guidance scale for optional model backend.")

    parser.add_argument("--negative", type=str, default="", help="Negative prompt for optional model backend.")
    parser.add_argument("--title", type=str, default="", help="Optional title used by poster/product/emblem scenes.")

    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--seed", type=int, default=77)

    parser.add_argument("--width", type=int, default=1400)
    parser.add_argument("--height", type=int, default=900)
    parser.add_argument("--supersample", type=int, default=1)

    parser.add_argument("--out", type=str, default="", help="Output folder. Defaults to artifacts/image_engine/outputs under the project root.")
    parser.add_argument("--logs", type=str, default="", help="Log folder. Defaults to artifacts/image_engine/logs under the project root.")
    parser.add_argument("--prefix", type=str, default="image_engine")
    parser.add_argument("--format", type=str, default="png", choices=["png", "jpg", "jpeg", "webp"])

    parser.add_argument("--sheet", action="store_true", help="Create a contact sheet.")
    parser.add_argument("--save-specs", action="store_true", help="Write per-image JSON metadata.")
    parser.add_argument("--manifest", action="store_true", help="Write one manifest JSON for the batch.")
    parser.add_argument("--name-from-prompt", action="store_true", help="Include inferred title in filenames.")
    parser.add_argument("--verbose", action="store_true")
    return parser


def validate_args(args: argparse.Namespace) -> argparse.Namespace:
    if args.count < 1:
        raise ValueError("--count must be at least 1")
    if args.width < 64 or args.height < 64:
        raise ValueError("--width and --height must each be at least 64")
    if args.supersample < 1 or args.supersample > 4:
        raise ValueError("--supersample must be between 1 and 4")
    if args.backend == "diffusion" and not args.model:
        raise ValueError("--model is required when --backend diffusion is selected")
    if args.width % 8 != 0 or args.height % 8 != 0:
        logging.warning("Width and height are best when divisible by 8.")
    return args


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = build_parser()
    args = parser.parse_args(argv)
    args = apply_preset_defaults(args, parser)
    return validate_args(args)


def main(argv: list[str] | None = None) -> int:
    try:
        generate_batch(parse_args(argv))
        return 0
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
