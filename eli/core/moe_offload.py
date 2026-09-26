"""Keep a mixture-of-experts model's expert tensors in RAM and everything else on the GPU.

An MoE model uses a few of its experts per token, and the experts are most of the file. Putting whole layers on a small
GPU wastes it: the layers that fit carry mostly idle experts. Putting every layer's attention and shared weights on the GPU
and leaving the experts in system memory keeps the parts every token needs on the fast side.

Measured on an RTX 2060 SUPER (8 GB) with Qwen3.6-35B-A3B Q4_K_M, 1,500-token prompt: 8 GPU layers gave 71 tok/s prompt
and 8.3 tok/s generation; all layers with experts in RAM gave 125 tok/s and 21.8 tok/s, and loaded 13 times faster.

llama-cpp-python does not expose llama.cpp's tensor buffer overrides, so the model parameters are patched while the model
is constructed. Modes (setting `moe_expert_offload` or ELI_MOE_EXPERT_OFFLOAD): auto (default: only when the whole model
would not fit in VRAM), on, off.
"""
from __future__ import annotations

import contextlib
import ctypes
import os
import threading
from typing import Any, Dict, Iterator, Optional

from eli.utils.log import get_logger

log = get_logger(__name__)

EXPERT_PATTERN = rb"blk\.\d+\.ffn_(up|down|gate|gate_up)_exps"
_DEFAULT_EXPERT_FRACTION = 0.90
_patch_lock = threading.Lock()
_keepalive: list = []


def mode() -> str:
    raw = (os.environ.get("ELI_MOE_EXPERT_OFFLOAD") or "").strip().lower()
    if not raw:
        try:
            from eli.core.runtime_settings import load_settings
            raw = str((load_settings() or {}).get("moe_expert_offload") or "").strip().lower()
        except Exception:
            raw = ""
    return raw if raw in ("on", "off", "auto") else "auto"


def expert_fraction() -> float:
    try:
        return min(0.98, max(0.5, float(os.environ.get("ELI_MOE_EXPERT_FRACTION", _DEFAULT_EXPERT_FRACTION))))
    except ValueError:
        return _DEFAULT_EXPERT_FRACTION


def profile(model_path: Optional[str]):
    try:
        from eli.cognition.model_load_diagnostics import gguf_model_profile
        return gguf_model_profile(model_path) if model_path else None
    except Exception:
        log.debug("moe: model profile unavailable", exc_info=True)
        return None


def plan(model_path: Optional[str], model_size_gb: float, *, free_vram_mb: int, available_ram_gb: float,
         reserve_mb: int = 700, gpu_supported: bool = True) -> Optional[Dict[str, Any]]:
    """The expert-offload plan for this model on this machine, or None to load it the ordinary way."""
    m = mode()
    if m == "off" or not gpu_supported or int(free_vram_mb) <= 0:
        return None
    prof = profile(model_path)
    if prof is None or not getattr(prof, "is_moe", False):
        return None
    size_mb = float(model_size_gb) * 1024.0
    if m == "auto" and size_mb + int(reserve_mb) <= int(free_vram_mb):
        return None
    experts_gb = float(model_size_gb) * expert_fraction()
    if float(available_ram_gb) < experts_gb * 0.75:
        return None
    return {"resident_gb": round(float(model_size_gb) - experts_gb, 2), "experts_gb": round(experts_gb, 2),
            "layers": int(prof.block_count or 0)}


def plan_for_load(model_path: str, gpu_supported: Optional[bool]) -> Optional[Dict[str, Any]]:
    """The plan at load time, from live memory."""
    try:
        from pathlib import Path
        if gpu_supported is False:
            return None
        from eli.core.hardware_profile import get_live_gpu_telemetry
        free = int(get_live_gpu_telemetry().get("free_mb") or 0)
        try:
            import psutil
            ram_gb = psutil.virtual_memory().available / (1024 ** 3)
        except Exception:
            ram_gb = 0.0
        return plan(model_path, Path(model_path).stat().st_size / (1024 ** 3), free_vram_mb=free, available_ram_gb=ram_gb)
    except Exception:
        log.debug("moe: load plan unavailable", exc_info=True)
        return None


@contextlib.contextmanager
def expert_offload_params() -> Iterator[None]:
    """While a model is constructed, its parameters carry the override that puts expert tensors in system memory."""
    import llama_cpp
    from llama_cpp import llama_cpp as lc
    base = ctypes.CDLL(os.path.join(os.path.dirname(llama_cpp.__file__), "lib", "libggml-base.so"))
    base.ggml_backend_cpu_buffer_type.restype = ctypes.c_void_p
    cpu = base.ggml_backend_cpu_buffer_type()

    class _Override(ctypes.Structure):
        _fields_ = [("pattern", ctypes.c_char_p), ("buft", ctypes.c_void_p)]

    table = (_Override * 2)(_Override(EXPERT_PATTERN, cpu), _Override(None, None))
    _keepalive.append(table)
    with _patch_lock:
        original = lc.llama_model_default_params

        def patched():
            params = original()
            params.tensor_buft_overrides = ctypes.cast(table, ctypes.c_void_p)
            return params
        lc.llama_model_default_params = patched
        try:
            yield
        finally:
            lc.llama_model_default_params = original
