from __future__ import annotations

from dataclasses import dataclass, field, asdict, replace
from pathlib import Path
from typing import Optional, List, Tuple, Dict, Any
from collections import Counter
try:
    from PIL import Image, ImageDraw, ImageFilter, ImageEnhance, ImageFont
except ImportError:
    Image = ImageDraw = ImageFilter = ImageEnhance = ImageFont = None  # type: ignore[assignment]
try:
    import numpy as np
except ImportError:
    np = None  # type: ignore[assignment]
import random
import math
import json
import re

Color = Tuple[int, int, int]
RGBA = Tuple[int, int, int, int]

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"}
TEXT_EXTS = {".txt", ".md", ".json", ".csv", ".yaml", ".yml"}

try:
    LANCZOS = Image.Resampling.LANCZOS
except AttributeError:
    LANCZOS = Image.LANCZOS


def clamp(x, lo=0, hi=255):
    return max(lo, min(hi, x))


def clamp01(x):
    return np.clip(x, 0.0, 1.0)


def smoothstep(t):
    return t * t * (3.0 - 2.0 * t)


def lerp(a, b, t):
    return a + (b - a) * t


def mix(a: Color, b: Color, t: float) -> Color:
    return (
        int(clamp(a[0] + (b[0] - a[0]) * t)),
        int(clamp(a[1] + (b[1] - a[1]) * t)),
        int(clamp(a[2] + (b[2] - a[2]) * t)),
    )


def darken(c: Color, amount: float) -> Color:
    return mix(c, (0, 0, 0), amount)


def lighten(c: Color, amount: float) -> Color:
    return mix(c, (255, 255, 255), amount)


def rgba(c: Color, a: int) -> RGBA:
    return (int(c[0]), int(c[1]), int(c[2]), int(clamp(a)))


def luminance(c: Color) -> float:
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def saturation_score(c: Color) -> float:
    return max(c) - min(c)


def tokenize(text: str) -> List[str]:
    return re.findall(r"[a-zA-Z0-9']+", text.lower())


def sanitize_filename(text: str, max_len: int = 80) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9_\- ]+", "", text)
    text = re.sub(r"\s+", "_", text)
    return text[:max_len] or "image"


STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "with", "in", "on", "at", "to", "for",
    "from", "by", "as", "is", "are", "be", "this", "that", "these", "those",
    "image", "picture", "art", "make", "create", "generate", "design", "show",
    "style", "high", "quality", "detailed", "ultra", "beautiful", "very"
}


def title_from_prompt(prompt: str, fallback: str = "ELI Image") -> str:
    words = [w for w in tokenize(prompt) if w not in STOPWORDS and len(w) > 2]
    if not words:
        return fallback
    return " ".join(words[:4]).title()


def get_font(size: int, bold: bool = False):
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
    ]
    for path in paths:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()


def draw_centered(draw, text, x, y, font, fill):
    try:
        box = draw.textbbox((0, 0), text, font=font)
        tw = box[2] - box[0]
    except Exception:
        tw = len(text) * 8
    draw.text((x - tw // 2, y), text, font=font, fill=fill)


def draw_wrapped_text(draw, text, xy, max_width, font, fill, line_spacing=6):
    words = text.split()
    lines = []
    current = ""

    for word in words:
        trial = word if not current else current + " " + word
        try:
            box = draw.textbbox((0, 0), trial, font=font)
            tw = box[2] - box[0]
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
            box = draw.textbbox((0, 0), line, font=font)
            tw = box[2] - box[0]
            th = box[3] - box[1]
        except Exception:
            tw = len(line) * 8
            th = 12

        draw.text((x - tw // 2, y), line, font=font, fill=fill)
        y += th + line_spacing


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


def fbm(width, height, seed, octaves=6, persistence=0.52, base_cells_x=2, base_cells_y=None):
    if base_cells_y is None:
        base_cells_y = max(1, int(base_cells_x * height / max(width, 1)))

    result = np.zeros((height, width), dtype=np.float32)
    amp = 1.0
    total = 0.0

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
        total += amp
        amp *= persistence

    return result / max(total, 1e-6)


def domain_warped_fbm(width, height, seed, strength=48.0, octaves=6, base_cells=2):
    warp_x = fbm(width, height, seed + 100, octaves=4, base_cells_x=base_cells)
    warp_y = fbm(width, height, seed + 200, octaves=4, base_cells_x=base_cells)
    detail = fbm(width, height, seed + 300, octaves=octaves, base_cells_x=base_cells)

    yy, xx = np.mgrid[0:height, 0:width]
    wx = np.clip(xx + (warp_x - 0.5) * strength, 0, width - 1).astype(np.int32)
    wy = np.clip(yy + (warp_y - 0.5) * strength, 0, height - 1).astype(np.int32)

    return detail[wy, wx]


@dataclass
class Palette:
    name: str
    dark: Color
    mid: Color
    primary: Color
    accent: Color
    light: Color
    warm: Color


@dataclass
class StylePreset:
    name: str
    contrast: float = 1.05
    saturation: float = 1.06
    grain: float = 4.0
    vignette: float = 130.0
    glow: float = 1.0
    cloud_softness: float = 1.0
    final_blur: float = 0.0


@dataclass
class SceneConfig:
    subject: str = "floating crystal island"
    environment: str = "sunset lake"
    mood: str = "magical"
    style: str = "cinematic fantasy"
    lighting: str = "sunset"
    camera: str = "wide cinematic shot"

    scene_type: str = "auto"
    prompt: str = ""
    title: str = ""

    width: int = 1400
    height: int = 900
    seed: int = 77
    variant: int = 0
    supersample: int = 1

    palette_name: str = "auto"
    custom_palette: Optional[List[Color]] = None

    detail_level: str = "high"
    atmosphere: str = "misty"
    horizon: Optional[float] = None

    subject_scale: float = 1.0
    subject_position: Tuple[float, float] = (0.5, 0.5)

    cloud_density: float = 1.0
    particle_amount: int = 420
    glow_strength: float = 1.0
    water_reflection_strength: float = 0.75
    mountain_depth: int = 3

    export_layers: bool = False
    export_metadata: bool = False
    output_format: str = "png"

    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CompositionPlan:
    horizon: float
    focal_point: Tuple[float, float]
    sun_position: Tuple[float, float]
    subject_position: Tuple[float, float]
    subject_scale: float
    depth_layers: int
    camera: str


@dataclass
class ProjectContext:
    text: str = ""
    tags: List[str] = field(default_factory=list)
    colors: List[Color] = field(default_factory=list)
    files: List[str] = field(default_factory=list)


@dataclass
class RenderResult:
    image: Image.Image
    config: SceneConfig
    palette: Palette
    style: StylePreset
    plan: CompositionPlan
    layers: Dict[str, Image.Image]
    metadata: Dict[str, Any]


PALETTES: Dict[str, Palette] = {
    "violet_dusk": Palette("violet_dusk", (20, 23, 49), (69, 65, 112), (116, 102, 148), (239, 171, 125), (255, 232, 190), (255, 203, 129)),
    "emerald_aurora": Palette("emerald_aurora", (7, 31, 38), (23, 82, 76), (49, 148, 119), (126, 255, 200), (231, 255, 221), (201, 255, 169)),
    "crimson_sunset": Palette("crimson_sunset", (43, 16, 48), (103, 42, 75), (178, 65, 94), (255, 157, 88), (255, 230, 177), (255, 192, 103)),
    "blue_dawn": Palette("blue_dawn", (13, 35, 72), (50, 92, 139), (92, 153, 193), (229, 219, 176), (246, 252, 255), (255, 238, 178)),
    "golden_storm": Palette("golden_storm", (31, 32, 45), (81, 73, 70), (136, 107, 76), (241, 177, 94), (255, 236, 180), (255, 199, 91)),
    "neon_noir": Palette("neon_noir", (8, 8, 18), (25, 18, 54), (67, 41, 122), (255, 40, 168), (180, 255, 252), (255, 211, 91)),
    "monochrome_luxury": Palette("monochrome_luxury", (12, 12, 14), (48, 46, 43), (104, 99, 91), (212, 176, 91), (245, 238, 221), (255, 214, 132)),
    "alien_bloom": Palette("alien_bloom", (10, 16, 23), (30, 71, 66), (90, 201, 151), (201, 82, 255), (221, 255, 235), (255, 167, 88)),
}


STYLES: Dict[str, StylePreset] = {
    "cinematic": StylePreset("cinematic", contrast=1.08, saturation=1.08, grain=4.5, vignette=145, glow=1.15),
    "fantasy": StylePreset("fantasy", contrast=1.06, saturation=1.12, grain=4.0, vignette=130, glow=1.25),
    "cyberpunk": StylePreset("cyberpunk", contrast=1.14, saturation=1.25, grain=5.0, vignette=155, glow=1.55),
    "gothic": StylePreset("gothic", contrast=1.16, saturation=0.86, grain=5.5, vignette=180, glow=0.85),
    "watercolor": StylePreset("watercolor", contrast=0.96, saturation=0.92, grain=2.0, vignette=80, glow=0.70, cloud_softness=1.8, final_blur=0.35),
    "alien": StylePreset("alien", contrast=1.10, saturation=1.18, grain=4.0, vignette=140, glow=1.45),
    "luxury": StylePreset("luxury", contrast=1.07, saturation=0.96, grain=2.5, vignette=110, glow=1.05),
    "minimal": StylePreset("minimal", contrast=1.02, saturation=0.90, grain=1.2, vignette=60, glow=0.65),
    "balanced": StylePreset("balanced"),
}


def palette_from_colors(colors: List[Color], name="project_palette") -> Palette:
    if len(colors) < 3:
        return PALETTES["violet_dusk"]

    colors = sorted(colors, key=luminance)
    dark = darken(colors[0], 0.22)
    light = lighten(colors[-1], 0.18)
    accent = max(colors, key=saturation_score)
    primary = colors[len(colors) // 2]
    mid = mix(dark, primary, 0.62)
    warm = mix(accent, light, 0.35)

    return Palette(name, dark, mid, primary, accent, light, warm)


class StyleSystem:
    def choose_palette(self, config: SceneConfig, project: Optional[ProjectContext] = None) -> Palette:
        if config.custom_palette and len(config.custom_palette) >= 3:
            return palette_from_colors(config.custom_palette, "custom_palette")

        if project and project.colors:
            return palette_from_colors(project.colors, "project_palette")

        text = " ".join([config.prompt, config.subject, config.environment, config.mood, config.style, config.lighting]).lower()

        if config.palette_name != "auto" and config.palette_name in PALETTES:
            return PALETTES[config.palette_name]

        if any(w in text for w in ["neon", "cyber", "synth"]):
            return PALETTES["neon_noir"]
        if any(w in text for w in ["luxury", "premium", "gold", "royal", "elegant", "perfume"]):
            return PALETTES["monochrome_luxury"]
        if any(w in text for w in ["emerald", "forest", "aurora", "green", "nature"]):
            return PALETTES["emerald_aurora"]
        if any(w in text for w in ["crimson", "red", "blood", "fire", "volcanic"]):
            return PALETTES["crimson_sunset"]
        if any(w in text for w in ["blue", "ocean", "dawn", "ice", "moon"]):
            return PALETTES["blue_dawn"]
        if any(w in text for w in ["alien", "bioluminescent", "extraterrestrial"]):
            return PALETTES["alien_bloom"]

        names = list(PALETTES.keys())
        return PALETTES[names[config.seed % len(names)]]

    def choose_style(self, config: SceneConfig) -> StylePreset:
        text = " ".join([config.prompt, config.style, config.mood]).lower()

        checks = [
            ("cyberpunk", ["cyberpunk", "neon", "synthwave"]),
            ("gothic", ["gothic", "dark", "cathedral", "horror"]),
            ("watercolor", ["watercolor", "painted", "soft wash"]),
            ("luxury", ["luxury", "premium", "elegant", "editorial", "perfume"]),
            ("minimal", ["minimal", "clean", "simple"]),
            ("alien", ["alien", "bioluminescent", "extraterrestrial"]),
            ("fantasy", ["fantasy", "magical", "mythic", "spell"]),
            ("cinematic", ["cinematic", "epic", "film", "dramatic"]),
        ]

        for name, words in checks:
            if any(w in text for w in words):
                return STYLES[name]

        return STYLES["balanced"]


def dominant_colors_from_image(path: Path, max_colors=6) -> List[Color]:
    try:
        img = Image.open(path).convert("RGBA")
        bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
        bg.alpha_composite(img)
        img = bg.convert("RGB")
        img.thumbnail((120, 120), LANCZOS)

        q = img.quantize(colors=max_colors)
        pal = q.getpalette()
        counts = q.getcolors(maxcolors=120 * 120)

        if not counts:
            return []

        counts.sort(reverse=True)
        out = []

        for _, index in counts[:max_colors]:
            base = index * 3
            c = tuple(pal[base:base + 3])
            if len(c) == 3:
                out.append((int(c[0]), int(c[1]), int(c[2])))

        return out
    except Exception:
        return []


class ProjectAnalyzer:
    def analyze(self, folder: Optional[str]) -> ProjectContext:
        if not folder:
            return ProjectContext()

        root = Path(folder)

        if not root.exists():
            raise FileNotFoundError(f"Project folder does not exist: {folder}")

        text_chunks = []
        tags = []
        colors = []
        files = []

        for path in root.rglob("*"):
            if not path.is_file():
                continue

            files.append(str(path))
            suffix = path.suffix.lower()
            tags.extend(tokenize(path.stem.replace("_", " ").replace("-", " ")))

            if suffix in TEXT_EXTS:
                try:
                    text_chunks.append(path.read_text(errors="ignore")[:12000])
                except Exception:
                    pass

            elif suffix in IMAGE_EXTS:
                colors.extend(dominant_colors_from_image(path))

        clean_tags = [t for t in tags if t not in STOPWORDS and len(t) > 2]
        common_colors = [c for c, _ in Counter(colors).most_common(14)]

        return ProjectContext(
            text="\n".join(text_chunks),
            tags=clean_tags[:120],
            colors=common_colors,
            files=files[:300],
        )


SCENE_KEYWORDS = {
    "landscape": {"landscape", "world", "mountain", "lake", "island", "forest", "castle", "terrain", "fantasy", "waterfall", "valley", "sky", "horizon", "nature", "ocean", "river", "temple"},
    "poster": {"poster", "cover", "album", "movie", "flyer", "advertisement", "print", "campaign", "editorial", "magazine", "banner"},
    "abstract": {"abstract", "pattern", "generative", "fractal", "flow", "texture", "wallpaper", "motion", "chaos", "waves", "geometric"},
    "emblem": {"logo", "emblem", "badge", "crest", "icon", "seal", "symbol", "mark"},
    "product": {"product", "bottle", "perfume", "package", "box", "cosmetic", "luxury", "label", "brand", "mockup"},
    "cityscape": {"city", "street", "skyline", "urban", "tower", "skyscraper", "metropolis", "cyberpunk", "building", "neon"},
    "space": {"space", "planet", "galaxy", "nebula", "star", "cosmos", "moon", "asteroid", "spaceship", "orbit"},
}


class PromptInterpreter:
    def infer_scene_type(self, text: str, forced: str = "auto") -> str:
        if forced != "auto":
            return forced

        tokens = set(tokenize(text))
        scores = {scene: len(tokens & words) for scene, words in SCENE_KEYWORDS.items()}
        best_scene, best_score = max(scores.items(), key=lambda kv: kv[1])

        return best_scene if best_score > 0 else "landscape"

    def interpret(self, prompt: str, base: Optional[SceneConfig] = None, project: Optional[ProjectContext] = None, forced_type: str = "auto") -> SceneConfig:
        config = replace(base) if base else SceneConfig()

        project_text = project.text if project else ""
        project_tags = " ".join(project.tags[:80]) if project else ""
        combined = " ".join([prompt or "", project_text, project_tags]).strip()

        if not combined:
            combined = "cinematic fantasy floating crystal island above a reflective sunset lake"

        text = combined.lower()
        tokens = set(tokenize(text))

        config.prompt = combined
        config.scene_type = self.infer_scene_type(text, forced_type)
        config.title = config.title or title_from_prompt(combined)

        if "crystal" in tokens and ("island" in tokens or "floating" in tokens):
            config.subject = "floating crystal island"
            config.glow_strength *= 1.35
            config.particle_amount += 180

        if "castle" in tokens:
            config.subject = "floating castle"
            config.mountain_depth = max(config.mountain_depth, 4)

        if "temple" in tokens:
            config.subject = "ancient temple"
            config.mountain_depth = max(config.mountain_depth, 4)

        if "forest" in tokens:
            config.subject = "floating forest island"
            config.cloud_density *= 0.9

        if {"planet", "space", "galaxy"} & tokens:
            config.subject = "planetary scene"
            config.environment = "deep space"
            config.scene_type = forced_type if forced_type != "auto" else "space"

        if {"city", "skyline", "cyberpunk"} & tokens:
            config.subject = "city skyline"
            config.environment = "neon city"
            config.scene_type = forced_type if forced_type != "auto" else "cityscape"

        if {"product", "perfume", "bottle", "package"} & tokens:
            config.subject = "premium product"
            config.scene_type = forced_type if forced_type != "auto" else "product"

        if {"logo", "emblem", "badge", "crest"} & tokens:
            config.subject = "symbolic emblem"
            config.scene_type = forced_type if forced_type != "auto" else "emblem"

        if {"poster", "cover", "campaign"} & tokens:
            config.scene_type = forced_type if forced_type != "auto" else "poster"

        if {"abstract", "fractal", "geometric"} & tokens:
            config.scene_type = forced_type if forced_type != "auto" else "abstract"

        if "gothic" in tokens or "dark" in tokens:
            config.mood = "dark gothic"
            config.style = "gothic cinematic"
            config.cloud_density *= 1.15
            config.glow_strength *= 0.75

        if {"magical", "glowing", "mystic"} & tokens:
            config.mood = "magical"
            config.particle_amount += 220
            config.glow_strength *= 1.35

        if {"calm", "peaceful", "serene"} & tokens:
            config.mood = "peaceful"
            config.water_reflection_strength = 0.9
            config.cloud_density *= 0.65

        if {"epic", "massive", "heroic"} & tokens:
            config.camera = "wide heroic cinematic shot"
            config.subject_scale *= 1.22
            config.mountain_depth = max(config.mountain_depth, 5)
            config.detail_level = "ultra"

        if "watercolor" in tokens:
            config.style = "watercolor"
            config.detail_level = "soft"

        if "cyberpunk" in tokens or "neon" in tokens:
            config.style = "cyberpunk"
            config.lighting = "neon night"
            config.palette_name = "neon_noir"
            config.glow_strength *= 1.5

        if {"luxury", "premium", "elegant"} & tokens:
            config.style = "luxury"
            config.mood = "elegant"
            config.palette_name = "monochrome_luxury"

        if {"alien", "bioluminescent"} & tokens:
            config.style = "alien"
            config.palette_name = "alien_bloom"
            config.glow_strength *= 1.4

        if "moonlit" in tokens or "moonlight" in tokens:
            config.lighting = "moonlit"
            if config.palette_name == "auto":
                config.palette_name = "blue_dawn"

        if "sunset" in tokens or "dusk" in tokens:
            config.lighting = "sunset"

        if "dawn" in tokens or "sunrise" in tokens:
            config.lighting = "dawn"
            if config.palette_name == "auto":
                config.palette_name = "blue_dawn"

        return config


class CompositionPlanner:
    def plan(self, config: SceneConfig) -> CompositionPlan:
        rng = np.random.default_rng(config.seed + config.variant * 911)

        if config.horizon is not None:
            horizon = float(config.horizon)
        elif config.scene_type in {"poster", "product", "emblem", "abstract"}:
            horizon = 0.72
        elif config.scene_type == "cityscape":
            horizon = float(rng.uniform(0.56, 0.68))
        elif config.scene_type == "space":
            horizon = 0.50
        else:
            horizon = float(rng.uniform(0.52, 0.60))

        sx, sy = config.subject_position

        if sx == 0.5 and sy == 0.5:
            sx = float(rng.uniform(0.44, 0.56))
            sy = float(rng.uniform(0.43, 0.54))

        sun_position = (
            float(rng.uniform(0.16, 0.82)),
            float(rng.uniform(0.11, 0.31)),
        )

        return CompositionPlan(
            horizon=horizon,
            focal_point=(sx, sy),
            sun_position=sun_position,
            subject_position=(sx, sy),
            subject_scale=config.subject_scale,
            depth_layers=max(1, int(config.mountain_depth)),
            camera=config.camera,
        )


class RenderContext:
    def __init__(self, config: SceneConfig, palette: Palette, style: StylePreset, plan: CompositionPlan):
        self.config = config
        self.palette = palette
        self.style = style
        self.plan = plan

        self.ss = max(1, int(config.supersample))
        self.out_w = int(config.width)
        self.out_h = int(config.height)
        self.w = self.out_w * self.ss
        self.h = self.out_h * self.ss

        self.seed = int(config.seed + config.variant * 7919)
        self.rng = np.random.default_rng(self.seed)
        self.py = random.Random(self.seed)

        prompt_text = " ".join([config.prompt, config.subject, config.environment, config.style, config.mood])
        self.tokens = set(tokenize(prompt_text))
        self.layers: Dict[str, Image.Image] = {}

    def s(self, value: float) -> int:
        return max(1, int(value * self.ss))

    def xy(self, norm: Tuple[float, float]) -> Tuple[int, int]:
        return int(self.w * norm[0]), int(self.h * norm[1])

    @property
    def horizon_y(self) -> int:
        return int(self.h * self.plan.horizon)

    @property
    def sun_xy(self) -> Tuple[int, int]:
        return self.xy(self.plan.sun_position)

    @property
    def subject_xy(self) -> Tuple[int, int]:
        return self.xy(self.plan.subject_position)


def make_vertical_gradient(width, height, top, middle, bottom, middle_at=0.58):
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


def add_radial_glow(img, center, color, radius, strength, squash_y=1.0):
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer, "RGBA")

    step = max(4, radius // 54)

    for r in range(radius, 0, -step):
        alpha = int(strength * ((r / radius) ** 2))
        ry = int(r * squash_y)

        d.ellipse(
            [center[0] - r, center[1] - ry, center[0] + r, center[1] + ry],
            fill=rgba(color, alpha),
        )

    img.alpha_composite(layer)


def downsample(ctx: RenderContext, img: Image.Image) -> Image.Image:
    if ctx.ss > 1:
        img = img.resize((ctx.out_w, ctx.out_h), LANCZOS)
    return img


class ProceduralRenderer:
    def render(self, config: SceneConfig, palette: Palette, style: StylePreset, plan: CompositionPlan) -> RenderResult:
        ctx = RenderContext(config, palette, style, plan)
        img = self.background(ctx)
        self.capture(ctx, "background", img)

        self.atmosphere(ctx, img)
        self.capture(ctx, "atmosphere", img)

        scene = config.scene_type

        if scene == "landscape":
            self.landscape_environment(ctx, img)
            self.capture(ctx, "environment", img)
            self.floating_island(ctx, img)
            self.capture(ctx, "subject", img)
        elif scene == "product":
            self.product_scene(ctx, img)
            self.capture(ctx, "product", img)
        elif scene == "poster":
            self.poster_scene(ctx, img)
            self.capture(ctx, "poster", img)
        elif scene == "space":
            self.space_scene(ctx, img)
            self.capture(ctx, "space", img)
        elif scene == "cityscape":
            self.city_scene(ctx, img)
            self.capture(ctx, "cityscape", img)
        elif scene == "abstract":
            self.abstract_scene(ctx, img)
            self.capture(ctx, "abstract", img)
        elif scene == "emblem":
            self.emblem_scene(ctx, img)
            self.capture(ctx, "emblem", img)

        self.particles(ctx, img)
        self.capture(ctx, "particles", img)

        img = self.postprocess(ctx, img)
        self.capture(ctx, "postprocess", img, final=True)

        metadata = {
            "prompt": config.prompt,
            "seed": config.seed,
            "variant": config.variant,
            "scene_type": config.scene_type,
            "palette": palette.name,
            "style": style.name,
            "width": config.width,
            "height": config.height,
        }

        return RenderResult(img, config, palette, style, plan, ctx.layers, metadata)

    def capture(self, ctx: RenderContext, name: str, img: Image.Image, final: bool = False):
        if not ctx.config.export_layers:
            return
        layer = img.copy()
        if not final:
            layer = downsample(ctx, layer).convert("RGB")
        ctx.layers[name] = layer

    def background(self, ctx: RenderContext) -> Image.Image:
        p = ctx.palette
        scene = ctx.config.scene_type

        if scene == "space":
            return make_vertical_gradient(ctx.w, ctx.h, darken(p.dark, 0.35), p.dark, darken(p.mid, 0.2), 0.55).convert("RGBA")

        if scene in {"product", "poster", "emblem", "abstract"}:
            img = make_vertical_gradient(ctx.w, ctx.h, darken(p.dark, 0.12), p.mid, darken(p.primary, 0.2), 0.62).convert("RGBA")
            add_radial_glow(img, (int(ctx.w * 0.62), int(ctx.h * 0.32)), p.accent, int(min(ctx.w, ctx.h) * 0.44), 26 * ctx.style.glow * ctx.config.glow_strength)
            return img

        img = make_vertical_gradient(ctx.w, ctx.h, p.dark, mix(p.mid, p.primary, 0.45), mix(p.accent, p.light, 0.26), 0.62).convert("RGBA")
        add_radial_glow(img, ctx.sun_xy, p.warm, int(min(ctx.w, ctx.h) * 0.42), 22 * ctx.style.glow * ctx.config.glow_strength)

        d = ImageDraw.Draw(img, "RGBA")
        sr = int(ctx.w * ctx.rng.uniform(0.020, 0.042))

        if "moon" in ctx.config.lighting.lower() or "night" in ctx.config.lighting.lower():
            d.ellipse([ctx.sun_xy[0] - sr, ctx.sun_xy[1] - sr, ctx.sun_xy[0] + sr, ctx.sun_xy[1] + sr], fill=rgba(lighten(p.light, 0.2), 215))
            d.ellipse([ctx.sun_xy[0] - sr // 3, ctx.sun_xy[1] - sr, ctx.sun_xy[0] + sr, ctx.sun_xy[1] + sr], fill=(0, 0, 0, 45))
        else:
            d.ellipse([ctx.sun_xy[0] - sr, ctx.sun_xy[1] - sr, ctx.sun_xy[0] + sr, ctx.sun_xy[1] + sr], fill=rgba(p.light, 225))
            d.ellipse([ctx.sun_xy[0] - sr // 2, ctx.sun_xy[1] - sr // 2, ctx.sun_xy[0] + sr // 2, ctx.sun_xy[1] + sr // 2], fill=rgba((255, 255, 240), 255))

        return img

    def atmosphere(self, ctx: RenderContext, img: Image.Image):
        p = ctx.palette
        scene = ctx.config.scene_type

        if scene == "space":
            nebula = domain_warped_fbm(ctx.w, ctx.h, ctx.seed + 444, strength=ctx.w * 0.08, octaves=7, base_cells=2)
            nebula = clamp01((nebula - 0.30) * 2.4)
            arr = np.zeros((ctx.h, ctx.w, 4), dtype=np.uint8)

            c1 = np.array(p.primary)
            c2 = np.array(p.accent)
            color = c1[None, None, :] * (1 - nebula[:, :, None]) + c2[None, None, :] * nebula[:, :, None]

            arr[:, :, :3] = np.clip(color, 0, 255).astype(np.uint8)
            arr[:, :, 3] = (nebula * 125).astype(np.uint8)

            img.alpha_composite(Image.fromarray(arr, "RGBA").filter(ImageFilter.GaussianBlur(ctx.s(4))))
            return

        if scene == "abstract":
            noise = domain_warped_fbm(ctx.w, ctx.h, ctx.seed + 777, strength=ctx.w * 0.10, octaves=8, base_cells=3)
            mask = clamp01((noise - 0.18) * 1.4)

            arr = np.zeros((ctx.h, ctx.w, 4), dtype=np.uint8)
            c1 = np.array(p.primary)
            c2 = np.array(p.accent)
            c3 = np.array(p.light)

            color = c1[None, None, :] * (1 - mask[:, :, None]) + c2[None, None, :] * mask[:, :, None]
            color = color * 0.78 + c3[None, None, :] * (mask[:, :, None] ** 3) * 0.22

            arr[:, :, :3] = np.clip(color, 0, 255).astype(np.uint8)
            arr[:, :, 3] = (mask * 170).astype(np.uint8)

            img.alpha_composite(Image.fromarray(arr, "RGBA").filter(ImageFilter.GaussianBlur(ctx.s(2))))
            return

        cloud_noise = domain_warped_fbm(ctx.w, ctx.h, ctx.seed + 301, strength=ctx.w * 0.045, octaves=7, base_cells=2)

        y = np.arange(ctx.h)[:, None]
        sky_fade = clamp01((ctx.horizon_y - y) / (ctx.h * 0.45))
        top_fade = np.linspace(1.0, 0.0, ctx.h)[:, None]

        mask = cloud_noise * sky_fade * top_fade
        mask *= ctx.config.cloud_density
        mask = clamp01((mask - 0.22) * 3.5)

        arr = np.zeros((ctx.h, ctx.w, 4), dtype=np.uint8)
        cloud_c = mix(p.light, p.accent, 0.25)

        arr[:, :, 0] = cloud_c[0]
        arr[:, :, 1] = cloud_c[1]
        arr[:, :, 2] = cloud_c[2]
        arr[:, :, 3] = (mask * 115).astype(np.uint8)

        softness = max(1, int(ctx.s(5) * ctx.style.cloud_softness))
        img.alpha_composite(Image.fromarray(arr, "RGBA").filter(ImageFilter.GaussianBlur(softness)))

        dist = np.abs(np.arange(ctx.h) - ctx.horizon_y)[:, None]
        haze = clamp01(1.0 - dist / (ctx.h * 0.25)) ** 1.55

        haze_arr = np.zeros((ctx.h, ctx.w, 4), dtype=np.uint8)
        fog_c = mix(p.light, p.accent, 0.20)

        haze_arr[:, :, 0] = fog_c[0]
        haze_arr[:, :, 1] = fog_c[1]
        haze_arr[:, :, 2] = fog_c[2]
        haze_arr[:, :, 3] = (haze * 46).astype(np.uint8)

        img.alpha_composite(Image.fromarray(haze_arr, "RGBA").filter(ImageFilter.GaussianBlur(ctx.s(3))))

    def landscape_environment(self, ctx: RenderContext, img: Image.Image):
        self.mountains(ctx, img)
        self.water(ctx, img)

    def mountains(self, ctx: RenderContext, img: Image.Image):
        p = ctx.palette

        for i in range(ctx.plan.depth_layers):
            base_y = int(ctx.horizon_y + ctx.h * (i * 0.055 - 0.030))
            amp = int(ctx.h * (0.14 + i * 0.027) * ctx.rng.uniform(0.85, 1.18))
            points = 10 + i * 3

            control_x = np.linspace(0, ctx.w - 1, points)
            control_y = np.array([base_y - ctx.py.random() * amp for _ in range(points)])
            ridge = np.interp(np.arange(ctx.w), control_x, control_y)
            ridge += np.sin(np.linspace(0, math.pi * (2.5 + i * 0.55), ctx.w)) * amp * 0.10

            layer = Image.new("RGBA", (ctx.w, ctx.h), (0, 0, 0, 0))
            d = ImageDraw.Draw(layer, "RGBA")

            mountain_c = darken(mix(p.mid, p.dark, 0.22 + i * 0.10), 0.04)
            fill = rgba(mountain_c, int(125 + min(i, 5) * 24))

            polygon = [(0, ctx.h)]
            polygon.extend([(x, int(ridge[x])) for x in range(ctx.w)])
            polygon.append((ctx.w, ctx.h))

            d.polygon(polygon, fill=fill)

            for x in range(0, ctx.w, ctx.s(4)):
                yy = int(ridge[x])
                d.line([(x, yy), (x + ctx.s(3), yy + ctx.s(2))], fill=rgba(p.light, 18 + i * 5), width=max(1, ctx.s(1)))

            blur = max(0.0, 2.8 - i * 0.5)
            img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(ctx.s(blur))))

    def water(self, ctx: RenderContext, img: Image.Image):
        p = ctx.palette
        water_h = ctx.h - ctx.horizon_y

        if water_h <= 10:
            return

        reflection = img.crop((0, 0, ctx.w, ctx.horizon_y)).transpose(Image.FLIP_TOP_BOTTOM)
        reflection = reflection.resize((ctx.w, water_h), LANCZOS)

        refl = np.array(reflection).astype(np.float32)
        ripple = value_noise(ctx.w, water_h, 24, 9, ctx.seed + 808)

        for y in range(water_h):
            shift = int(
                math.sin(y * 0.045 / ctx.ss) * 7 * ctx.ss
                + math.sin(y * 0.013 / ctx.ss + 2.4) * 12 * ctx.ss
                + (ripple[y, ctx.w // 2] - 0.5) * 18 * ctx.ss
            )
            refl[y] = np.roll(refl[y], shift, axis=0)

        grad = make_vertical_gradient(ctx.w, water_h, mix(p.mid, p.primary, 0.35), mix(p.dark, p.primary, 0.35), darken(p.dark, 0.15), 0.45).convert("RGBA")

        water_arr = np.array(grad).astype(np.float32)
        strength = float(ctx.config.water_reflection_strength)
        depth = np.linspace(strength, max(0.12, strength * 0.30), water_h)[:, None, None]

        blended = refl * depth + water_arr * (1.0 - depth)
        blended[:, :, 3] = 255

        water = Image.fromarray(np.clip(blended, 0, 255).astype(np.uint8), "RGBA")
        d = ImageDraw.Draw(water, "RGBA")

        for _ in range(int(180 * ctx.w * ctx.h / (1400 * 900 * ctx.ss * ctx.ss))):
            y = ctx.py.randint(5, max(6, water_h - 8))
            x = ctx.py.randint(0, ctx.w)
            length = ctx.py.randint(ctx.s(30), ctx.s(190))
            d.line([(x, y), (min(ctx.w, x + length), y)], fill=rgba(p.light, ctx.py.randint(10, 44)), width=max(1, ctx.s(1)))

        img.alpha_composite(water, (0, ctx.horizon_y))

    def floating_island(self, ctx: RenderContext, img: Image.Image):
        p = ctx.palette
        cx, cy = ctx.subject_xy
        top_width = int(ctx.w * 0.34 * ctx.plan.subject_scale)

        island = Image.new("RGBA", (ctx.w, ctx.h), (0, 0, 0, 0))
        d = ImageDraw.Draw(island, "RGBA")

        top_points = []
        for i in range(28):
            t = i / 27
            x = cx - top_width // 2 + int(t * top_width)
            wobble = math.sin(t * math.pi * 6) * ctx.s(12) + ctx.py.randint(-ctx.s(8), ctx.s(8))
            top_points.append((x, cy + int(wobble)))

        bottom_tip = (cx + ctx.s(10), cy + int(ctx.h * 0.28 * ctx.plan.subject_scale))

        dirt_poly = top_points + [
            (cx + int(top_width * 0.47), cy + int(ctx.h * 0.06)),
            (cx + int(top_width * 0.27), cy + int(ctx.h * 0.18)),
            bottom_tip,
            (cx - int(top_width * 0.27), cy + int(ctx.h * 0.18)),
            (cx - int(top_width * 0.47), cy + int(ctx.h * 0.06)),
        ]

        d.polygon(dirt_poly, fill=rgba(darken(p.mid, 0.18), 255))

        for _ in range(130):
            x1 = ctx.py.randint(cx - int(top_width * 0.44), cx + int(top_width * 0.44))
            y1 = ctx.py.randint(cy + ctx.s(16), cy + int(ctx.h * 0.23))
            x2 = x1 + ctx.py.randint(-ctx.s(40), ctx.s(40))
            y2 = y1 + ctx.py.randint(ctx.s(12), ctx.s(48))
            d.line([(x1, y1), (x2, y2)], fill=rgba(darken(p.dark, 0.05), ctx.py.randint(35, 95)), width=ctx.py.randint(1, max(2, ctx.s(3))))

        grass_poly = top_points + [
            (cx + top_width // 2 - ctx.s(20), cy + ctx.s(42)),
            (cx - top_width // 2 + ctx.s(20), cy + ctx.s(42)),
        ]
        d.polygon(grass_poly, fill=rgba(mix(p.primary, p.accent, 0.18), 255))

        for x, y in top_points[::2]:
            d.line([(x - ctx.s(8), y - ctx.s(1)), (x + ctx.s(10), y - ctx.s(4))], fill=rgba(lighten(p.primary, 0.35), 235), width=max(1, ctx.s(2)))

        for _ in range(34):
            sx = ctx.py.randint(cx - int(top_width * 0.41), cx + int(top_width * 0.41))
            sy = cy + ctx.py.randint(ctx.s(25), ctx.s(55))
            length = ctx.py.randint(ctx.s(45), ctx.s(155))
            pts = []
            for j in range(6):
                pts.append((sx + ctx.py.randint(-ctx.s(16), ctx.s(16)), sy + int(length * j / 5)))
            d.line(pts, fill=(45, 30, 25, 170), width=ctx.py.randint(1, max(2, ctx.s(3))))

        for _ in range(ctx.py.randint(8, 17)):
            x = ctx.py.randint(cx - int(top_width * 0.36), cx + int(top_width * 0.36))
            y = cy + ctx.py.randint(-ctx.s(18), ctx.s(12))
            ch = ctx.py.randint(ctx.s(40), ctx.s(110))
            cw = ctx.py.randint(ctx.s(16), ctx.s(36))
            col = ctx.py.choice([p.accent, p.light, p.warm])

            crystal = [
                (x, y - ch),
                (x + cw // 2, y - ch // 3),
                (x + cw // 3, y + ctx.s(10)),
                (x - cw // 3, y + ctx.s(10)),
                (x - cw // 2, y - ch // 3),
            ]

            d.polygon(crystal, fill=rgba(col, 178), outline=rgba(p.light, 130))
            d.line([(x, y - ch), (x, y + ctx.s(6))], fill=rgba((255, 255, 255), 95), width=max(1, ctx.s(1)))

        for _ in range(ctx.py.randint(12, 23)):
            x = ctx.py.randint(cx - int(top_width * 0.40), cx + int(top_width * 0.40))
            y = cy + ctx.py.randint(-ctx.s(25), ctx.s(8))
            th = ctx.py.randint(ctx.s(25), ctx.s(46))

            d.line([(x, y), (x + ctx.py.randint(-ctx.s(5), ctx.s(5)), y - th)], fill=(54, 34, 26, 255), width=ctx.py.randint(max(2, ctx.s(3)), max(3, ctx.s(5))))

            for _ in range(7):
                ox = ctx.py.randint(-ctx.s(18), ctx.s(18))
                oy = ctx.py.randint(-ctx.s(16), ctx.s(12))
                rr = ctx.py.randint(ctx.s(9), ctx.s(18))
                leaf = mix(p.primary, p.light, ctx.py.random() * 0.25)
                d.ellipse([x + ox - rr, y - th + oy - rr, x + ox + rr, y - th + oy + rr], fill=rgba(leaf, 230))

        if {"castle", "tower", "temple", "city"} & ctx.tokens:
            bx = cx - ctx.s(55)
            by = cy - ctx.s(62)
            building_c = rgba(darken(p.dark, 0.02), 225)

            d.rectangle([bx, by, bx + ctx.s(110), cy], fill=building_c)

            for tx in [bx, bx + ctx.s(42), bx + ctx.s(84)]:
                d.rectangle([tx, by - ctx.s(48), tx + ctx.s(24), cy], fill=building_c)
                d.polygon([(tx - ctx.s(6), by - ctx.s(48)), (tx + ctx.s(12), by - ctx.s(76)), (tx + ctx.s(30), by - ctx.s(48))], fill=rgba(p.accent, 205))

        glow = Image.new("RGBA", (ctx.w, ctx.h), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow, "RGBA")
        max_r = int(ctx.w * 0.14 * ctx.plan.subject_scale)

        for rr in range(max_r, 0, -ctx.s(10)):
            gd.ellipse([cx - rr, cy + ctx.s(120) - rr // 2, cx + rr, cy + ctx.s(120) + rr // 2], fill=rgba(p.accent, int(38 * (rr / max_r) ** 2 * ctx.config.glow_strength)))

        img.alpha_composite(glow)
        img.alpha_composite(island)

    def product_scene(self, ctx: RenderContext, img: Image.Image):
        p = ctx.palette
        d = ImageDraw.Draw(img, "RGBA")

        floor_y = int(ctx.h * 0.76)
        d.rectangle([0, floor_y, ctx.w, ctx.h], fill=rgba(darken(p.dark, 0.12), 215))

        cx = ctx.w // 2
        base_y = int(ctx.h * 0.75)

        shadow = Image.new("RGBA", (ctx.w, ctx.h), (0, 0, 0, 0))
        sd = ImageDraw.Draw(shadow, "RGBA")
        sd.ellipse([cx - int(ctx.w * 0.20), base_y - ctx.s(20), cx + int(ctx.w * 0.20), base_y + ctx.s(30)], fill=(0, 0, 0, 110))
        img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(ctx.s(18))))

        bottle = {"bottle", "perfume", "cosmetic"} & ctx.tokens

        if bottle:
            bw = int(ctx.w * 0.18)
            bh = int(ctx.h * 0.46)
            x1 = cx - bw // 2
            y1 = base_y - bh

            d.rounded_rectangle([x1, y1, x1 + bw, base_y], radius=ctx.s(32), fill=rgba(lighten(p.dark, 0.08), 245), outline=rgba(p.light, 120), width=max(2, ctx.s(2)))
            d.rectangle([cx - bw // 5, y1 - ctx.s(50), cx + bw // 5, y1 + ctx.s(15)], fill=rgba(darken(p.dark, 0.02), 245), outline=rgba(p.light, 95))
            d.rectangle([cx - bw // 3, y1 - ctx.s(75), cx + bw // 3, y1 - ctx.s(45)], fill=rgba(p.accent, 220))
            label = [x1 + ctx.s(18), y1 + int(bh * 0.44), x1 + bw - ctx.s(18), y1 + int(bh * 0.72)]
        else:
            bw = int(ctx.w * 0.28)
            bh = int(ctx.h * 0.44)
            x1 = cx - bw // 2
            y1 = base_y - bh
            side = int(bw * 0.25)

            front = [(x1, y1), (x1 + bw, y1), (x1 + bw, base_y), (x1, base_y)]
            side_poly = [(x1 + bw, y1), (x1 + bw + side, y1 - ctx.s(35)), (x1 + bw + side, base_y - ctx.s(40)), (x1 + bw, base_y)]
            top_poly = [(x1, y1), (x1 + side, y1 - ctx.s(35)), (x1 + bw + side, y1 - ctx.s(35)), (x1 + bw, y1)]

            d.polygon(front, fill=rgba(lighten(p.dark, 0.10), 245), outline=rgba(p.light, 95))
            d.polygon(side_poly, fill=rgba(darken(p.mid, 0.10), 245), outline=rgba(p.light, 75))
            d.polygon(top_poly, fill=rgba(lighten(p.mid, 0.10), 245), outline=rgba(p.light, 75))
            label = [x1 + ctx.s(28), y1 + int(bh * 0.33), x1 + bw - ctx.s(28), y1 + int(bh * 0.68)]

        d.rounded_rectangle(label, radius=ctx.s(12), fill=rgba(mix(p.light, p.accent, 0.14), 235))

        font_title = get_font(ctx.s(30), bold=True)
        font_small = get_font(ctx.s(14), bold=False)

        draw_wrapped_text(d, ctx.config.title.upper(), ((label[0] + label[2]) // 2, label[1] + ctx.s(18)), label[2] - label[0] - ctx.s(20), font_title, rgba(darken(p.dark, 0.08), 245), ctx.s(4))
        draw_wrapped_text(d, ctx.config.style.upper(), ((label[0] + label[2]) // 2, label[3] - ctx.s(34)), label[2] - label[0] - ctx.s(20), font_small, rgba(darken(p.dark, 0.05), 170), ctx.s(2))

    def poster_scene(self, ctx: RenderContext, img: Image.Image):
        p = ctx.palette
        d = ImageDraw.Draw(img, "RGBA")

        for _ in range(18):
            x1 = ctx.py.randint(-ctx.w // 3, ctx.w)
            y1 = ctx.py.randint(0, ctx.h)
            x2 = x1 + ctx.py.randint(ctx.s(120), ctx.s(520))
            y2 = y1 + ctx.py.randint(-ctx.s(220), ctx.s(220))
            width = ctx.py.randint(ctx.s(12), ctx.s(55))
            col = ctx.py.choice([p.primary, p.accent, p.warm, p.light])
            d.line([(x1, y1), (x2, y2)], fill=rgba(col, ctx.py.randint(35, 120)), width=width)

        margin = int(min(ctx.w, ctx.h) * 0.08)
        d.rounded_rectangle([margin, margin, ctx.w - margin, ctx.h - margin], radius=ctx.s(36), outline=rgba(p.light, 95), width=max(2, ctx.s(3)), fill=rgba(darken(p.dark, 0.08), 90))

        cx, cy = ctx.w // 2, int(ctx.h * 0.43)
        max_r = int(min(ctx.w, ctx.h) * 0.22)

        for i in range(9):
            rr = max_r - i * ctx.s(18)
            if rr <= 0:
                continue
            col = [p.accent, p.primary, p.warm, p.light][i % 4]
            d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], outline=rgba(col, 155 - i * 12), width=max(1, ctx.s(4)))

        points = []
        sides = 7
        for i in range(sides):
            a = math.tau * i / sides - math.pi / 2
            rr = max_r * (0.78 + 0.22 * math.sin(i * 2.1 + ctx.seed))
            points.append((cx + int(math.cos(a) * rr), cy + int(math.sin(a) * rr)))

        d.polygon(points, fill=rgba(p.accent, 90), outline=rgba(p.light, 150))

        font_title = get_font(ctx.s(58), bold=True)
        font_sub = get_font(ctx.s(22), bold=False)

        draw_wrapped_text(d, ctx.config.title.upper(), (ctx.w // 2, int(ctx.h * 0.70)), int(ctx.w * 0.76), font_title, rgba(p.light, 245), ctx.s(8))
        subtitle = ctx.config.style.upper() + " / " + ctx.config.mood.upper()
        draw_wrapped_text(d, subtitle[:120], (ctx.w // 2, int(ctx.h * 0.84)), int(ctx.w * 0.70), font_sub, rgba(mix(p.light, p.accent, 0.30), 180), ctx.s(5))

    def space_scene(self, ctx: RenderContext, img: Image.Image):
        p = ctx.palette
        d = ImageDraw.Draw(img, "RGBA")

        for _ in range(int(1200 * ctx.w * ctx.h / (1400 * 900 * ctx.ss * ctx.ss))):
            x = ctx.py.randint(0, ctx.w)
            y = ctx.py.randint(0, ctx.h)
            r = ctx.py.choice([1, 1, 1, 2]) * ctx.ss
            d.ellipse([x - r, y - r, x + r, y + r], fill=rgba(p.light, ctx.py.randint(75, 240)))

        count = 1 if "planet" in ctx.tokens else ctx.py.randint(1, 3)

        for _ in range(count):
            cx = ctx.py.randint(int(ctx.w * 0.18), int(ctx.w * 0.85))
            cy = ctx.py.randint(int(ctx.h * 0.18), int(ctx.h * 0.70))
            r = ctx.py.randint(int(min(ctx.w, ctx.h) * 0.055), int(min(ctx.w, ctx.h) * 0.16))

            add_radial_glow(img, (cx, cy), p.accent, r * 4, 20 * ctx.style.glow)

            planet = Image.new("RGBA", (ctx.w, ctx.h), (0, 0, 0, 0))
            pd = ImageDraw.Draw(planet, "RGBA")
            pd.ellipse([cx - r, cy - r, cx + r, cy + r], fill=rgba(mix(p.primary, p.light, 0.25), 255))
            pd.ellipse([cx - r + int(r * 0.35), cy - r, cx + r + int(r * 0.35), cy + r], fill=rgba(darken(p.dark, 0.1), 145))

            if ctx.py.random() < 0.5 or "ring" in ctx.tokens:
                pd.ellipse([cx - int(r * 1.8), cy - int(r * 0.45), cx + int(r * 1.8), cy + int(r * 0.45)], outline=rgba(p.warm, 120), width=max(2, ctx.s(3)))

            img.alpha_composite(planet)

    def city_scene(self, ctx: RenderContext, img: Image.Image):
        p = ctx.palette
        d = ImageDraw.Draw(img, "RGBA")
        horizon = ctx.horizon_y

        x = -ctx.s(30)
        while x < ctx.w + ctx.s(40):
            bw = ctx.py.randint(ctx.s(35), ctx.s(115))
            bh = ctx.py.randint(int(ctx.h * 0.17), int(ctx.h * 0.58))
            y = horizon - bh
            c = darken(mix(p.dark, p.mid, ctx.py.random() * 0.45), ctx.py.random() * 0.12)

            d.rectangle([x, y, x + bw, horizon + ctx.s(10)], fill=rgba(c, 235))

            win_w = max(ctx.s(3), bw // ctx.py.randint(8, 14))
            win_h = max(ctx.s(4), ctx.s(8))

            for wx in range(x + ctx.s(7), x + bw - ctx.s(7), win_w * 2):
                for wy in range(y + ctx.s(12), horizon - ctx.s(10), win_h * 2):
                    if ctx.py.random() < 0.50:
                        wc = ctx.py.choice([p.accent, p.light, p.warm])
                        d.rectangle([wx, wy, wx + win_w, wy + win_h], fill=rgba(wc, ctx.py.randint(75, 210)))

            x += bw + ctx.py.randint(ctx.s(2), ctx.s(8))

        d.rectangle([0, horizon, ctx.w, ctx.h], fill=rgba(darken(p.dark, 0.15), 230))

        for _ in range(24):
            x = ctx.py.randint(0, ctx.w)
            y = ctx.py.randint(int(ctx.h * 0.25), max(int(ctx.h * 0.3), horizon))
            length = ctx.py.randint(ctx.s(18), ctx.s(95))
            color = ctx.py.choice([p.accent, p.light, p.warm])
            d.line([(x, y), (x + length, y)], fill=rgba(color, ctx.py.randint(90, 220)), width=max(1, ctx.s(3)))

    def abstract_scene(self, ctx: RenderContext, img: Image.Image):
        p = ctx.palette
        d = ImageDraw.Draw(img, "RGBA")

        for _ in range(90):
            cx = ctx.py.randint(-ctx.w // 10, int(ctx.w * 1.1))
            cy = ctx.py.randint(-ctx.h // 10, int(ctx.h * 1.1))
            r = ctx.py.randint(ctx.s(20), ctx.s(220))
            col = ctx.py.choice([p.primary, p.accent, p.light, p.warm])
            a = ctx.py.randint(12, 70)

            if ctx.py.random() < 0.5:
                d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=rgba(col, a), width=ctx.py.randint(1, max(2, ctx.s(5))))
            else:
                points = []
                sides = ctx.py.randint(3, 8)
                for i in range(sides):
                    ang = math.tau * i / sides + ctx.py.random() * 0.3
                    points.append((cx + int(math.cos(ang) * r), cy + int(math.sin(ang) * r)))
                d.polygon(points, outline=rgba(col, a), fill=rgba(col, a // 4))

    def emblem_scene(self, ctx: RenderContext, img: Image.Image):
        p = ctx.palette
        d = ImageDraw.Draw(img, "RGBA")

        add_radial_glow(img, (ctx.w // 2, ctx.h // 2), p.accent, int(min(ctx.w, ctx.h) * 0.42), 24 * ctx.style.glow)

        cx, cy = ctx.w // 2, ctx.h // 2
        r = int(min(ctx.w, ctx.h) * 0.31)

        for i in range(5):
            rr = r - i * ctx.s(18)
            d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], outline=rgba([p.light, p.accent, p.warm, p.primary, p.light][i], 190 - i * 25), width=max(2, ctx.s(3)))

        crest = [
            (cx, cy - r),
            (cx + int(r * 0.70), cy - int(r * 0.35)),
            (cx + int(r * 0.56), cy + int(r * 0.56)),
            (cx, cy + r),
            (cx - int(r * 0.56), cy + int(r * 0.56)),
            (cx - int(r * 0.70), cy - int(r * 0.35)),
        ]

        d.polygon(crest, fill=rgba(darken(p.dark, 0.05), 185), outline=rgba(p.light, 165))

        diamond = [
            (cx, cy - int(r * 0.55)),
            (cx + int(r * 0.42), cy),
            (cx, cy + int(r * 0.55)),
            (cx - int(r * 0.42), cy),
        ]

        d.polygon(diamond, fill=rgba(p.accent, 165), outline=rgba(p.light, 220))
        d.line([(cx, cy - int(r * 0.55)), (cx, cy + int(r * 0.55))], fill=rgba(p.light, 125), width=max(1, ctx.s(2)))
        d.line([(cx - int(r * 0.42), cy), (cx + int(r * 0.42), cy)], fill=rgba(p.light, 95), width=max(1, ctx.s(2)))

        font = get_font(ctx.s(34), bold=True)
        draw_wrapped_text(d, ctx.config.title.upper(), (cx, cy + int(r * 1.18)), int(ctx.w * 0.70), font, rgba(p.light, 225), ctx.s(5))

    def particles(self, ctx: RenderContext, img: Image.Image):
        if ctx.config.scene_type == "space":
            return

        p = ctx.palette
        layer = Image.new("RGBA", (ctx.w, ctx.h), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer, "RGBA")

        count = int(ctx.config.particle_amount * ctx.w * ctx.h / (1400 * 900 * ctx.ss * ctx.ss))

        for _ in range(count):
            x = ctx.py.randint(0, ctx.w)
            y = ctx.py.randint(0, ctx.h)
            r = ctx.py.choice([1, 1, 1, 2, 2, 3]) * ctx.ss
            dist = math.dist((x, y), ctx.sun_xy)
            sun_bonus = max(0.0, 1.0 - dist / (650 * ctx.ss))
            a = int(ctx.py.randint(10, 68) * (0.45 + sun_bonus))
            d.ellipse([x - r, y - r, x + r, y + r], fill=rgba(p.light, a))

        img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(max(0.4, ctx.ss * 0.4))))

    def postprocess(self, ctx: RenderContext, img: Image.Image) -> Image.Image:
        if ctx.style.final_blur > 0:
            img = img.filter(ImageFilter.GaussianBlur(ctx.style.final_blur * ctx.ss))

        arr = np.array(img).astype(np.int16)

        if ctx.style.grain > 0:
            grain = ctx.rng.normal(0, ctx.style.grain, arr.shape).astype(np.int16)
            arr[:, :, :3] += grain[:, :, :3]

        arr = np.clip(arr, 0, 255).astype(np.uint8)
        img = Image.fromarray(arr, "RGBA")

        yy, xx = np.mgrid[0:ctx.h, 0:ctx.w]
        dx = (xx - ctx.w / 2) / (ctx.w / 2)
        dy = (yy - ctx.h / 2) / (ctx.h / 2)
        dist = np.sqrt(dx * dx + dy * dy)

        vignette = clamp01((dist - 0.38) / 0.78)
        alpha = (vignette * ctx.style.vignette).astype(np.uint8)

        vig = np.zeros((ctx.h, ctx.w, 4), dtype=np.uint8)
        vig[:, :, 3] = alpha
        img.alpha_composite(Image.fromarray(vig, "RGBA"))

        img = img.filter(ImageFilter.UnsharpMask(radius=max(1.0, 1.25 * ctx.ss), percent=105, threshold=3))
        img = ImageEnhance.Contrast(img).enhance(ctx.style.contrast)
        img = ImageEnhance.Color(img).enhance(ctx.style.saturation)

        img = downsample(ctx, img)
        return img.convert("RGB")


class ExportSystem:
    def save_result(self, result: RenderResult, out_dir: str | Path, prefix="eli", name_from_prompt=True) -> Path:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        title = sanitize_filename(result.config.title, 40) if name_from_prompt else "image"
        fmt = result.config.output_format.lower().strip(".") or "png"

        if fmt not in {"png", "jpg", "jpeg"}:
            fmt = "png"

        ext = "jpg" if fmt == "jpeg" else fmt

        base = f"{prefix}_{result.config.variant:03d}_{title}_{result.config.scene_type}_{result.palette.name}_seed{result.config.seed}"
        path = out_dir / f"{base}.{ext}"

        if ext == "png":
            result.image.save(path)
        else:
            result.image.save(path, quality=95)

        if result.config.export_metadata:
            self.save_metadata(result, out_dir / f"{base}.json")

        if result.config.export_layers and result.layers:
            layer_dir = out_dir / f"{base}_layers"
            layer_dir.mkdir(parents=True, exist_ok=True)
            for name, layer in result.layers.items():
                layer.save(layer_dir / f"{name}.png")

        return path

    def save_metadata(self, result: RenderResult, path: str | Path):
        data = {
            "config": asdict(result.config),
            "palette": asdict(result.palette),
            "style": asdict(result.style),
            "composition_plan": asdict(result.plan),
            "metadata": result.metadata,
            "recreate_hint": {
                "seed": result.config.seed,
                "variant": result.config.variant,
                "prompt": result.config.prompt,
                "scene_type": result.config.scene_type,
                "palette": result.palette.name,
                "style": result.style.name,
            },
        }

        Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")

    def contact_sheet(self, image_paths: List[Path], out_path: str | Path, thumb_w=360):
        if not image_paths:
            return

        images = [Image.open(p).convert("RGB") for p in image_paths]
        aspect = images[0].height / images[0].width
        thumb_h = int(thumb_w * aspect)

        cols = math.ceil(math.sqrt(len(images)))
        rows = math.ceil(len(images) / cols)

        sheet = Image.new("RGB", (cols * thumb_w, rows * thumb_h), (18, 18, 24))

        for i, img in enumerate(images):
            thumb = img.resize((thumb_w, thumb_h), LANCZOS)
            x = (i % cols) * thumb_w
            y = (i // cols) * thumb_h
            sheet.paste(thumb, (x, y))

        sheet.save(out_path, quality=95)


class ImageGenerator:
    def __init__(self):
        self.project_analyzer = ProjectAnalyzer()
        self.prompt_interpreter = PromptInterpreter()
        self.style_system = StyleSystem()
        self.composition_planner = CompositionPlanner()
        self.renderer = ProceduralRenderer()
        self.exporter = ExportSystem()

    def render_result(self, config: SceneConfig, project: Optional[ProjectContext] = None) -> RenderResult:
        if config.scene_type == "auto":
            config = self.prompt_interpreter.interpret(config.prompt, base=config, project=project, forced_type="auto")

        palette = self.style_system.choose_palette(config, project)
        style = self.style_system.choose_style(config)
        plan = self.composition_planner.plan(config)

        return self.renderer.render(config, palette, style, plan)

    def render(self, config: SceneConfig) -> Image.Image:
        return self.render_result(config).image

    def render_prompt(self, prompt: str, **overrides) -> Image.Image:
        config = self.prompt_interpreter.interpret(prompt)
        config = self._apply_overrides(config, overrides)
        return self.render_result(config).image

    def render_batch(self, prompt: str, count: int = 1, seed: int = 77, project_folder: Optional[str] = None, forced_type: str = "auto", **overrides) -> List[RenderResult]:
        project = self.project_analyzer.analyze(project_folder)
        base = self.prompt_interpreter.interpret(prompt, project=project, forced_type=forced_type)
        base = self._apply_overrides(base, overrides)

        results = []

        for i in range(count):
            cfg = replace(base)
            cfg.seed = seed + i * 7919
            cfg.variant = i
            results.append(self.render_result(cfg, project=project))

        return results

    def render_project(self, folder: str, prompt: str = "", count: int = 1, seed: int = 77, forced_type: str = "auto", **overrides) -> List[RenderResult]:
        return self.render_batch(prompt=prompt, count=count, seed=seed, project_folder=folder, forced_type=forced_type, **overrides)

    def _apply_overrides(self, config: SceneConfig, overrides: Dict[str, Any]) -> SceneConfig:
        for key, value in overrides.items():
            if value is None:
                continue
            if hasattr(config, key):
                setattr(config, key, value)
        return config
