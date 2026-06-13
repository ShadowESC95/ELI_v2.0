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


def derive_budget(model_path: str | Path = "") -> DynamicRuntimeBudget:
    gpu_name, vram_total, vram_free = detect_gpu()
    ram_gb = detect_ram_gb()
    threads = max(2, (os.cpu_count() or 4) - 2)
    size_gb = model_size_gb(model_path)

    usable_vram = max(0, vram_free - 900)

    # GPU layers: model-size aware, not just VRAM aware.
    if vram_total <= 0:
        gpu_layers = 0
    elif size_gb <= 2.5 and usable_vram >= 3500:
        gpu_layers = 99
    elif size_gb <= 5.0 and usable_vram >= 5500:
        gpu_layers = 35
    elif size_gb <= 8.0 and usable_vram >= 6500:
        gpu_layers = 24
    elif size_gb <= 12.0 and usable_vram >= 6500:
        gpu_layers = 16
    elif size_gb <= 18.0 and usable_vram >= 6500:
        gpu_layers = 8
    else:
        gpu_layers = 4 if usable_vram >= 3500 else 0

    # Context: constrained by RAM + model size.
    if ram_gb >= 48 and size_gb <= 8:
        n_ctx = 16384
    elif ram_gb >= 32 and size_gb <= 16:
        n_ctx = 12288
    elif ram_gb >= 24:
        n_ctx = 8192
    elif ram_gb >= 16:
        n_ctx = 6144
    else:
        n_ctx = 4096

    # Very large models on modest machines should not start at huge ctx.
    if size_gb >= 14 and ram_gb < 48:
        n_ctx = min(n_ctx, 8192)

    n_ctx = _round_ctx(n_ctx)

    # Batch: primarily VRAM pressure.
    if usable_vram >= 10000 and size_gb <= 8:
        batch = 512
    elif usable_vram >= 7000 and size_gb <= 12:
        batch = 384
    elif usable_vram >= 5500:
        batch = 256
    else:
        batch = 128

    if size_gb >= 14:
        batch = min(batch, 128)

    # Output budget: prefer 4096, but maintain prompt headroom.
    # This is generated-token budget, not context.
    if n_ctx >= 8192:
        max_tokens = 4096
    elif n_ctx >= 6144:
        max_tokens = 3072
    else:
        max_tokens = 2048

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
