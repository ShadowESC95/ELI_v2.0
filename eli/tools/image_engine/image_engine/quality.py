from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

try:
    import numpy as np
except ImportError:
    np = None  # type: ignore[assignment]
try:
    from PIL import Image, ImageStat
except ImportError:
    Image = ImageStat = None  # type: ignore[assignment]


def image_hash(path: str | Path, size: int = 8) -> str:
    """Return a compact average hash for duplicate/near-duplicate lookup."""
    with Image.open(path) as img:
        gray = img.convert("L").resize((size, size))
    arr = np.asarray(gray, dtype=np.float32)
    bits = arr > arr.mean()
    value = 0
    for bit in bits.flatten():
        value = (value << 1) | int(bit)
    return f"{value:0{size * size // 4}x}"


def file_sha256(path: str | Path, block_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        while True:
            block = f.read(block_size)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def score_image(path: str | Path) -> dict[str, Any]:
    """Score a rendered image using lightweight visual heuristics.

    Scores are intentionally simple and deterministic. They are useful for
    ranking local candidates, not for judging aesthetics absolutely.
    """
    with Image.open(path) as img:
        rgb = img.convert("RGB")
        rgb.thumbnail((768, 768))
        arr = np.asarray(rgb, dtype=np.float32) / 255.0
        gray = np.asarray(rgb.convert("L"), dtype=np.float32) / 255.0

    # Sharpness: average squared gradient magnitude.
    gy, gx = np.gradient(gray)
    sharpness = float(np.mean(gx * gx + gy * gy) * 350.0)

    # Contrast and color richness.
    contrast = float(np.std(gray) * 2.2)
    saturation = float(np.mean(np.max(arr, axis=2) - np.min(arr, axis=2)) * 1.8)

    # Exposure penalizes severely under/overexposed images.
    exposure = float(1.0 - abs(np.mean(gray) - 0.50) * 1.8)

    # Entropy-like spread.
    hist, _ = np.histogram(gray, bins=64, range=(0.0, 1.0), density=True)
    hist = hist / max(hist.sum(), 1e-9)
    entropy = float(-(hist * np.log2(hist + 1e-9)).sum() / 6.0)

    components = {
        "sharpness": max(0.0, min(1.0, sharpness)),
        "contrast": max(0.0, min(1.0, contrast)),
        "saturation": max(0.0, min(1.0, saturation)),
        "exposure": max(0.0, min(1.0, exposure)),
        "entropy": max(0.0, min(1.0, entropy)),
    }
    score = (
        components["sharpness"] * 0.20
        + components["contrast"] * 0.23
        + components["saturation"] * 0.17
        + components["exposure"] * 0.15
        + components["entropy"] * 0.25
    ) * 100.0

    return {
        "score": round(float(score), 3),
        "components": {k: round(v, 4) for k, v in components.items()},
        "average_hash": image_hash(path),
        "sha256": file_sha256(path),
    }


def choose_best(scored_paths: list[tuple[Path, dict[str, Any]]]) -> Path | None:
    if not scored_paths:
        return None
    return max(scored_paths, key=lambda item: float(item[1].get("score", 0.0)))[0]
