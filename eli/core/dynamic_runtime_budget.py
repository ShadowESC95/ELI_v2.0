from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
import json
import os
import re
import subprocess
from typing import Any, Dict, Optional


@dataclass
class DynamicRuntimeBudget:
    model_path: str
    model_size_gb: float
    gpu_name: str
    vram_total_mb: int
    vram_free_mb: int
    ram_total_gb: float
    cpu_threads: int
    n_ctx: int
    n_gpu_layers: int
    batch_size: int
    max_tokens: int
    mode_presets: Dict[str, Dict[str, Any]]
    reasoning: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _run(cmd: list[str]) -> str:
    return subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL).strip()


def detect_gpu() -> tuple[str, int, int]:
    try:
        raw = _run([
            "nvidia-smi",
            "--query-gpu=name,memory.total,memory.free",
            "--format=csv,noheader,nounits",
        ]).splitlines()[0]
        name, total, free = [x.strip() for x in raw.split(",")]
        return name, int(total), int(free)
    except Exception:
        return "CPU/no-NVIDIA", 0, 0


def detect_ram_gb() -> float:
    # psutil is cross-platform and already a dependency — prefer it so RAM is
    # detected correctly off-Linux instead of defaulting to 8.
    try:
        import psutil
        return psutil.virtual_memory().total / 1e9
    except Exception:
        pass
    try:
        meminfo = Path("/proc/meminfo").read_text()
        m = re.search(r"MemTotal:\s+(\d+)\s+kB", meminfo)
        if m:
            return int(m.group(1)) / 1024 / 1024
    except Exception:
        pass
    return 8.0


def model_size_gb(model_path: str | Path) -> float:
    try:
        return Path(model_path).stat().st_size / (1024 ** 3)
    except Exception:
        return 0.0


def _round_ctx(x: int) -> int:
    choices = [2048, 4096, 6144, 8192, 12288, 16384, 24576, 32768]
    return max(c for c in choices if c <= max(2048, x))



_MIN_CTX = 4096
_MIN_BATCH = 128
# A proportion of measured memory, not a size band: a machine with twice the
# RAM gets twice the allowance, with no thresholds to fall between.
_RAM_FRACTION_FOR_CTX = 0.25
# Nothing sensible can be inferred above a model's own training window, and a
# context beyond it degrades quality — llama.cpp warns "n_ctx_seq > n_ctx_train".
_ABSOLUTE_CTX_CAP = 32768



# Generated-output share of the context window. The rest is prompt headroom:
# persona brief, memory context and evidence all have to fit alongside it.
_OUTPUT_SHARE_OF_CTX = 0.375
_MAX_OUTPUT_TOKENS = 4096


def _output_budget_for_ctx(n_ctx: int) -> int:
    """Generated-token budget as a proportion of the window, not a band."""
    return max(512, min(_MAX_OUTPUT_TOKENS, int(int(n_ctx) * _OUTPUT_SHARE_OF_CTX)))


def _ctx_ceiling_for_ram(ram_gb: float, size_gb: float) -> int:
    """Largest context this machine's RAM can hold for a model this size.

    Replaces `if ram_gb >= 48 ... 16384 / elif >= 32 ... 12288 / ...`.

    The per-token cost comes from hardware_profile._kv_cache_mb — the same
    measured KV arithmetic the loader uses — rather than a constant invented
    here. An earlier draft of this function DID invent one, and it implied an
    18k context on an 8GB machine, which is exactly the class of number this
    change exists to remove.
    """
    try:
        from eli.core.hardware_profile import _kv_cache_mb, _layers_for_size
        layers = _layers_for_size(float(size_gb))
        mb_per_token = _kv_cache_mb(1, layers, quant=False)
    except Exception:
        return _MIN_CTX
    if mb_per_token <= 0:
        return _MIN_CTX
    allowance_mb = max(0.0, float(ram_gb)) * 1024.0 * _RAM_FRACTION_FOR_CTX
    return max(_MIN_CTX, min(_ABSOLUTE_CTX_CAP, int(allowance_mb / mb_per_token)))


def _batch_ceiling_for_vram(usable_vram_mb: float) -> int:
    """Batch scales with the VRAM actually free, in powers of two.

    Replaces `if usable_vram >= 10000 ... 512 / elif >= 7000 ... 384 / ...`.
    smart_fit_config halves this toward its own floor when it does not fit, so
    this only needs to be an honest starting point.
    """
    b = _MIN_BATCH
    while b < 512 and usable_vram_mb >= (b * 16):
        b *= 2
    return int(b)


def derive_budget(model_path: str | Path = "") -> DynamicRuntimeBudget:
    gpu_name, vram_total, vram_free = detect_gpu()
    ram_gb = detect_ram_gb()
    threads = max(2, (os.cpu_count() or 4) - 2)
    size_gb = model_size_gb(model_path)

    usable_vram = max(0, vram_free - 900)

    # ── ctx / gpu_layers / batch come from the MEASURED fit ────────────────
    #
    # This used to be three ladders of hardcoded buckets — ctx picked from
    # {16384, 12288, 8192, 6144, 4096} by RAM band, gpu_layers from
    # {99, 35, 24, 16, 8, 4} by model-size band, batch from
    # {512, 384, 256, 128} by VRAM band. Nothing measured the KV cache or the
    # compute graph, so the numbers disagreed with what the loader actually
    # did: on one live 2.3.0 launch this table's ctx and the resident ctx were
    # 6144 and 10384, on the same machine, at the same moment.
    #
    # hardware_profile.smart_fit_config is the real arithmetic — KV cache per
    # token, compute-graph reserve, MB per layer from the model's own size —
    # and it is what the loader uses. Deriving from it keeps one answer in the
    # process instead of two that drift apart.
    ctx_target = _ctx_ceiling_for_ram(ram_gb, size_gb)
    try:
        from eli.core.hardware_profile import smart_fit_config
        n_ctx, gpu_layers, batch = smart_fit_config(
            model_size_gb=size_gb,
            free_vram_mb=int(vram_free),
            user_ctx=ctx_target,
            user_batch=_batch_ceiling_for_vram(usable_vram),
        )
    except Exception:
        # The fit is unavailable (no hardware_profile on this build). Fall back
        # to the smallest safe window rather than to invented buckets.
        n_ctx, gpu_layers, batch = _MIN_CTX, (0 if vram_total <= 0 else 4), _MIN_BATCH

    if vram_total <= 0:
        gpu_layers = 0

    n_ctx = _round_ctx(n_ctx)

    # Output budget: a share of the window, so prompt headroom is preserved at
    # every size instead of jumping between three fixed values. The last of the
    # bands lived here (4096 / 3072 / 2048 by ctx), which meant a ctx of 6143
    # and 6144 got budgets 1024 tokens apart for no measured reason.
    max_tokens = _output_budget_for_ctx(n_ctx)

    # Mode-specific budgets.
    mode_presets = {
        "quick": {
            "max_tokens": min(max_tokens, 1536),
            "passes": 1,
            "memory_depth": "low",
        },
        "standard": {
            "max_tokens": min(max_tokens, 3072),
            "passes": 1,
            "memory_depth": "normal",
        },
        "cot": {
            "max_tokens": max_tokens,
            "passes": 1,
            "memory_depth": "normal",
        },
        "self_consistency": {
            "samples": 3 if n_ctx >= 8192 else 2,
            "max_tokens_per_sample": min(max_tokens, 2048),
            "max_tokens_final": min(max_tokens, 3072),
        },
        "tree_of_thoughts": {
            "branches": 3 if n_ctx >= 8192 else 2,
            "depth": 2,
            "max_tokens_generate": min(max_tokens, 2048),
            "max_tokens_critique": 768,
            "max_tokens_revise": min(max_tokens, 4096),
        },
        "constitutional_ai": {
            "max_tokens_generate": min(max_tokens, 3072),
            "max_tokens_critique": 1024,
            "max_tokens_revise": min(max_tokens, 4096),
            "max_tokens": max_tokens,
        },
    }

    reasoning = {
        "policy": "dynamic_hardware_model_budget",
        "note": "max_tokens is generated output budget; n_ctx is total context window.",
        "large_model_guard": size_gb >= 14,
        "usable_vram_mb": usable_vram,
    }

    return DynamicRuntimeBudget(
        model_path=str(model_path),
        model_size_gb=round(size_gb, 2),
        gpu_name=gpu_name,
        vram_total_mb=vram_total,
        vram_free_mb=vram_free,
        ram_total_gb=round(ram_gb, 2),
        cpu_threads=threads,
        n_ctx=n_ctx,
        n_gpu_layers=gpu_layers,
        batch_size=batch,
        max_tokens=max_tokens,
        mode_presets=mode_presets,
        reasoning=reasoning,
    )


def write_budget(model_path: str | Path = "", out_path: str | Path = "artifacts/runtime_dynamic_budget.json") -> Dict[str, Any]:
    budget = derive_budget(model_path)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(budget.to_dict(), indent=2), encoding="utf-8")
    return budget.to_dict()


if __name__ == "__main__":
    import sys
    model = sys.argv[1] if len(sys.argv) > 1 else ""
    print(json.dumps(write_budget(model), indent=2))
