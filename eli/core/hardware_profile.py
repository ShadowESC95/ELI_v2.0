"""
eli.core.hardware_profile — auto-detect optimal runtime configuration.

Single source of truth for runtime tuning across CLI, GUI, and executor,
using a free-VRAM-aware hardware profile.

Free-VRAM aware: queries `nvidia-smi --query-gpu=memory.free` instead
of memory.total. Critical because the X server, browser, games, etc
all consume VRAM before ELI launches. Fitting based on total VRAM
oversubscribes and OOMs.

KV-cache overhead aware: GPU layer count accounts for the KV cache
(~6KB per token per layer) plus 350MB CUDA runtime overhead. Without
this, ELI loads "successfully" then OOMs on the first long prompt.

- detect_hardware()       → HardwareProfile (cpu_threads, ram_gb,
                            available_ram_gb, has_gpu, gpu_name,
                            free_vram_mb, total_vram_mb)
- discover_models()       → list of installed GGUF models
- recommend(hw, models)   → ModelRecommendation
- apply_recommendation()  → writes flat keys to config/settings.json
- run_benchmark()         → full detect + recommend + return

Writes simple flat keys (model_path, n_ctx, n_gpu_layers, batch_size,
n_threads, use_mmap, use_mlock, provider) to settings.json. NEVER
writes mode_profiles or active_mode.
"""
from __future__ import annotations

import os
import sys
import json
import shutil
import subprocess
import multiprocessing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


# KV-cache overhead constants (matched against eli/gui/app.py — keep in sync)
_KV_BYTES_PER_TOKEN_PER_LAYER = 6_000
_CUDA_OVERHEAD_MB = 350


def _kv_cache_mb(n_ctx: int, n_layers: int = 32, quant: bool = False) -> float:
    raw = n_ctx * n_layers * _KV_BYTES_PER_TOKEN_PER_LAYER / 1_048_576
    return raw / 4 if quant else raw


def _layers_for_size(size_gb: float) -> int:
    """Total transformer layers heuristic by model size (GB)."""
    if size_gb < 1.5:   return 22
    if size_gb < 3.0:   return 28
    if size_gb < 6.0:   return 32
    if size_gb < 12.0:  return 40
    return 48


@dataclass
class HardwareProfile:
    cpu_threads: int = 1
    ram_gb: float = 8.0
    available_ram_gb: float = 8.0
    has_gpu: bool = False
    gpu_name: str = ""
    free_vram_mb: int = 0       # FREE VRAM, not total
    total_vram_mb: int = 0
    vram_gb: float = 0.0        # convenience: free_vram_mb / 1024 (legacy callers)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cpu_threads": self.cpu_threads,
            "ram_gb": round(self.ram_gb, 1),
            "available_ram_gb": round(self.available_ram_gb, 1),
            "has_gpu": self.has_gpu,
            "gpu_name": self.gpu_name,
            "free_vram_mb": self.free_vram_mb,
            "total_vram_mb": self.total_vram_mb,
            "vram_gb": round(self.vram_gb, 1),
        }


@dataclass
class ModelRecommendation:
    model_path: str = ""
    model_name: str = ""
    model_size_gb: float = 0.0
    n_gpu_layers: int = 0
    n_ctx: int = 4096
    n_threads: int = 1
    batch_size: int = 256
    max_tokens: int = -1
    temperature: float = 0.7
    use_mmap: bool = True
    use_mlock: bool = False
    provider: str = "custom_gguf"
    cache_type_k: str = ""
    cache_type_v: str = ""
    mode_presets: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    reasoning: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_path": self.model_path,
            "model_name": self.model_name,
            "model_size_gb": round(self.model_size_gb, 2),
            "n_gpu_layers": self.n_gpu_layers,
            "n_ctx": self.n_ctx,
            "n_threads": self.n_threads,
            "batch_size": self.batch_size,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "use_mmap": self.use_mmap,
            "use_mlock": self.use_mlock,
            "provider": self.provider,
            "cache_type_k": self.cache_type_k,
            "cache_type_v": self.cache_type_v,
            "mode_presets": dict(self.mode_presets),
            "reasoning": list(self.reasoning),
        }


def _derive_mode_presets(base_n_ctx: int, base_max_tokens: int,
                         base_temperature: float) -> Dict[str, Dict[str, Any]]:
    """Derive per-reasoning-mode parameters from the base hardware-aware tune.

    Each mode gets per-stage `max_tokens`, a `temperature` shaped to the
    mode's intent (cooler for analytic, warmer for sampling), a `passes`
    or `samples` count, and a `voice` descriptor that tells the engine
    how to phrase the system-prompt suffix for that mode. Computed FROM
    the base ctx, never hard-coded numbers.

    Quick is the reference — full ctx, full max_tokens, single pass.
    Other modes carve their per-stage budget out of the base so total
    work fits in one ctx window.
    """
    base_max = max(512, int(base_max_tokens) if base_max_tokens > 0 else 2048)

    return {
        "quick": {
            "passes": 1,
            "max_tokens": base_max,
            "temperature": float(base_temperature),
            "top_p": 0.90,
            "top_k": 40,
            "threshold": 0.54,
            "voice": (
                "Direct, single-pass. Answer the question. No staged "
                "reasoning. No self-narration about your process."
            ),
        },
        "chain_of_thought": {
            "passes": 1,
            "max_tokens": int(base_max * 0.85),
            "temperature": max(0.3, float(base_temperature) - 0.2),
            "top_p": 0.85,
            "top_k": 40,
            "threshold": 0.60,
            "voice": (
                "Use structured hidden reasoning. Output final answer only. "
                "State assumptions only when useful for the visible answer. End with the "
                "final answer clearly separated from the reasoning."
            ),
        },
        "self_consistency": {
            "passes": 1,                       # algorithm runs samples internally
            "samples": 3,
            "max_tokens": int(base_max * 0.55),  # per-sample budget
            "temperature": max(0.6, float(base_temperature)),
            "top_p": 0.85,
            "top_k": 50,
            "threshold": 0.65,
            "voice": (
                "Reason independently each time. Don't anchor on prior "
                "phrasings. The selection stage will pick the most "
                "defensible across samples."
            ),
        },
        "tree_of_thoughts": {
            "passes": 1,                       # algorithm runs branch+develop
            "branches": 3,
            "max_tokens_propose": int(base_max * 0.30),
            "max_tokens_develop": int(base_max * 0.85),
            "temperature_propose": 0.6,
            "temperature_develop": max(0.3, float(base_temperature) - 0.3),
            "top_p": 0.80,
            "top_k": 30,
            "threshold": 0.70,
            "voice": (
                "Branch first, commit second. Each candidate approach is "
                "named, evaluated on feasibility, then the strongest is "
                "developed in full. Do not solve in the proposal phase."
            ),
        },
        "constitutional_ai": {
            "passes": 1,                       # algorithm runs gen→critique→revise
            "stages": ["generate", "critique", "revise"],
            "max_tokens_generate": int(base_max * 0.85),
            "max_tokens_critique": int(base_max * 0.30),
            "max_tokens_revise":   int(base_max * 0.85),
            "temperature": max(0.2, float(base_temperature) - 0.4),
            "top_p": 0.85,
            "top_k": 30,
            "threshold": 0.68,
            "voice": (
                "Generate carefully, then critique your own draft against "
                "the principles, then revise. The critique pass is "
                "honest, not theatrical — only fail principles when they "
                "actually fail."
            ),
        },
    }


def detect_hardware() -> HardwareProfile:
    """Probe the host for CPU/RAM/free-VRAM. Reads FREE VRAM from nvidia-smi."""
    hw = HardwareProfile()
    hw.cpu_threads = multiprocessing.cpu_count()

    # RAM total + available
    try:
        import psutil
        vm = psutil.virtual_memory()
        hw.ram_gb = vm.total / 1e9
        hw.available_ram_gb = vm.available / 1e9
    except Exception:
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        hw.ram_gb = int(line.split()[1]) / 1_048_576
                    elif line.startswith("MemAvailable:"):
                        hw.available_ram_gb = int(line.split()[1]) / 1_048_576
        except Exception:
            pass

    # FREE VRAM — critical for GPU layer counts. Display server, browser,
    # games, etc all consume VRAM before ELI launches. Total VRAM
    # oversubscribes and OOMs.
    try:
        out = subprocess.check_output(
            ["nvidia-smi",
             "--query-gpu=memory.free,memory.total,name",
             "--format=csv,noheader,nounits"],
            stderr=subprocess.DEVNULL, timeout=5
        ).decode().strip().splitlines()
        if out:
            parts = [p.strip() for p in out[0].split(",")]
            hw.free_vram_mb = int(parts[0])
            hw.total_vram_mb = int(parts[1])
            hw.gpu_name = parts[2] if len(parts) > 2 else "NVIDIA GPU"
            hw.vram_gb = hw.free_vram_mb / 1024.0
            hw.has_gpu = True
    except Exception:
        pass

    if not hw.has_gpu and not hw.gpu_name:
        hw.gpu_name = "CPU only"

    return hw


def _is_embedder_path(path: Path) -> bool:
    """Heuristic: paths under `models/embeddings/` or names containing
    embed-only signatures are NOT chat models and must never be selected
    as the main GGUF by `recommend()`. Detected by Jay 2026-05-11 — the
    profiler picked `nomic-embed-text-v1.5.Q4_K_M.gguf` as the chat model
    and broke the next launch."""
    name = path.name.lower()
    parts = {p.lower() for p in path.parts}
    if "embeddings" in parts or "embedding" in parts:
        return True
    if any(tag in name for tag in ("embed", "embedding", "embedder", "nomic-embed", "bge-")):
        return True
    return False


def discover_models(models_dir: Optional[Path] = None,
                    include_embedders: bool = False) -> List[Dict[str, Any]]:
    """Find chat-suitable GGUF models on disk.

    Recursive; finds `models/gguf/base/*` etc. By default embedders are
    excluded from the result — they are not chat models and must never be
    selected as the main model by `recommend()`. Pass `include_embedders=True`
    when callers genuinely want every .gguf on disk (e.g. a diagnostic
    inventory)."""
    if models_dir is None:
        try:
            from eli.core.paths import project_root
            models_dir = project_root() / "models"
        except Exception:
            models_dir = Path.cwd() / "models"

    out: List[Dict[str, Any]] = []
    if not models_dir.is_dir():
        return out
    for f in sorted(models_dir.rglob("*.gguf")):
        if not include_embedders and _is_embedder_path(f):
            continue
        size = f.stat().st_size
        out.append({
            "name": f.name,
            "path": str(f.resolve()),
            "size_bytes": size,
            "size_gb": size / 1e9,
        })
    return out


def _gpu_layers_for_model(size_gb: float, free_vram_mb: int, n_ctx: int,
                          kv_quantized: bool = False) -> int:
    """Compute n_gpu_layers from FREE VRAM minus KV-cache and CUDA overhead.

    When kv_quantized=True, the KV cache uses ~25% of fp16 size (q4_0 K
    and q4_0 V), letting much larger n_ctx fit on the same GPU.

    Returns 9999 sentinel if the entire model fits, 0 if no GPU or
    insufficient VRAM, or a partial layer count otherwise.
    """
    if free_vram_mb <= 0:
        return 0
    total_layers = _layers_for_size(size_gb)
    kv_mb = _kv_cache_mb(n_ctx, total_layers, quant=kv_quantized)
    available_for_model = free_vram_mb - kv_mb - _CUDA_OVERHEAD_MB
    mb_per_layer = (size_gb * 1024) / max(1, total_layers + 2)
    if available_for_model <= 0 or mb_per_layer <= 0:
        return 0
    n = int(available_for_model / mb_per_layer)
    if n >= total_layers:
        return 9999  # all layers fit — let llama.cpp handle it
    return max(0, n)


def recommend(hw: Optional[HardwareProfile] = None,
              models: Optional[List[Dict[str, Any]]] = None) -> ModelRecommendation:
    """Generate optimal model + parameter recommendation for this hardware.

    Picks the largest model that fits within free VRAM (after KV cache +
    CUDA overhead) OR within available RAM if no GPU.
    """
    if hw is None:
        hw = detect_hardware()
    if models is None:
        models = discover_models()

    rec = ModelRecommendation()
    rec.reasoning = []

    rec.n_threads = max(1, hw.cpu_threads - 2)
    rec.reasoning.append(
        f"CPU: {hw.cpu_threads} threads → using {rec.n_threads}"
    )
    rec.reasoning.append(
        f"RAM: {hw.ram_gb:.1f}GB total, {hw.available_ram_gb:.1f}GB available"
    )
    if hw.has_gpu:
        rec.reasoning.append(
            f"GPU: {hw.gpu_name} — {hw.free_vram_mb/1024.0:.2f}GB free / "
            f"{hw.total_vram_mb/1024.0:.1f}GB total"
        )
    else:
        rec.reasoning.append("GPU: none detected (CPU-only mode)")

    if not models:
        rec.reasoning.append("No GGUF models found. Consider Ollama.")
        rec.provider = "ollama"
        rec.n_ctx = 8192
        rec.batch_size = 512
        return rec

    # KV-cache quantization decision. q4_0 K + q4_0 V cuts KV memory ~75%
    # with negligible quality loss for chat workloads. We enable it
    # automatically when the GPU is small enough that fp16 KV would
    # squeeze GPU layers below useful counts. On a 4 GB card this is
    # always; on a 12+ GB card, fp16 is fine.
    rec.cache_type_k = "q4_0" if (hw.has_gpu and hw.total_vram_mb < 12000) else ""
    rec.cache_type_v = rec.cache_type_k  # match K and V quantization
    kv_q = bool(rec.cache_type_k)
    if kv_q:
        rec.reasoning.append("KV cache: q4_0 (4× more ctx for the same VRAM, minimal quality loss)")
    else:
        rec.reasoning.append("KV cache: fp16 (no quantization)")

    # Context window. Now driven by available RAM AND VRAM. With KV-q4
    # enabled, 16k ctx fits even on a 4 GB GPU with most of the model
    # offloaded — that is the regime we want by default.
    if hw.available_ram_gb >= 16:
        rec.n_ctx = 16384
    elif hw.available_ram_gb >= 8:
        rec.n_ctx = 8192
    elif hw.available_ram_gb >= 4:
        rec.n_ctx = 4096
    else:
        rec.n_ctx = 2048
    rec.reasoning.append(f"n_ctx={rec.n_ctx} (scales with available RAM)")

    # Pick the largest model that actually fits, given the chosen ctx and
    # KV-quantization regime.
    models_sorted = sorted(models, key=lambda m: m["size_gb"])
    chosen = None
    chosen_layers = 0
    for m in reversed(models_sorted):
        if hw.has_gpu:
            layers = _gpu_layers_for_model(
                m["size_gb"], hw.free_vram_mb, rec.n_ctx, kv_quantized=kv_q,
            )
            if layers > 0:
                chosen = m
                chosen_layers = layers
                break
        else:
            if m["size_gb"] <= hw.available_ram_gb * 0.5:
                chosen = m
                chosen_layers = 0
                break

    if chosen is None:
        chosen = models_sorted[0]
        chosen_layers = (_gpu_layers_for_model(
            chosen["size_gb"], hw.free_vram_mb, rec.n_ctx, kv_quantized=kv_q,
        ) if hw.has_gpu else 0)
        rec.reasoning.append(
            f"Falling back to smallest: {chosen['name']} ({chosen['size_gb']:.1f}GB)"
        )

    # If the largest-model attempt found 0 GPU layers at this ctx, retry
    # smaller-model first before giving up — this is the regime where ctx
    # is so big the KV cache eats VRAM. recommend() should always produce
    # something usable on GPU when one is present.

    rec.model_path = chosen["path"]
    rec.model_name = chosen["name"]
    rec.model_size_gb = chosen["size_gb"]
    rec.n_gpu_layers = chosen_layers

    if chosen_layers >= 9999:
        rec.reasoning.append(
            f"Model: {chosen['name']} ({chosen['size_gb']:.2f}GB) — "
            f"all layers on GPU (free VRAM sufficient)"
        )
    elif chosen_layers > 0:
        total_layers = _layers_for_size(chosen["size_gb"])
        rec.reasoning.append(
            f"Model: {chosen['name']} ({chosen['size_gb']:.2f}GB) — "
            f"{chosen_layers}/{total_layers} layers on GPU "
            f"(KV {_kv_cache_mb(rec.n_ctx, total_layers):.0f}MB + "
            f"{_CUDA_OVERHEAD_MB}MB CUDA overhead)"
        )
    else:
        rec.reasoning.append(
            f"Model: {chosen['name']} ({chosen['size_gb']:.2f}GB) — CPU only"
        )

    # Batch size: scales aggressively with GPU offload. Larger batch =
    # faster prompt prefill on GPU. Capped at 1024 to keep the kv-cache
    # alloc spike under control on small VRAM cards.
    total_layers = _layers_for_size(chosen["size_gb"])
    if chosen_layers >= 9999 or chosen_layers >= total_layers:
        rec.batch_size = 1024
    elif chosen_layers >= 24:
        rec.batch_size = 768
    elif chosen_layers >= 20:
        rec.batch_size = 512
    elif chosen_layers >= 12:
        rec.batch_size = 384
    elif chosen_layers >= 6:
        rec.batch_size = 256
    else:
        rec.batch_size = 128

    rec.use_mmap = True
    rec.use_mlock = (hw.available_ram_gb >= 16)
    rec.max_tokens = -1   # unlimited — use full remaining context
    rec.temperature = 0.7

    # Per-reasoning-mode presets derived from the base tune. Quick is
    # the reference (full base); each other mode carves a stage budget.
    # The base max_tokens for derivation is whichever is larger between
    # the configured cap and a context-scaled ceiling. `-1` means
    # unlimited at runtime, so for derivation we use n_ctx/4 capped at
    # 4096 as a stable per-stage reference.
    _max_for_derivation = (
        rec.max_tokens
        if rec.max_tokens > 0
        else min(4096, max(1024, int(rec.n_ctx // 4)))
    )
    rec.mode_presets = _derive_mode_presets(
        rec.n_ctx, _max_for_derivation, rec.temperature,
    )
    rec.reasoning.append(
        f"mode_presets: 5 reasoning modes derived from base "
        f"(ctx={rec.n_ctx}, max_tokens_ref={_max_for_derivation})"
    )

    return rec


def apply_recommendation(rec: ModelRecommendation) -> Dict[str, Any]:
    """Write the recommendation as flat keys to config/settings.json.

    Writes ONLY the flat canonical keys. Does NOT write mode_profiles
    or active_mode, which are no longer part of the runtime settings shape.
    """
    try:
        from eli.core.runtime_settings import load_settings, save_settings
        settings = load_settings()
        settings["model_path"] = rec.model_path
        settings["bundled_model_path"] = rec.model_path
        settings["custom_model_path"] = rec.model_path
        settings["gguf_model_path"] = rec.model_path
        settings["n_gpu_layers"] = rec.n_gpu_layers
        settings["n_ctx"] = rec.n_ctx
        settings["batch_size"] = rec.batch_size
        settings["n_threads"] = rec.n_threads
        settings["max_tokens"] = rec.max_tokens
        settings["temperature"] = rec.temperature
        settings["use_mmap"] = rec.use_mmap
        settings["use_mlock"] = rec.use_mlock
        settings["provider"] = rec.provider
        # KV-cache quantization keys: empty string clears any previous
        # value, populated string enables that quantization regime.
        settings["cache_type_k"] = rec.cache_type_k
        settings["cache_type_v"] = rec.cache_type_v
        # Per-reasoning-mode presets — engine reads these so each mode
        # has parameters derived from this hardware tune, not hard-coded.
        settings["mode_presets"] = dict(rec.mode_presets)
        save_settings(settings)
        return {"ok": True, "settings_updated": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def run_benchmark() -> Dict[str, Any]:
    """Full hardware detection + recommendation. Returns dict for the executor."""
    hw = detect_hardware()
    models = discover_models()
    rec = recommend(hw, models)
    return {
        "hardware": hw.to_dict(),
        "models": models,
        "recommendation": rec.to_dict(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Hardware-profile authority: the profiler is the source of truth (ELI design
# directive #1). At startup, settings that drift above what `recommend()`
# would produce on this machine are re-applied automatically. We never silently
# downgrade the model — only the runtime tune (n_ctx, n_gpu_layers, batch).
# Model swap recommendations (e.g. Q3→Q4 on a 4 GB card) are emitted as a
# warning banner, never auto-applied.
# ─────────────────────────────────────────────────────────────────────────────

def compute_hardware_fingerprint(hw: HardwareProfile) -> str:
    """Stable short hash of the machine's identifying hardware traits.
    Used to detect 'we are running on a different machine now'."""
    import hashlib
    parts = (
        str(hw.cpu_threads),
        f"{hw.ram_gb:.0f}",
        str(int(hw.has_gpu)),
        str(hw.gpu_name or ""),
        str(int(hw.total_vram_mb)),
    )
    raw = "|".join(parts).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def _model_quant_label(path: str) -> str:
    name = Path(path).name.lower() if path else ""
    for q in ("q2_k", "q3_k_m", "q3_k_s", "q3_k", "q3", "q4_k_m", "q4_k_s",
             "q4_0", "q4_1", "q5_k_m", "q5_k_s", "q5_0", "q6_k", "q8_0", "f16"):
        if q in name:
            return q
    return ""


def _settings_out_of_bounds(settings: Dict[str, Any],
                            rec: ModelRecommendation) -> List[str]:
    """Return a list of breach reasons; empty list means the settings are
    within or equal to what the profiler would produce on this hardware."""
    reasons: List[str] = []
    try:
        if int(settings.get("n_ctx", 0)) > int(rec.n_ctx):
            reasons.append(f"n_ctx {settings.get('n_ctx')} > recommended {rec.n_ctx}")
    except Exception:
        pass
    try:
        # n_gpu_layers: -1 / 9999 sentinels mean "all layers". Compare raw.
        s_layers = int(settings.get("n_gpu_layers", 0))
        r_layers = int(rec.n_gpu_layers)
        # Treat 9999 (full offload) as legitimate ceiling on either side.
        if 0 < r_layers < 9999 and s_layers > r_layers:
            reasons.append(f"n_gpu_layers {s_layers} > recommended {r_layers}")
    except Exception:
        pass
    try:
        if int(settings.get("batch_size", 0)) > int(rec.batch_size):
            reasons.append(f"batch_size {settings.get('batch_size')} > recommended {rec.batch_size}")
    except Exception:
        pass
    return reasons


def _user_model_path_is_valid(settings: Dict[str, Any]) -> bool:
    """True iff settings.model_path points at a file that exists and is
    a chat-suitable GGUF (not an embedder). Used to decide whether to
    preserve the user's explicit model choice or fall back to the
    profiler's recommendation."""
    raw = str(settings.get("model_path") or "").strip()
    if not raw:
        return False
    try:
        from eli.core.paths import project_root
        root = project_root()
    except Exception:
        root = Path.cwd()
    p = Path(raw)
    if not p.is_absolute():
        p = (root / p).resolve()
    if not p.exists():
        return False
    if p.suffix.lower() != ".gguf":
        return False
    if _is_embedder_path(p):
        return False
    return True


def enforce_hardware_authority(*, force: bool = False) -> Dict[str, Any]:
    """Validate that settings.json reflects what the profiler would produce
    on this hardware. If hardware fingerprint changed OR runtime-tune
    settings are above profiler-recommended bounds, rewrite ONLY the
    runtime-tune fields (n_ctx, n_gpu_layers, batch_size, cache_type_k/v).

    The user's explicit model_path is PRESERVED unless it's missing,
    non-existent on disk, or has accidentally been pointed at an embedder
    (bug found 2026-05-11 — discover_models picked nomic-embed as the chat
    model). In that case the profiler's recommendation is written.

    Returns:
        {ok, rewritten, reason, fingerprint, previous_fingerprint, banner, warnings}
    """
    warnings: List[str] = []
    try:
        from eli.core.runtime_settings import load_settings, save_settings
        settings = dict(load_settings() or {})
    except Exception as exc:
        return {"ok": False, "rewritten": False, "reason": f"could not load settings: {exc}",
                "fingerprint": "", "previous_fingerprint": None, "banner": None,
                "warnings": warnings}

    hw = detect_hardware()

    # Phase 11 fix (2026-05-11): if this process already has a GGUF model
    # loaded, the live free_vram_mb is artificially small (the model is
    # eating its own budget). Computing layer recommendations from that
    # number gives nonsense values (Jay's session showed n_gpu_layers
    # → 1, effectively CPU-only). Predict free VRAM AS IF no chat model
    # was loaded: total_vram - (display server estimate, ~500 MB) - kv
    # cache, leaving room for the chat model itself.
    try:
        from eli.cognition import gguf_inference as _gi_check
        _loaded = bool(getattr(_gi_check, "_llm", None))
    except Exception:
        _loaded = False
    if _loaded and hw.has_gpu and hw.total_vram_mb > 0:
        # Heuristic: assume ~500 MB consumed by the display server + Qt,
        # everything else is the chat model + embedder. That's what would
        # be available if we re-ran cold.
        _predicted_free = max(0, hw.total_vram_mb - 500)
        if _predicted_free > hw.free_vram_mb:
            hw.free_vram_mb = _predicted_free
            hw.vram_gb = _predicted_free / 1024.0

    fingerprint = compute_hardware_fingerprint(hw)
    previous_fp = settings.get("hardware_fingerprint")

    # Discover ONLY chat-suitable models for the recommendation.
    models = discover_models()
    rec = recommend(hw, models)

    # Model-quant advisory (never auto-swap; spec directive — flag only).
    try:
        active_quant = _model_quant_label(str(settings.get("model_path", "")))
        if active_quant.startswith("q3") and hw.has_gpu and hw.total_vram_mb < 4500:
            warnings.append(
                f"Active model uses {active_quant.upper()} on a {hw.total_vram_mb/1024:.1f} GB GPU. "
                f"Q4_K_M or Q5_K_S would resolve meta-reasoning failures while still fitting. "
                f"Re-run the profiler or choose a different model to apply."
            )
    except Exception:
        pass

    reasons = _settings_out_of_bounds(settings, rec)
    fingerprint_changed = (previous_fp is not None and previous_fp != fingerprint)
    model_invalid = not _user_model_path_is_valid(settings)
    if model_invalid:
        reasons.append(f"model_path invalid or points at embedder: {settings.get('model_path')!r}")

    if not force and not fingerprint_changed and not reasons:
        return {
            "ok": True, "rewritten": False, "reason": "",
            "fingerprint": fingerprint,
            "previous_fingerprint": previous_fp,
            "banner": None,
            "warnings": warnings,
        }

    if model_invalid:
        primary_reason = "model_path was missing or pointed at an embedder; profiler chose a chat model"
    elif fingerprint_changed:
        primary_reason = f"hardware fingerprint changed ({previous_fp} -> {fingerprint})"
    elif reasons:
        primary_reason = "settings exceed profiler-recommended bounds: " + "; ".join(reasons)
    else:
        primary_reason = "forced re-apply"

    # Only rewrite the fields that actually need to change. The user's
    # explicit model_path is preserved when valid.
    before = {k: settings.get(k) for k in ("n_ctx", "n_gpu_layers", "batch_size", "model_path")}
    new_settings = dict(settings)

    # Runtime tune always re-applies on rewrite (these are the parameters
    # the profiler authoritatively decides).
    new_settings["n_ctx"] = int(rec.n_ctx)
    new_settings["n_gpu_layers"] = int(rec.n_gpu_layers)
    new_settings["batch_size"] = int(rec.batch_size)
    new_settings["n_threads"] = int(rec.n_threads)
    new_settings["cache_type_k"] = rec.cache_type_k
    new_settings["cache_type_v"] = rec.cache_type_v
    new_settings["use_mmap"] = bool(rec.use_mmap)
    new_settings["use_mlock"] = bool(rec.use_mlock)
    if rec.mode_presets:
        new_settings["mode_presets"] = dict(rec.mode_presets)

    # Model path: preserve user selection unless it was invalid.
    if model_invalid:
        new_settings["model_path"] = rec.model_path
        new_settings["bundled_model_path"] = rec.model_path
        new_settings["custom_model_path"] = rec.model_path
        new_settings["gguf_model_path"] = rec.model_path
        new_settings["provider"] = rec.provider

    new_settings["hardware_fingerprint"] = fingerprint

    try:
        save_settings(new_settings)
    except Exception as exc:
        return {
            "ok": False, "rewritten": False,
            "reason": f"save_settings failed: {exc}",
            "fingerprint": fingerprint,
            "previous_fingerprint": previous_fp,
            "banner": None,
            "warnings": warnings,
        }

    diffs = []
    for k, before_v in before.items():
        after_v = new_settings.get(k)
        if str(before_v) != str(after_v):
            diffs.append(f"{k}: {before_v} → {after_v}")
    banner = "Hardware profile re-applied. " + primary_reason
    if diffs:
        banner += " | " + ", ".join(diffs)

    return {
        "ok": True, "rewritten": True, "reason": primary_reason,
        "fingerprint": fingerprint,
        "previous_fingerprint": previous_fp,
        "banner": banner,
        "warnings": warnings,
    }


# CLI entry point
if __name__ == "__main__":
    bench = run_benchmark()
    print(json.dumps(bench, indent=2))
