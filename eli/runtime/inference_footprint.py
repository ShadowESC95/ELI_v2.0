"""Live inference RAM — read from the loaded llama.cpp model and this process, never guessed."""
from __future__ import annotations

import os
import re
import time
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


def _get_live_llm():
    try:
        import eli.cognition.gguf_inference as ggi
        return getattr(ggi, "_llm", None)
    except Exception:
        log.debug("gguf_inference import for live llm failed", exc_info=True)
        return None


def _bytes_to_mb(value: int | float) -> float:
    return round(float(value) / (1024 * 1024), 1)


def _fmt_mb(value: int | float) -> str:
    return f"{_bytes_to_mb(value):.1f} MB"


def capture_process_rss_bytes() -> int:
    import psutil
    return int(psutil.Process(os.getpid()).memory_info().rss)


def _process_memory() -> Dict[str, int]:
    import psutil
    p = psutil.Process(os.getpid())
    mi = p.memory_info()
    out: Dict[str, int] = {"rss_bytes": int(mi.rss)}
    try:
        full = p.memory_full_info()
        uss = int(getattr(full, "uss", 0) or 0)
        if uss > 0:
            out["uss_bytes"] = uss
    except Exception:
        log.debug("process uss unavailable", exc_info=True)
    return out


def _read_llama_live(llm) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if llm is None:
        return out
    try:
        import llama_cpp.llama_cpp as lc
    except Exception:
        log.debug("llama_cpp native bindings unavailable", exc_info=True)
        return out

    model = getattr(llm, "model", None)
    ctx = getattr(llm, "ctx", None)
    if model is not None:
        try:
            out["model_bytes"] = int(lc.llama_model_size(model))
        except Exception:
            log.debug("llama_model_size failed", exc_info=True)
        try:
            out["n_params"] = int(lc.llama_model_n_params(model))
        except Exception:
            log.debug("llama_model_n_params failed", exc_info=True)
    if ctx is not None:
        try:
            out["n_ctx_live"] = int(lc.llama_n_ctx(ctx))
        except Exception:
            log.debug("llama_n_ctx failed", exc_info=True)
        try:
            out["kv_state_bytes"] = int(lc.llama_get_state_size(ctx))
        except Exception:
            log.debug("llama_get_state_size failed", exc_info=True)
        try:
            mem = lc.llama_get_memory(ctx)
            if mem:
                pos = int(lc.llama_memory_seq_pos_max(mem, 0))
                if pos >= 0:
                    out["tokens_in_context"] = pos + 1
        except Exception:
            log.debug("llama memory seq pos failed", exc_info=True)
    return out


def _gpu_process_vram_bytes() -> Optional[int]:
    """VRAM bytes used by this PID, when nvidia-smi exposes it."""
    try:
        from eli.core.hardware_profile import nvidia_smi_path
        smi = nvidia_smi_path()
        if not smi:
            return None
        import subprocess
        pid = os.getpid()
        proc = subprocess.run(
            [
                smi,
                "--query-compute-apps=pid,used_gpu_memory",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        if proc.returncode != 0:
            return None
        total = 0
        for line in (proc.stdout or "").splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) != 2:
                continue
            try:
                if int(parts[0]) == pid:
                    total += int(float(parts[1])) * 1024 * 1024
            except ValueError:
                continue
        return total if total > 0 else None
    except Exception:
        log.debug("gpu process vram probe failed", exc_info=True)
        return None


def record_load_memory(llm, *, pre_load_rss_bytes: int) -> Dict[str, Any]:
    """Capture exact RAM before/after model load — called from the loader."""
    llama = _read_llama_live(llm)
    post = _process_memory()
    post_rss = int(post["rss_bytes"])
    model_bytes = int(llama.get("model_bytes") or 0)
    load_delta = max(0, post_rss - int(pre_load_rss_bytes))
    context_alloc_bytes = max(0, load_delta - model_bytes) if model_bytes else load_delta
    return {
        "source": "measured_at_load",
        "ts": time.time(),
        "pid": os.getpid(),
        "pre_load_rss_bytes": int(pre_load_rss_bytes),
        "post_load_rss_bytes": post_rss,
        "load_delta_rss_bytes": load_delta,
        "model_bytes": model_bytes,
        "context_alloc_bytes": context_alloc_bytes,
        "n_ctx_live": llama.get("n_ctx_live"),
        "n_params": llama.get("n_params"),
    }


def read_live_inference_memory(
    *,
    llm=None,
    snap: Optional[dict] = None,
) -> Dict[str, Any]:
    """Read what is in RAM right now — llama.cpp sizes + this process RSS."""
    snap = dict(snap or _read_snapshot())
    llm = llm if llm is not None else _get_live_llm()
    loaded = llm is not None or bool(snap.get("loaded"))

    eff = snap.get("effective") if isinstance(snap.get("effective"), dict) else {}
    if not eff:
        eff = snap

    out: Dict[str, Any] = {
        "loaded": loaded,
        "source": "live",
        "ts": time.time(),
        "pid": os.getpid(),
        "model_name": snap.get("model_name") or "",
        "model_path": snap.get("model_path") or "",
        "load_mode": snap.get("load_mode") or ("GPU" if int(eff.get("n_gpu_layers") or 0) > 0 else "CPU"),
        "n_ctx": int(eff.get("n_ctx") or snap.get("n_ctx") or 0),
        "n_batch": int(eff.get("n_batch") or snap.get("n_batch") or 0),
        "n_gpu_layers": int(eff.get("n_gpu_layers") or snap.get("n_gpu_layers") or 0),
        "measured_at_load": dict(snap.get("live_inference_memory") or {}),
    }

    if not loaded:
        out["inference_active"] = False
        return out

    llama = _read_llama_live(llm)
    proc = _process_memory()
    out.update(llama)
    out.update(proc)

    gpu_vram = _gpu_process_vram_bytes()
    if gpu_vram is not None:
        out["gpu_vram_bytes"] = gpu_vram

    at_load = out.get("measured_at_load") or {}
    pre_load = int(at_load.get("pre_load_rss_bytes") or 0)
    if pre_load > 0:
        out["inference_rss_bytes"] = max(0, int(proc["rss_bytes"]) - pre_load)
    elif int(at_load.get("load_delta_rss_bytes") or 0) > 0:
        out["inference_rss_bytes"] = int(at_load["load_delta_rss_bytes"])

    model_bytes = int(out.get("model_bytes") or at_load.get("model_bytes") or 0)
    context_bytes = int(out.get("context_alloc_bytes") or at_load.get("context_alloc_bytes") or 0)
    if model_bytes and context_bytes:
        out["inference_components_bytes"] = model_bytes + context_bytes
    elif int(out.get("inference_rss_bytes") or 0) > 0:
        out["inference_components_bytes"] = int(out["inference_rss_bytes"])

    out["inference_active"] = True
    return out


def refresh_live_inference_memory(*, llm=None, snap: Optional[dict] = None) -> Dict[str, Any]:
    """Refresh and optionally persist live inference memory into runtime_snapshot."""
    live = read_live_inference_memory(llm=llm, snap=snap)
    try:
        from eli.core.paths import get_paths
        snap_path = Path(get_paths().artifacts_dir) / "runtime_snapshot.json"
        existing = {}
        if snap_path.is_file():
            import json
            existing = json.loads(snap_path.read_text(encoding="utf-8"))
        existing["live_inference_memory"] = {
            k: v for k, v in live.items()
            if k not in ("measured_at_load",)
        }
        if live.get("measured_at_load"):
            existing["live_inference_memory"]["measured_at_load"] = live["measured_at_load"]
        snap_path.write_text(__import__("json").dumps(existing, indent=2), encoding="utf-8")
    except Exception:
        log.debug("live inference memory snapshot write failed", exc_info=True)
    return live


def _conversational_opener(question: str, live: Dict[str, Any]) -> str:
    low = str(question or "").lower()
    casual = bool(re.search(r"\b(hey|pal|mate|buddy|honestly|quick question)\b", low))

    if not live.get("loaded") and not live.get("inference_active"):
        return (
            f"{'Hey — ' if casual else ''}No model is loaded right now, so I'm not "
            "using inference RAM — just the normal ELI process overhead."
        )

    headline_bytes = (
        int(live.get("inference_rss_bytes") or 0)
        or int(live.get("inference_components_bytes") or 0)
        or int(live.get("rss_bytes") or 0)
    )
    headline_gb = headline_bytes / (1024 ** 3)
    mode = str(live.get("load_mode") or "CPU")
    n_ctx = int(live.get("n_ctx_live") or live.get("n_ctx") or 0)

    opener = (
        f"{'Hey — ' if casual else ''}You're asking about inference RAM — "
        "what the loaded model and context actually hold in memory right now, "
        "not my SQLite memory database (that's a separate tiny store on disk)."
    )
    opener += (
        f" Measured live: {headline_gb:.2f} GB for inference "
        f"({mode}, {n_ctx} token context window)."
    )
    return opener


def format_inference_footprint_report(
    *,
    include_latency_note: bool = False,
    question: str = "",
) -> str:
    live = refresh_live_inference_memory()
    lines = [_conversational_opener(question, live), "", "Live measurements (this process, right now):"]

    if not live.get("inference_active"):
        lines.append("- model: not loaded")
        lines.append("- inference RAM: 0 MB (nothing loaded)")
        lines.append(
            "- note: SQLite / FAISS memory stores are separate and much smaller than inference RAM."
        )
        return "\n".join(lines)

    model_name = live.get("model_name") or Path(str(live.get("model_path") or "")).name or "unknown"
    lines.append(f"- model: {model_name}")

    if live.get("model_bytes"):
        lines.append(f"- model weights in RAM (llama.cpp): {_fmt_mb(live['model_bytes'])}")

    at_load = live.get("measured_at_load") or {}
    if at_load.get("context_alloc_bytes"):
        lines.append(
            f"- context allocation at load (measured RSS delta − weights): "
            f"{_fmt_mb(at_load['context_alloc_bytes'])}"
        )
    if at_load.get("load_delta_rss_bytes"):
        lines.append(
            f"- RAM added when model loaded (measured): {_fmt_mb(at_load['load_delta_rss_bytes'])}"
        )

    if live.get("kv_state_bytes"):
        lines.append(f"- KV / context state size now (llama.cpp): {_fmt_mb(live['kv_state_bytes'])}")
    if live.get("tokens_in_context") is not None:
        lines.append(f"- tokens currently in context: {live['tokens_in_context']}")

    lines.append(f"- this ELI process RSS now: {_fmt_mb(live.get('rss_bytes', 0))}")
    if live.get("uss_bytes"):
        lines.append(f"- this ELI process USS now: {_fmt_mb(live['uss_bytes'])}")
    if live.get("inference_rss_bytes"):
        lines.append(
            f"- inference RAM now (RSS − pre-load baseline): {_fmt_mb(live['inference_rss_bytes'])}"
        )
    if live.get("gpu_vram_bytes"):
        lines.append(f"- GPU VRAM used by this process (nvidia-smi): {_fmt_mb(live['gpu_vram_bytes'])}")

    lines.append(
        f"- load mode: {live.get('load_mode')} · "
        f"n_ctx={live.get('n_ctx_live') or live.get('n_ctx')} · "
        f"batch={live.get('n_batch')} · "
        f"gpu_layers={live.get('n_gpu_layers')}"
    )

    try:
        import psutil
        vm = psutil.virtual_memory()
        lines.append(
            f"- whole-machine RAM: {vm.percent:.0f}% used "
            f"({vm.used / (1024 ** 3):.2f} GB / {vm.total / (1024 ** 3):.2f} GB)"
        )
    except Exception:
        log.debug("psutil unavailable for system RAM line", exc_info=True)

    if include_latency_note or int(live.get("n_gpu_layers") or 0) <= 0:
        lines.append(
            "- latency: CPU-only inference runs tokens on the CPU; "
            "most of the RAM above is model weights plus the allocated context buffer."
        )
    lines.append(
        "- note: SQLite / FAISS memory stores are separate and much smaller than inference RAM."
    )
    return "\n".join(lines)
