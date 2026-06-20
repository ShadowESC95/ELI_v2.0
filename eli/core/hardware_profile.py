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


def _compute_graph_reserve_mb(n_ctx: int, batch: int = 256) -> float:
    """Estimate the CUDA compute/graph buffer llama.cpp allocates at DECODE
    time — separate from model weights and KV cache.

    This buffer scales with context length (attention scratch / KQ buffers)
    and batch size (activation buffers). It is allocated lazily on the first
    generation, NOT at load. Failing to reserve it is why a profile could
    load cleanly and then hard-crash (ggml-cuda.cu CUDA error / core dump)
    on the first decode: model + KV + 350MB overhead fit, but the compute
    buffer then pushed total VRAM over the card's limit.

    Reference measurement (8GB card, a ~7B-class full-offload model at 32k ctx
    / batch 256) needed ~1.2-1.4GB here. The estimate below is model-agnostic:
    it scales with ctx and batch only, never model identity. Conservative
    linear estimate (errs slightly high so the chosen ctx/layers stay
    inference-safe rather than load-safe-only):
        base 256MB + 24MB per 1K ctx + 1.5MB per batch unit
    """
    return 256.0 + (max(0, int(n_ctx)) / 1024.0) * 24.0 + float(max(0, int(batch))) * 1.5


def _layers_for_size(size_gb: float) -> int:
    """Total transformer layers heuristic by model size (GB). Extended for big
    models (readiness #5): a 70B has ~80 layers, a 100B+ ~96+ — capping at 48
    under-offloaded large models."""
    if size_gb < 1.5:   return 22
    if size_gb < 3.0:   return 28
    if size_gb < 6.0:   return 32
    if size_gb < 12.0:  return 40
    if size_gb < 30.0:  return 48   # ~13–32B
    if size_gb < 55.0:  return 64   # ~34–70B
    if size_gb < 90.0:  return 80   # ~70–100B
    return 96                       # 100B+


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


def _derive_mode_presets(_base_n_ctx: int, base_max_tokens: int,
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

    # MODEL-AGNOSTIC capability scaling for the sample/branch COUNTS (the per-stage token
    # budgets already follow base_max). tier_scale() is 1.0 for the current small model
    # (behaviour-preserving) and rises for medium/large/frontier models, so a stronger model
    # gets more samples / wider search instead of staying at the small-model default of 3.
    try:
        from eli.core.model_tier import tier_scale as _ts
        _scale = float(_ts())
    except Exception:
        _scale = 1.0

    def _cnt(base: int, lo: int, hi: int) -> int:
        return max(lo, min(hi, int(round(base * _scale))))

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
            "samples": _cnt(3, 2, 7),
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
            "branches": _cnt(3, 2, 6),
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
            "max_tokens_critique": min(256, int(base_max * 0.15)),
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
            # Sum across ALL GPUs (readiness #5: multi-GPU was under-counted by
            # reading only the first card). llama.cpp splits across visible CUDA
            # devices, and the adaptive-load fallback reduces layers on any OOM —
            # so provisioning against total capacity is safe.
            free_sum = total_sum = 0
            names: list = []
            for line in out:
                p = [x.strip() for x in line.split(",")]
                try:
                    free_sum += int(p[0])
                    total_sum += int(p[1])
                    if len(p) > 2:
                        names.append(p[2])
                except Exception:
                    continue
            n = max(1, len(names) or len(out))
            hw.free_vram_mb = free_sum
            hw.total_vram_mb = total_sum
            hw.gpu_name = (names[0] if names else "NVIDIA GPU") + (f" ×{n}" if n > 1 else "")
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
    as the main GGUF by `recommend()`. Reported 2026-05-11 — the
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

    Returns 99 sentinel if the entire model fits (llama.cpp loads all layers
    when n_gpu_layers exceeds actual layer count; 99 is always above any
    real-world 7–70B model's layer count and avoids the 9999 sentinel that
    _eli_requested_runtime_from_kwargs() treats as an uncalibrated user value).
    Returns 0 if no GPU or insufficient VRAM, or a partial layer count otherwise.
    """
    if free_vram_mb <= 0:
        return 0
    total_layers = _layers_for_size(size_gb)
    kv_mb = _kv_cache_mb(n_ctx, total_layers, quant=kv_quantized)
    # Reserve the decode-time compute/graph buffer too, not just model+KV+overhead.
    # Without this, full offload (99) gets chosen at max ctx, loads fine, then
    # OOMs on the first decode when the compute buffer is allocated.
    compute_mb = _compute_graph_reserve_mb(n_ctx)
    available_for_model = free_vram_mb - kv_mb - _CUDA_OVERHEAD_MB - compute_mb
    mb_per_layer = (size_gb * 1024) / max(1, total_layers + 2)
    if available_for_model <= 0 or mb_per_layer <= 0:
        return 0
    n = int(available_for_model / mb_per_layer)
    if n >= total_layers:
        return 99  # all layers fit — llama.cpp handles any value > actual layer count
    return max(0, n)


def smart_fit_config(
    model_size_gb: float,
    free_vram_mb: int,
    *,
    user_ctx: int,
    user_batch: int,
    reserve_mb: int = 700,
    kv_quantized: bool = False,
    total_layers: Optional[int] = None,
    ctx_grain: int = 2048,
    min_ctx: int = 2048,
    min_batch: int = 64,
    min_gpu_fraction: float = 0.25,
) -> tuple[int, int, int]:
    """Smart loader fit.

    Starts from the user's preferred ctx/batch with FULL GPU offload, then — if
    that won't fit in the VRAM left after the required models (vision + nomic)
    are resident — reduces to fit in this order:

        1. GPU layers — first, in ~10% increments, down to a floor
           (min_gpu_fraction of total); we don't strip the GPU entirely just to
           keep a big ctx.
        2. batch — halved toward min_batch.
        3. ctx — last, in ctx_grain steps toward min_ctx, so context (quality)
           is preserved as long as possible. ("Quality over speed".)
        4. Only if it STILL won't fit: shed the remaining GPU layers to 0
           (CPU offload) as a last resort.

    KV cache for ALL layers lives on GPU in llama.cpp, so it scales with ctx
    regardless of offload — only ctx reduction frees it. Compute/graph buffer
    (the lazy first-decode allocation that OOMs) scales with ctx and batch.

    Returns (n_ctx, n_gpu_layers, n_batch). n_gpu_layers is the 99 sentinel when
    all layers fit, 0 for CPU-only. Pure/deterministic — no hardware calls.
    """
    total = int(total_layers or _layers_for_size(model_size_gb))
    budget = max(0, int(free_vram_mb) - int(reserve_mb))
    mb_per_layer = (model_size_gb * 1024.0) / max(1, total + 2)

    def _needed(ctx: int, layers: int, batch: int) -> float:
        gpu_model = mb_per_layer * layers
        kv = _kv_cache_mb(ctx, total, quant=kv_quantized)
        compute = _compute_graph_reserve_mb(ctx, batch)
        return gpu_model + kv + compute + _CUDA_OVERHEAD_MB

    ctx = max(min_ctx, int(user_ctx))
    batch = max(min_batch, int(user_batch))
    layers = total  # start fully offloaded

    if budget <= 0:
        return ctx, 0, batch  # no GPU budget → CPU-only

    floor = max(0, int(total * min_gpu_fraction))
    step = max(1, total // 10)

    # 1) GPU layers, in increments, down to the floor.
    while layers > floor and _needed(ctx, layers, batch) > budget:
        layers = max(floor, layers - step)
    # 2) batch.
    while batch > min_batch and _needed(ctx, layers, batch) > budget:
        batch = max(min_batch, batch // 2)
    # 3) Shed the REMAINING GPU layers (below the floor, toward CPU-only) to PRESERVE
    #    the user's requested ctx — context is quality, and a big-model-on-small-VRAM
    #    KV cache needs the room. This is what "ctx last, quality over speed" means:
    #    honour the requested context by trading GPU offload, NOT by crushing ctx while
    #    keeping layers (which forced a 20GB model to ctx=6144 at 12 layers when 8 layers
    #    would have held ~22k). The fraction spinbox is the user's speed↔context dial.
    while layers > 0 and _needed(ctx, layers, batch) > budget:
        layers = max(0, layers - step)
    # 4) ctx — true last resort, only when even CPU-only (0 layers) can't hold it.
    while ctx > min_ctx and _needed(ctx, layers, batch) > budget:
        ctx = max(min_ctx, ctx - ctx_grain)

    # Fine pack: the coarse 10%-step reduction above can leave VRAM unused (e.g. it
    # stopped at 8 layers with ~1.5GB still free). Greedily add layers back one at a
    # time while they still fit, so GPU offload FILLS the remaining budget — "give
    # the leftover VRAM to the layers". Strictly bounded by budget, so it can never
    # reintroduce an OOM; a no-op when already fully offloaded or CPU-only-by-necessity.
    while layers < total and _needed(ctx, layers + 1, batch) <= budget:
        layers += 1

    n_layers = 99 if layers >= total else layers
    return ctx, n_layers, batch


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

    # Context window:
    # • GPU systems  — drive ctx from VRAM KV budget, not RAM.
    #   Available RAM fluctuates with other processes and gives misleadingly
    #   low values (e.g. 2 GB free when 16 GB total) that result in ctx=2048
    #   on a machine that can handle 18 K+ tokens.  We start with the model's
    #   full training window and let the VRAM refinement below set the real
    #   ceiling after model selection.
    # • CPU-only     — RAM is the binding constraint; use available RAM.
    _ctx_grain = 2048
    if hw.has_gpu and hw.free_vram_mb > 0:
        # Default target context window for ALL models (overridable by the user in
        # the GUI startup loader / user_preferred_ctx). 16384 fits typical prompts
        # and, on VRAM-limited GPUs, leaves room for more GPU layers than a
        # train-ctx-sized window would. VRAM refinement below only REDUCES this.
        try:
            from eli.core.runtime_settings import DEFAULT_N_CTX as _DEF_CTX
        except Exception:
            _DEF_CTX = 16384
        rec.n_ctx = int(_DEF_CTX)
        rec.reasoning.append(
            f"n_ctx default={rec.n_ctx} (GPU system — reduced to fit if VRAM is tight)"
        )
    else:
        _raw_ctx = int(hw.available_ram_gb * 1024)
        rec.n_ctx = max(2048, (max(2048, min(131072, _raw_ctx)) // _ctx_grain) * _ctx_grain)
        rec.reasoning.append(
            f"n_ctx={rec.n_ctx} "
            f"(CPU-only: available_ram={hw.available_ram_gb:.1f}GB × 1024, 2048-grain)"
        )

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

    # Refine n_ctx now that we know the model and GPU offload level.
    # For GPU systems, cap ctx at what the remaining VRAM can hold for KV cache.
    # Without this the RAM-based formula over-allocates on VRAM-limited machines
    # and causes OOM on the first load attempt.
    if hw.has_gpu and hw.free_vram_mb > 0 and chosen_layers > 0:
        _total_layers_est = _layers_for_size(chosen["size_gb"])
        _model_vram_mb = chosen["size_gb"] * 1024.0
        # In partial offload only the GPU-resident fraction of the model occupies
        # VRAM. Subtracting the full model size when layers < total causes
        # vram_for_kv to go negative (→ 0 → ctx=2048) even when KV fits fine.
        _offload_frac = min(1.0, chosen_layers / max(1, _total_layers_est))
        _gpu_model_mb = _model_vram_mb * _offload_frac
        # All layers' KV cache lives on GPU by default in llama.cpp (even for
        # CPU-resident layers). Reserve only the fixed CUDA overhead here; the
        # old +1500 "runtime headroom" double-counted the batch/compute reserve
        # already accounted for during layer selection above.
        # Reserve the decode-time compute/graph buffer alongside model+overhead
        # so the chosen ctx is safe at FIRST GENERATION, not merely at load.
        _compute_mb = _compute_graph_reserve_mb(rec.n_ctx, 256)
        _vram_for_kv = max(0.0, hw.free_vram_mb - _gpu_model_mb - float(_CUDA_OVERHEAD_MB) - _compute_mb)
        _kv_factor = 4 if kv_q else 1
        _kv_per_token_mb = (_total_layers_est * _KV_BYTES_PER_TOKEN_PER_LAYER / 1_048_576) / _kv_factor
        if _kv_per_token_mb > 0:
            _max_ctx_vram = max(2048, int(_vram_for_kv / _kv_per_token_mb))
            _ctx_grain = 2048
            # Cap at the initial estimate (model training ctx); never inflate beyond it.
            _vram_ctx = max(2048, min(rec.n_ctx, (_max_ctx_vram // _ctx_grain) * _ctx_grain))
            _old = rec.n_ctx
            rec.n_ctx = _vram_ctx
            rec.reasoning.append(
                f"n_ctx set {_old} → {rec.n_ctx} from VRAM budget "
                f"(vram_for_kv={_vram_for_kv:.0f}MB kv/tok={_kv_per_token_mb:.3f}MB "
                f"gpu_model={_gpu_model_mb:.0f}MB offload={_offload_frac:.2f})"
            )

    total_layers = _layers_for_size(chosen["size_gb"])
    _full_offload = chosen_layers >= total_layers  # 99 >= actual layer count → all layers on GPU
    if _full_offload:
        rec.reasoning.append(
            f"Model: {chosen['name']} ({chosen['size_gb']:.2f}GB) — "
            f"all layers on GPU (free VRAM sufficient)"
        )
    elif chosen_layers > 0:
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

    # Batch size: scales linearly with GPU offload ratio.
    # Partial offload → interpolate 128..512 by actual offload fraction.
    # CPU-only → floor of 128. Aligned to 64-byte boundaries.
    if chosen_layers == 0:
        rec.batch_size = 128
    elif _full_offload:
        rec.batch_size = 512
    else:
        _offload = min(1.0, chosen_layers / max(1, total_layers))
        _raw_b = int(128 + _offload * (512 - 128))
        rec.batch_size = max(128, (_raw_b // 64) * 64)

    # VRAM headroom check: llama.cpp compute buffers (rope, attention accumulation,
    # graph workspace) consume VRAM beyond the model + KV allocation. On 8 GB cards
    # with full offload and long ctx, this leaves insufficient room for batch=512.
    # Thresholds derived empirically: ~750 MB needed for batch=512 on 7B models.
    if hw.has_gpu and hw.free_vram_mb > 0 and chosen_layers > 0 and rec.batch_size > 128:
        _offload_f = min(1.0, chosen_layers / max(1, total_layers))
        _kv_at_ctx = _kv_cache_mb(rec.n_ctx, total_layers, quant=kv_q)
        _gpu_model_for_batch = chosen["size_gb"] * 1024.0 * _offload_f
        _compute_headroom = (hw.free_vram_mb
                             - _gpu_model_for_batch
                             - _kv_at_ctx
                             - float(_CUDA_OVERHEAD_MB))
        # Pick the largest batch whose DECODE-time compute buffer actually fits
        # the remaining headroom, plus a safety margin. The compute buffer grows
        # with BOTH ctx and batch, so the old fixed thresholds (1000/400MB)
        # under-estimated at long ctx and let batch stay too high — loading fine
        # then OOMing on first decode. _compute_graph_reserve_mb errs high and
        # the margin absorbs estimate error + display/VRAM fluctuation.
        _SAFETY_MARGIN_MB = 400.0
        _safe_batch = 128
        for _cand_b in (512, 448, 384, 320, 256, 192, 128):
            if _cand_b > rec.batch_size:
                continue
            _need = _compute_graph_reserve_mb(rec.n_ctx, _cand_b) + _SAFETY_MARGIN_MB
            if _compute_headroom >= _need:
                _safe_batch = _cand_b
                break
        if rec.batch_size > _safe_batch:
            rec.reasoning.append(
                f"batch reduced {rec.batch_size}→{_safe_batch} — headroom "
                f"{_compute_headroom:.0f}MB vs compute buffer "
                f"{_compute_graph_reserve_mb(rec.n_ctx, rec.batch_size):.0f}MB"
                f"+{_SAFETY_MARGIN_MB:.0f}MB margin at ctx={rec.n_ctx}"
            )
            rec.batch_size = _safe_batch

    # Honor the startup dialog's ELI_TARGET_BATCH as an upper cap.
    # This lets the user throttle batch (e.g. when running alongside other
    # GPU workloads) without the profiler silently ignoring the setting.
    _env_batch_cap = int(os.environ.get("ELI_TARGET_BATCH", "0") or "0")
    if 0 < _env_batch_cap < rec.batch_size:
        rec.batch_size = max(128, (_env_batch_cap // 64) * 64)
        rec.reasoning.append(f"batch capped to {rec.batch_size} by ELI_TARGET_BATCH={_env_batch_cap}")

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
    """Write the recommendation to config/settings.json.

    Hardware-computed runtime-tune values (n_ctx, n_gpu_layers, batch_size)
    are written to hw_profile_* keys only — the canonical keys are the user's
    domain and must not be auto-overwritten.  All other fields (model_path,
    n_threads, cache_type_k/v, mode_presets, etc.) are safe to write.
    """
    try:
        from eli.core.runtime_settings import load_settings, save_settings
        settings = load_settings()
        settings["model_path"] = rec.model_path
        settings["bundled_model_path"] = rec.model_path
        settings["custom_model_path"] = rec.model_path
        settings["gguf_model_path"] = rec.model_path
        # Hardware-computed values stored under isolated keys only.
        settings["hw_profile_n_gpu_layers"] = rec.n_gpu_layers
        settings["hw_profile_n_ctx"] = rec.n_ctx
        settings["hw_profile_batch_size"] = rec.batch_size
        settings["n_threads"] = rec.n_threads
        settings["max_tokens"] = rec.max_tokens
        settings["temperature"] = rec.temperature
        settings["use_mmap"] = rec.use_mmap
        settings["use_mlock"] = rec.use_mlock
        settings["provider"] = rec.provider
        settings["cache_type_k"] = rec.cache_type_k
        settings["cache_type_v"] = rec.cache_type_v
        settings["mode_presets"] = dict(rec.mode_presets)
        save_settings(settings)

        # Keep the GUI's hw-profile artifact in sync.
        # eli_pro_audio_gui_MKI.py reads artifacts/runtime_hardware_profile.json
        # (keys: n_ctx, n_gpu_layers, batch_size) as its hw-profile fallback.
        # Without this write the GUI would show stale values from a previous
        # optimizer run, making it look like the profile wasn't updated.
        try:
            import json as _json
            from eli.core.paths import project_root as _project_root
            _art_path = _project_root() / "artifacts" / "runtime_hardware_profile.json"
            _art_path.parent.mkdir(parents=True, exist_ok=True)
            _art_path.write_text(
                _json.dumps(
                    {
                        "n_ctx": rec.n_ctx,
                        "n_gpu_layers": rec.n_gpu_layers,
                        "batch_size": rec.batch_size,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        except Exception:
            pass  # non-fatal — settings.json is the source of truth

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
        # n_gpu_layers: -1 / 99 / 9999 sentinels mean "all layers". Compare raw.
        s_layers = int(settings.get("n_gpu_layers", 0))
        r_layers = int(rec.n_gpu_layers)
        # Treat 99+ (full offload sentinel) as a legitimate ceiling on either side.
        if 0 < r_layers < 99 and s_layers > r_layers:
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
    # number gives nonsense values (a real session showed n_gpu_layers
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

    # _settings_out_of_bounds is advisory only — it no longer triggers a
    # rewrite.  The user's n_ctx / n_gpu_layers / batch_size are theirs to set
    # and are never auto-overwritten by the profiler.
    _oob = _settings_out_of_bounds(settings, rec)
    if _oob:
        try:
            import logging as _logging
            _logging.getLogger(__name__).debug(
                "[HW_AUTHORITY] advisory (not enforced): %s", ", ".join(_oob)
            )
        except Exception:
            pass

    fingerprint_changed = (previous_fp is not None and previous_fp != fingerprint)
    model_invalid = not _user_model_path_is_valid(settings)

    # Only proceed if something actually warrants writing:
    # new hardware fingerprint, invalid model path, or explicit force.
    if not force and not fingerprint_changed and not model_invalid:
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
    else:
        primary_reason = "forced re-apply"

    # Track what changes (hw_profile_* keys + model_path when invalid).
    before = {k: settings.get(k) for k in (
        "hw_profile_n_ctx", "hw_profile_n_gpu_layers", "hw_profile_batch_size", "model_path"
    )}
    new_settings = dict(settings)

    # Hardware-computed recommendation stored under hw_profile_* only.
    # n_ctx / n_gpu_layers / batch_size (canonical keys) are NOT touched —
    # they belong to the user and load_model() uses them for attempt 1.
    new_settings["hw_profile_n_ctx"] = int(rec.n_ctx)
    new_settings["hw_profile_n_gpu_layers"] = int(rec.n_gpu_layers)
    new_settings["hw_profile_batch_size"] = int(rec.batch_size)
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
    banner = "Hardware profile updated. " + primary_reason
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
