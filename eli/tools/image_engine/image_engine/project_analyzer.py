from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from . import visual_core as core


def color_to_hex(color: core.Color) -> str:
    return "#{:02x}{:02x}{:02x}".format(*color)


def analyze_project_profile(path: str | Path | None) -> dict[str, Any]:
    context = core.analyze_project_folder(str(path or ""))
    tags = [t for t, _ in Counter(context.tags).most_common(40)]
    colors = context.colors[:12]

    profile = {
        "path": str(path or ""),
        "file_count": len(context.files),
        "text_chars": len(context.text),
        "tags": tags,
        "dominant_colors_rgb": colors,
        "dominant_colors_hex": [color_to_hex(c) for c in colors],
        "style_hints": infer_style_hints(context.text, tags),
        "files_sample": context.files[:30],
    }
    return profile


def infer_style_hints(text: str, tags: list[str]) -> list[str]:
    joined = (" ".join(tags) + " " + (text or "")).lower()
    hints = []
    for word in [
        "dark", "neon", "luxury", "minimal", "cinematic", "mythic", "technical",
        "premium", "nature", "space", "cyber", "brand", "poster", "logo", "data",
    ]:
        if word in joined:
            hints.append(word)
    return hints[:20]
