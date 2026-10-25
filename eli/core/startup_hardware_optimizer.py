"""A model's trained context, the context free RAM holds, and the reasoning-mode budgets sized from the
context that loaded. What loads where is planned by eli/core/load_plan.py; the machine is read by
eli/core/hardware_profile.py."""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

from eli.utils.log import get_logger

log = get_logger(__name__)


def detect_available_ram_gb() -> float:
    """Currently free RAM — the binding budget for CPU-only inference. 0.0 when it cannot be read."""
    from eli.core.hardware_profile import system_ram_gib
    return round(system_ram_gib()[1], 2)


_MIN_CTX = 4096
# A proportion of measured memory, not a size band: a machine with twice the
# RAM gets twice the allowance, with no thresholds to fall between.
_RAM_FRACTION_FOR_CTX = 0.25


def _ctx_ceiling_for_ram(ram_gb: float, size_gb: float, train_ctx: int = 0,
                         model_path: Optional[str] = None) -> int:
    """Largest context this machine's RAM can hold for a model this size.

    The per-token cost comes from hardware_profile._kv_cache_mb — the same
    measured KV arithmetic the loader uses — rather than a constant invented
    here. An earlier draft of this function DID invent one, and it implied an
    18k context on an 8GB machine. A model's own trained window is the only
    honest ceiling above that (0: unknown, RAM alone sets it).
    """
    try:
        from eli.core.hardware_profile import _kv_cache_mb, _layers_for_size, model_cost
        layers = _layers_for_size(float(size_gb))
        mb_per_token = _kv_cache_mb(1, layers, quant=False, cost=model_cost(model_path))
    except Exception:
        return _MIN_CTX
    if mb_per_token <= 0:
        return _MIN_CTX
    # ram_gb is AVAILABLE headroom — subtract model weights + runtime reserve first,
    # then size KV from what remains. Ignoring model size over-estimates ctx on
    # low-RAM CPU-only hosts (e.g. integrated-GPU laptops with ~4–8 GB RAM).
    _model_mb = max(0.0, float(size_gb)) * 1024.0 * 1.08
    _runtime_mb = 512.0
    _net_mb = max(0.0, float(ram_gb) * 1024.0 - _model_mb - _runtime_mb)
    allowance_mb = _net_mb * _RAM_FRACTION_FOR_CTX
    ceiling = max(_MIN_CTX, int(allowance_mb / mb_per_token))
    train = int(train_ctx or 0)
    return min(ceiling, train) if train > 0 else ceiling


def cpu_ctx_ceiling_from_ram(model_gb: float, train_ctx: int = 0, model_path: Optional[str] = None) -> int:
    """Largest ctx this machine's available RAM can hold for this model."""
    return int(_ctx_ceiling_for_ram(detect_available_ram_gb(), float(model_gb), int(train_ctx or 0),
                                    model_path=model_path))


_TRAIN_CTX_CACHE: dict = {}


def _gguf_metadata_ctx(model_path: str) -> int:
    """Read the model's REAL trained context (`<arch>.context_length`) from the GGUF
    header via a cheap vocab-only load. Cached per path; returns 0 if unavailable.

    This is the authoritative source — the filename table below is wrong both ways
    (it missed eli-finetuned-phi3's 4096 and phi-4's 16384, sending ELI's loader to
    32768 → failed GPU loads → CPU-garbage). Model-agnostic: any GGUF carries this.
    """
    key = str(model_path)
    if key in _TRAIN_CTX_CACHE:
        return _TRAIN_CTX_CACHE[key]
    val = 0
    try:
        from eli.cognition.model_load_diagnostics import gguf_model_profile
        prof = gguf_model_profile(model_path)
        if prof.context_length and prof.context_length > 0:
            val = int(prof.context_length)
    except Exception:
        val = 0
    if not val:
        try:
            from llama_cpp import Llama
            _m = Llama(model_path=str(model_path), vocab_only=True, verbose=False)
            md = getattr(_m, "metadata", None) or {}
            arch = str(md.get("general.architecture") or "").strip()
            raw = md.get(f"{arch}.context_length") or md.get("context_length")
            if raw is not None:
                val = int(str(raw).strip())
            try:
                del _m
            except Exception:
                log.debug("suppressed exception", exc_info=True)
        except Exception:
            val = 0
    _TRAIN_CTX_CACHE[key] = val
    return val


def train_ctx_for_model(model_path: str) -> int:
    """Return the model's native training context length.

    Order: ELI_MODEL_TRAIN_CTX env override → real GGUF metadata (authoritative) →
    conservative default when metadata is unreadable. No brand/filename table —
    redistributed GGUFs must not depend on marketing names in the path.
    """
    forced = os.environ.get("ELI_MODEL_TRAIN_CTX", "").strip()
    if forced:
        return int(forced)

    # Authoritative: the model's own embedded context_length.
    try:
        _meta_ctx = _gguf_metadata_ctx(model_path)
        if _meta_ctx and _meta_ctx > 0:
            return int(_meta_ctx)
    except Exception:
        log.debug("suppressed exception", exc_info=True)

    # Metadata missing/unreadable — do not invent a brand-based window.
    return 8192


def max_tokens_from_ctx(n_ctx: int) -> int:
    """Max generation tokens: half the context window. A ceiling only: each generation sizes its
    own budget from the prompt (it was clamped to 1024..8192 whatever the window)."""
    return max(1, int(n_ctx) // 2)


def resize_budgets_to_effective_ctx(effective_ctx: int) -> Dict[str, Any]:
    """Re-derive max_tokens + mode_presets from the context that ACTUALLY loaded.

    `max_tokens` and `mode_presets` are computed here from the tuner's recommended
    n_ctx and written to the canonical settings keys. But the tuner's n_ctx is only
    a recommendation — the loader is free to override it and routinely does, because
    the two use opposite reduction rules: the tuner cuts ctx to fit the KV budget
    while holding GPU layers, and `smart_fit_config` sheds layers and batch first,
    cutting ctx last. n_ctx itself is protected from that mismatch (it stays the
    user's, with the tuner's value filed under hw_profile_n_ctx); the budgets
    derived FROM it were not.

    Observed live at 2.1.82: the tuner derived the five reasoning modes from
    ctx=4096 while the model ran at ctx=10384, so every mode planned against less
    than half the context that was pinned — 2 self-consistency samples and 2 tree
    branches instead of 3, under a 2048-token ceiling instead of 5192.

    Called after the load settles, when the effective ctx is known. Returns the
    settings delta actually written; {} when nothing needed to change.
    """
    ctx = int(effective_ctx or 0)
    if ctx <= 0:
        return {}

    from eli.core.runtime_settings import load_settings as _load, save_settings as _save

    settings = dict(_load() or {})
    want_max_tokens = max_tokens_from_ctx(ctx)
    want_presets = mode_presets(ctx, want_max_tokens)

    delta: Dict[str, Any] = {}
    if int(settings.get("max_tokens") or 0) != int(want_max_tokens):
        delta["max_tokens"] = want_max_tokens
    if (settings.get("mode_presets") or {}) != want_presets:
        delta["mode_presets"] = want_presets
    if not delta:
        return {}

    settings.update(delta)
    # Record what the budgets were sized against, so a later reader can tell
    # whether they still match the running context without recomputing.
    settings["mode_presets_ctx"] = ctx
    _save(settings)
    return delta


def mode_presets(n_ctx: int, max_tokens: int) -> Dict[str, Dict[str, Any]]:
    # Model-agnostic capability scaling: a bigger model gets more samples, wider and deeper search
    # and larger stage budgets. tier_scale() is 1.0 for the current small model and rises (medium
    # 1.5, large 2.5, frontier 4.0) as a larger GGUF loads.
    try:
        from eli.core.model_tier import tier_scale as _ts
        _scale = float(_ts())
    except Exception:
        _scale = 1.0

    def _cnt(base: int, lo: int, hi: int) -> int:
        return max(lo, min(hi, int(round(base * _scale))))

    def _tok(base: int) -> int:
        return min(max_tokens, int(round(base * _scale)))

    # Tree depth is tier-mapped so the SMALL model stays single-level (depth 1 = current
    # behaviour) and only capable models deepen the tree: small 1, medium 2, large 3, frontier 4.
    _depth = 1 if _scale < 1.5 else (2 if _scale < 2.5 else (3 if _scale < 4.0 else 4))

    return {
        "quick": {
            # No output ceiling. "quick" means one pass with minimal retrieval, not a cut-short answer, and
            # max_tokens is a ceiling anyway. These were a flat 1024/3072 while every other preset scaled,
            # so a 30B model got a 7B budget. The real limit is applied per call in
            # gguf_inference._fit_generation_budget.
            "max_tokens": max_tokens,
            "passes": 1,
            "memory_depth": "minimal",
        },
        "standard": {
            "max_tokens": max_tokens,
            "passes": 1,
            "memory_depth": "normal",
        },
        "cot": {
            "max_tokens": max_tokens,
            "passes": 1,
            "memory_depth": "normal",
        },
        "self_consistency": {
            "samples": _cnt(3 if n_ctx >= 8192 else 2, 2, 7),
            "max_tokens_per_sample": _tok(2048),
            "max_tokens_final": _tok(3072),
        },
        "tree_of_thoughts": {
            "branches": _cnt(3 if n_ctx >= 8192 else 2, 2, 6),
            "depth": _depth,
            "max_tokens_propose": _tok(1024),
            "max_tokens_develop": _tok(3072),
            "max_tokens_critique": _tok(1024),
            "max_tokens_revise": max_tokens,
        },
        "constitutional_ai": {
            "max_tokens_generate": _tok(3072),
            "max_tokens_critique": _tok(1024),
            "max_tokens_revise": max_tokens,
            "max_tokens": max_tokens,
        },
    }
