"""Live inference RAM footprint — model weights, KV cache, and latency context."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Optional

from eli.utils.log import get_logger

log = get_logger(__name__)


def is_inference_ram_question(text: str) -> bool:
    """True when the user asks about ELI's inference RAM, not memory DB / psutil."""
    low = str(text or "").lower()
    if re.search(
        r"\b(memories|sqlite|database|faiss|embedder|remember me|who am i|"
        r"memory entries|conversation turns|knowledge graph)\b",
        low,
    ):
        return False
    if re.search(
        r"\b(how much|how many)\b.{0,50}\b(ram|memory)\b",
        low,
    ) and re.search(
        r"\b(you|your|eli|utili[sz]|using|inference|model|loaded|latency|"
        r"response|speed|gpu|instead of|without)\b",
        low,
    ):
        return True
    if re.search(r"\bram\b.{0,40}\b(instead of|without)\b.{0,24}\b(gpu|cuda|vulkan)\b", low):
        return True
    if re.search(
        r"\b(your|you)\b.{0,40}\b(ram|memory)\b.{0,50}\b(latency|response time|"
        r"speed|inference|model|utili[sz]|using)\b",
        low,
    ):
        return True
    return False


def _read_snapshot() -> dict:
    try:
        from eli.runtime.deterministic_grounding_gate import _runtime_snapshot
        return _runtime_snapshot() or {}
    except Exception:
        return {}


def _model_size_gb(snap: dict) -> float:
    try:
        mp = str(snap.get("model_path") or "")
        if mp and Path(mp).is_file():
            return Path(mp).stat().st_size / (1024 ** 3)
    except Exception:
        log.debug("model size stat failed", exc_info=True)
    try:
        val = float(snap.get("model_size_gb") or 0)
        if val > 0:
            return val
    except Exception:
        log.debug("model_size_gb parse failed", exc_info=True)
    return 0.0


def estimate_inference_ram_mb(snap: Optional[dict] = None) -> Dict[str, Any]:
    snap = snap or _read_snapshot()
    eff = snap.get("effective") if isinstance(snap.get("effective"), dict) else {}
    if not eff:
        eff = snap

    n_ctx = int(eff.get("n_ctx") or snap.get("n_ctx") or 0)
    n_batch = int(eff.get("n_batch") or eff.get("batch_size") or snap.get("n_batch") or 32)
    n_gpu = int(eff.get("n_gpu_layers") or snap.get("n_gpu_layers") or 0)
    model_path = str(snap.get("model_path") or "")

    from eli.core.hardware_profile import (
        _compute_graph_reserve_mb,
        _kv_cache_mb,
        layers_for_model,
    )

    size_gb = _model_size_gb(snap)
    if size_gb <= 0:
        size_gb = 1.67
    n_layers = layers_for_model(model_path or None, size_gb)

    kv_k = str(snap.get("cache_type_k") or eff.get("cache_type_k") or "")
    kv_v = str(snap.get("cache_type_v") or eff.get("cache_type_v") or "")
    kv_quant = any(q in kv_k.lower() or q in kv_v.lower() for q in ("q4", "q8", "iq"))

    weights_mb = size_gb * 1024.0
    if n_gpu <= 0:
        weights_ram_mb = weights_mb
    else:
        gpu_frac = min(1.0, float(n_gpu) / max(1, n_layers))
        weights_ram_mb = weights_mb * max(0.05, 1.0 - gpu_frac)

    kv_mb = _kv_cache_mb(n_ctx, n_layers, quant=kv_quant)
    compute_mb = _compute_graph_reserve_mb(n_ctx, n_batch)
    total_mb = weights_ram_mb + kv_mb + compute_mb

    model_name = snap.get("model_name") or (Path(model_path).name if model_path else "unknown")
    load_mode = str(snap.get("load_mode") or ("GPU" if n_gpu > 0 else "CPU"))

    return {
        "model_name": model_name,
        "size_gb": round(size_gb, 2),
        "n_ctx": n_ctx,
        "n_batch": n_batch,
        "n_gpu_layers": n_gpu,
        "n_layers": n_layers,
        "weights_ram_mb": round(weights_ram_mb, 0),
        "kv_cache_mb": round(kv_mb, 0),
        "compute_reserve_mb": round(compute_mb, 0),
        "estimated_total_mb": round(total_mb, 0),
        "load_mode": load_mode,
        "kv_quantized": kv_quant,
    }


def _conversational_opener(question: str, est: Dict[str, Any]) -> str:
    """One-line human summary so RAM answers don't read like a log dump."""
    low = str(question or "").lower()
    casual = bool(re.search(r"\b(hey|pal|mate|buddy|honestly|quick question)\b", low))
    total_gb = est["estimated_total_mb"] / 1024.0
    mode = str(est.get("load_mode") or "CPU")
    opener = (
        f"{'Hey — ' if casual else ''}You're asking about inference RAM — "
        "the loaded model and KV cache in memory, not my SQLite memory database "
        "(that's tiny on disk, usually under a megabyte)."
    )
    opener += (
        f" Right now I'm holding about {total_gb:.1f} GB in RAM for inference "
        f"({mode}, {est['n_ctx']} token context)."
    )
    return opener


def format_inference_footprint_report(
    *,
    include_latency_note: bool = False,
    question: str = "",
) -> str:
    snap = _read_snapshot()
    est = estimate_inference_ram_mb(snap)
    lines = [
        _conversational_opener(question, est),
        "",
        "Breakdown (live estimate):",
        f"- model: {est['model_name']} ({est['size_gb']} GB weights on disk)",
        f"- load mode: {est['load_mode']} ({est['n_gpu_layers']} of {est['n_layers']} layers on GPU)",
        f"- context window: {est['n_ctx']} tokens · batch: {est['n_batch']}",
        f"- model weights in RAM: ~{est['weights_ram_mb']:.0f} MB",
        f"- KV cache (context): ~{est['kv_cache_mb']:.0f} MB"
        + (" (quantized)" if est.get("kv_quantized") else ""),
        f"- compute/scratch reserve: ~{est['compute_reserve_mb']:.0f} MB",
        (
            f"- estimated inference RAM total: ~{est['estimated_total_mb']:.0f} MB "
            f"(~{est['estimated_total_mb'] / 1024:.1f} GB for this session's load settings)"
        ),
    ]

    try:
        import psutil
        vm = psutil.virtual_memory()
        lines.append(
            f"- whole-machine RAM: {vm.percent:.0f}% used "
            f"({vm.used / (1024 ** 3):.1f} GB / {vm.total / (1024 ** 3):.1f} GB) — "
            "includes ELI, the desktop, and everything else running"
        )
    except Exception:
        log.debug("psutil unavailable for system RAM line", exc_info=True)

    if include_latency_note or int(est.get("n_gpu_layers") or 0) <= 0:
        lines.append(
            "- latency: with 0 GPU layers, tokens run on CPU — most RAM here is "
            "model weights + KV cache. Lower ctx or batch reduces RAM and often speeds replies."
        )
    lines.append(
        "- note: SQLite / FAISS memory stores are separate and much smaller than inference RAM."
    )
    return "\n".join(lines)
