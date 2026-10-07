from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from eli.utils.log import get_logger

log = get_logger(__name__)


def _root() -> Path:
    try:
        from eli.core.paths import canonical_root
        return canonical_root(Path(__file__).resolve().parents[2])
    except Exception:
        return Path(__file__).resolve().parents[2]


def _artifacts_dir() -> Path:
    """The artifacts dir the loader actually writes to (honours the override)."""
    try:
        from eli.core.paths import get_paths as _gp
        return Path(_gp().artifacts_dir)
    except Exception:
        return _root() / "artifacts"


def _snapshot() -> dict[str, Any]:
    path = _artifacts_dir() / "runtime_snapshot.json"
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}


def context_size(default: int = 0) -> int:
    """The context window in use: ELI_CONTEXT_SIZE when set, else what loaded, else the setting
    or auto for this model (gguf_inference.context_window). `default` only when none is known."""
    try:
        forced = int(os.environ.get("ELI_CONTEXT_SIZE") or 0)
        if forced > 0:
            return forced
    except Exception:
        log.debug("suppressed exception", exc_info=True)
    # Only when already imported: importing it loads llama.cpp, which must not happen before the
    # GPU pack is in place, and budgets here are read at import time.
    _gi = sys.modules.get("eli.cognition.gguf_inference")
    if _gi is not None:
        try:
            value = int(_gi.context_window() or 0)
            if value > 0:
                return value
        except Exception:
            log.debug("suppressed exception", exc_info=True)
    snap = _snapshot()
    for key in ("n_ctx", "effective_context_size", "context_size"):
        try:
            value = int((snap.get("effective") or {}).get(key) or snap.get(key) or 0)
            if value > 0:
                return value
        except Exception:
            log.debug("suppressed exception", exc_info=True)
    try:
        from eli.core.runtime_settings import load_settings
        value = int((load_settings() or {}).get("n_ctx") or 0)
        if value > 0:
            return value
    except Exception:
        log.debug("suppressed exception", exc_info=True)
    return int(default)


# Budget defaults below are written as characters per this many tokens of context, and scale
# with the window in use in both directions.
_BUDGET_REFERENCE_CTX = 8192


def budget(name: str, default: int, *, floor: int | None = None, ceiling: int | None = None) -> int:
    env_name = "ELI_BUDGET_" + str(name or "").upper()
    try:
        if os.environ.get(env_name):
            value = int(os.environ[env_name])
        else:
            ctx = context_size()
            # proportional: a smaller window gets less (a floor of 1x overflowed small models),
            # a large one more (a cap of 4x left a 128k window sized like 32k)
            scale = (ctx / float(_BUDGET_REFERENCE_CTX)) if ctx > 0 else 1.0
            value = int(round(float(default) * scale))
    except Exception:
        value = int(default)
    if floor is not None:
        value = max(int(floor), value)
    if ceiling is not None:
        value = min(int(ceiling), value)
    return int(value)


def timeout(name: str, default: float) -> float:
    env_name = "ELI_TIMEOUT_" + str(name or "").upper()
    try:
        if os.environ.get(env_name):
            return max(0.1, float(os.environ[env_name]))
        ctx = context_size()
        # a quarter more time per doubling of the window past the reference, continuous (it was
        # steps at 16k and 32k and flat beyond)
        if ctx <= _BUDGET_REFERENCE_CTX:
            return float(default)
        import math
        return float(default) * (1.0 + 0.25 * math.log2(ctx / float(_BUDGET_REFERENCE_CTX)))
    except Exception:
        return float(default)


def tts_chunk_chars(default: int = 360) -> int:
    try:
        return budget("tts_chunk_chars", default, floor=180, ceiling=900)
    except Exception:
        return int(default)
