"""Model-capability tier — the single signal that lets ELI's cognition budgets
auto-scale to whatever model is loaded, so a bigger/smarter local model is used
to its potential instead of staying throttled for a small one.

Tier is inferred from the loaded GGUF's file size (a robust, always-available
proxy that needs no loaded model and no metadata):

    small    < 8 GB    (≈ ≤8B, or small quant)   scale 1.0  ← current default
    medium   8–20 GB   (≈ 13–32B)                scale 1.5
    large    20–55 GB  (≈ 34–70B)                scale 2.5
    frontier > 55 GB   (≈ 100B+)                 scale 4.0

`tier_scale()` is what the budget code multiplies by (synthesis prompt cap,
gather limits, …). For the current 7B it is 1.0 → fully behaviour-preserving;
the scaling only activates once a larger model is dropped in. Tunable/overridable
via the `ELI_MODEL_TIER` env var (small|medium|large|frontier).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

_TIER_SCALE = {"small": 1.0, "medium": 1.5, "large": 2.5, "frontier": 4.0}
_TIER_BY_GB = (  # (min_gb, tier) — first match from largest down
    (55.0, "frontier"),
    (20.0, "large"),
    (8.0, "medium"),
    (0.0, "small"),
)

# Cache: model path str -> tier (file size doesn't change at runtime)
_CACHE: dict = {}


def _model_path() -> Optional[Path]:
    try:
        from eli.cognition.gguf_inference import get_model_path
        return get_model_path()
    except Exception:
        return None


def _file_gb(p: Optional[Path]) -> float:
    try:
        if p and Path(p).exists():
            return Path(p).stat().st_size / (1024.0 ** 3)
    except Exception:
        pass
    return 0.0


def detect_tier() -> str:
    """Capability tier of the currently-configured model. Defaults to 'small'
    (the safe, behaviour-preserving default) when the model can't be sized."""
    env = os.environ.get("ELI_MODEL_TIER", "").strip().lower()
    if env in _TIER_SCALE:
        return env
    p = _model_path()
    key = str(p or "")
    if key in _CACHE:
        return _CACHE[key]
    gb = _file_gb(p)
    tier = "small"
    if gb > 0:
        for min_gb, t in _TIER_BY_GB:
            if gb >= min_gb:
                tier = t
                break
    _CACHE[key] = tier
    return tier


def tier_scale(tier: Optional[str] = None) -> float:
    """Budget multiplier for the tier (1.0 = small = current default)."""
    return float(_TIER_SCALE.get(tier or detect_tier(), 1.0))


def clear_cache() -> None:
    _CACHE.clear()


__all__ = ["detect_tier", "tier_scale", "clear_cache"]
