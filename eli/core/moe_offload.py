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
    resident_gb = float(model_size_gb) - experts_gb
    try:
        from eli.core import gguf_sizes
        w = gguf_sizes.weights(model_path)
        if w is not None and w.experts_total > 0:
            # the file's own tensor sizes; the fraction is only for a file whose table cannot be read
            experts_gb = w.experts_total / 1024 ** 3
            resident_gb = w.resident_total / 1024 ** 3
    except Exception:
        log.debug("moe: tensor sizes unreadable", exc_info=True)
    if float(available_ram_gb) < experts_gb * 0.75:
        return None
    return {"resident_gb": round(resident_gb, 2), "experts_gb": round(experts_gb, 2),
            "layers": int(prof.block_count or 0)}


def plan_for_load(model_path: str, gpu_supported: Optional[bool]) -> Optional[Dict[str, Any]]:
    """The plan at load time, from live memory."""
    try:
        from eli.core import mem_units
        if gpu_supported is False:
            return None
        from eli.core.hardware_profile import get_live_gpu_telemetry
        free = int(get_live_gpu_telemetry().get("free_mb") or 0)
        try:
            import psutil
            ram_gb = mem_units.bytes_to_gib(psutil.virtual_memory().available)
        except Exception:
            ram_gb = 0.0
        return plan(model_path, mem_units.file_size_gib(model_path), free_vram_mb=free, available_ram_gb=ram_gb)
    except Exception:
        log.debug("moe: load plan unavailable", exc_info=True)
        return None


def full_offload_layers(n_gpu_layers: Any, model_path: Optional[str]) -> int:
    """llama.cpp counts one more layer than the model has blocks (the output layer).
    Asking for 40 on a 40-block model put the output layer and 39 blocks on the GPU and
    left block 0's attention on the CPU, while ELI reported "40/40" (live load log,
    2026-10-03). An expert-offload request for every block asks for every layer."""
    n = int(n_gpu_layers)
    prof = profile(model_path)
    blocks = int(getattr(prof, "block_count", 0) or 0)
    return blocks + 1 if blocks and 0 < blocks <= n < 99 else n


def _zero_copy_experts_wanted() -> bool:
    return (os.environ.get("ELI_MOE_PINNED_EXPERTS") or "").strip().lower() not in {"1", "true", "yes", "on"}


def apply_zero_copy(params: Any) -> Any:
    """Read the expert tensors straight from the file mapping: no pinned copy, no repack.

    Newer llama.cpp (the 0.3.35 GPU pack) puts CPU-side weights in the GPU backend's
    pinned host buffer (CUDA_Host) and, failing that, repacks them into a CPU layout.
    Both COPY the experts. Live, 2026-10-03, Qwen3.6-35B-A3B on 32 GB RAM with the
    RTX 2060 SUPER: pinning 17.7 GB stalled the load at 12 GB RSS while the system
    swapped (14 minutes, never finished); repack (14.4 GB) loaded in 265 s and
    generated 1.6 tok/s; neither loaded in 18 s and generated 18.3 tok/s.
    ELI_MOE_PINNED_EXPERTS=1 keeps llama.cpp's default, for machines with RAM to spare.
    Fields an older build doesn't have are left alone.
    """
    if not _zero_copy_experts_wanted():
        return params
    fields = {f[0] for f in getattr(type(params), "_fields_", ())}
    if "no_host" in fields:
        params.no_host = True
    if "use_extra_bufts" in fields:
        params.use_extra_bufts = False
    return params


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
            return apply_zero_copy(params)
        lc.llama_model_default_params = patched
        try:
            yield
        finally:
            lc.llama_model_default_params = original
