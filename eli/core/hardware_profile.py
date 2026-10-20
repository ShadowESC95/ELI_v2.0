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

import copy
import functools
import os
import re
import sys
import json
import shutil
import subprocess
import multiprocessing
import time
from dataclasses import dataclass, field
from pathlib import Path

from eli.utils.log import get_logger
from eli.core import mem_units
from eli.core.runtime_settings import ALL_GPU_LAYERS

log = get_logger(__name__)
from typing import Any, Dict, List, Optional


# KV-cache overhead constants, used only when a model file cannot be read
_KV_BYTES_PER_TOKEN_PER_LAYER = 6_000
_CUDA_OVERHEAD_MB = 350


def vram_reserve_mb(*, gpu_integrated: Optional[bool] = None) -> int:
    """GPU memory to keep free beyond what a load itself takes, in MiB: the operator's own figure
    (ELI_VRAM_RESERVE_MB), else the most llama.cpp was measured taking after a load on any GPU of this
    machine (eli/core/load_plan.py, headroom), else 0 until something has been measured. The planner
    asks per card (load_plan.headroom_mb); this is for the checks that look at the machine as a whole
    (Whisper's place, the status report). It was a fixed 700 MB (400 on integrated GPUs), measured once
    on one card: 34-82 MB is what two RTX 2060 SUPER needed. `gpu_integrated` is accepted for older
    callers and changes nothing: integrated GPUs are measured the same way."""
    raw = (os.environ.get("ELI_VRAM_RESERVE_MB") or "").strip()
    if raw.isdigit() and int(raw) > 0:
        return int(raw)
    try:
        from eli.core import load_plan
        seen = [load_plan.measured_headroom(d) for d in load_plan.devices()]
        return int(round(max([h for h in seen if h is not None], default=0.0)))
    except Exception:
        log.debug("measured GPU headroom unavailable", exc_info=True)
        return 0


def _kv_cache_mb(n_ctx: int, n_layers: int = 32, quant: bool = False, *,
                 cost: Optional["ModelCost"] = None) -> float:
    if cost is not None:
        return cost.kv_mb(n_ctx)
    # no readable model file: a size per layer, the last resort
    raw = n_ctx * n_layers * _KV_BYTES_PER_TOKEN_PER_LAYER / 1_048_576
    if not quant:
        return raw
    from eli.core import gguf_sizes
    return raw * gguf_sizes.bytes_per_element(gguf_sizes.QUANTIZED_CACHE) / gguf_sizes.bytes_per_element("f16")


@dataclass(frozen=True)
class ModelCost:
    """A model's own memory costs, read by eli.core.gguf_sizes. With one, the fit functions use
    the file's tensor sizes and KV layout instead of dividing the file size by its layer count."""
    weights: Any
    kv_bytes_per_token: float
    experts_in_ram: bool

    def gpu_weights_mb(self, layers: int) -> float:
        return self.weights.gpu_bytes(int(layers), experts_in_ram=self.experts_in_ram) / 1_048_576

    def kv_mb(self, ctx: int, gpu_layers: Optional[int] = None) -> float:
        """KV for ctx tokens; with gpu_layers, the share that lives on the GPU (llama.cpp keeps
        each layer's cache on that layer's device)."""
        total = max(0, int(ctx)) * self.kv_bytes_per_token / 1_048_576
        if gpu_layers is None:
            return total
        return total * min(1.0, max(0, int(gpu_layers)) / max(1, self.weights.blocks))

    def cpu_weights_mb(self, gpu_layers: int) -> float:
        w = self.weights
        held = w.resident_total + (0 if self.experts_in_ram else w.experts_total) + w.input_bytes
        return max(0, held - w.gpu_bytes(int(gpu_layers), experts_in_ram=self.experts_in_ram)) / 1_048_576


def model_cost(model_path: Optional[str], *, experts_in_ram: bool = False,
               kv_quantized: bool = False, kv_cache_type: Optional[str] = None) -> Optional[ModelCost]:
    """The model's real costs, or None when its file cannot be read (then the estimates apply).
    kv_cache_type is the cache type asked for; kv_quantized alone means the quantized type ELI
    loads (gguf_sizes.QUANTIZED_CACHE). Either way the size is that of the cache that loads."""
    if not model_path:
        return None
    try:
        from eli.core import gguf_sizes
        w = gguf_sizes.weights(model_path)
        if w is None:
            return None
        ctype = kv_cache_type or (gguf_sizes.QUANTIZED_CACHE if kv_quantized else "f16")
        kv = gguf_sizes.kv_bytes_per_token(model_path, ctype)
        if kv is None:
            return None
        return ModelCost(w, float(kv), bool(experts_in_ram))
    except Exception:
        log.debug("model cost unreadable for %s", model_path, exc_info=True)
        return None


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


def layers_for_model(model_path: Optional[str] = None, size_gb: Optional[float] = None) -> int:
    """Layer count for VRAM fit — GGUF ``block_count`` when readable, else size heuristic."""
    if model_path:
        try:
            from eli.cognition.model_load_diagnostics import gguf_model_profile
            prof = gguf_model_profile(model_path)
            if prof.block_count and prof.block_count > 0:
                return int(prof.block_count)
        except Exception:
            log.debug("gguf layer count unavailable for %s", model_path, exc_info=True)
    if size_gb is not None and size_gb > 0:
        return _layers_for_size(float(size_gb))
    return 32


@dataclass
class HardwareProfile:
    cpu_threads: int = 1
    cpu_cores: int = 0            # physical performance cores; 0 when not read
    ram_gb: float = 8.0
    available_ram_gb: float = 8.0
    has_gpu: bool = False
    gpu_name: str = ""
    gpu_vendor: str = ""          # nvidia, amd, intel, apple, unknown
    gpu_integrated: bool = False  # True for iGPU / APU / Apple unified-memory (shared RAM)
    vulkan_available: bool = False
    free_vram_mb: int = 0       # FREE VRAM, not total
    total_vram_mb: int = 0
    vram_gb: float = 0.0        # convenience: free_vram_mb / 1024 (legacy callers)
    # True when has_gpu=False only because a real GPU PCI device exists that no vendor probe could
    # read (timeout, missing tool, permissions), as opposed to no GPU at all. has_gpu stays False
    # either way; reporting code uses this to say which.
    gpu_detection_uncertain: bool = False
    # Each GPU on its own, as the vendor's tool or the driver reports it: {index, name, vendor,
    # free_mb, total_mb, integrated}. free_vram_mb / total_vram_mb are their sums. llama.cpp's own
    # device list (load_plan.devices) is what loads use; this is the view before it is loaded.
    gpus: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cpu_threads": self.cpu_threads,
            "cpu_cores": self.cpu_cores,
            "ram_gb": round(self.ram_gb, 1),
            "available_ram_gb": round(self.available_ram_gb, 1),
            "has_gpu": self.has_gpu,
            "gpu_name": self.gpu_name,
            "gpu_vendor": self.gpu_vendor,
            "gpu_integrated": self.gpu_integrated,
            "vulkan_available": self.vulkan_available,
            "free_vram_mb": self.free_vram_mb,
            "total_vram_mb": self.total_vram_mb,
            "vram_gb": round(self.vram_gb, 1),
            "gpu_detection_uncertain": self.gpu_detection_uncertain,
            "gpus": [dict(g) for g in self.gpus],
        }


@dataclass
class ModelRecommendation:
    model_path: str = ""
    model_name: str = ""
    model_size_gb: float = 0.0
    n_gpu_layers: int = 0
    n_ctx: int = 0              # set by recommend(); 0 until then
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

    # Model-agnostic scaling of the sample/branch counts (per-stage token budgets already follow
    # base_max). tier_scale() is 1.0 for the current small model and rises for larger ones, so a
    # stronger model gets more samples instead of the small-model default of 3.
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
            # CoT spends tokens on hidden reasoning before the visible answer, so it needs more than
            # the base budget (below ~1536 the answer truncates mid-reasoning). Floor there whenever
            # ctx allows; tiny-ctx machines keep a proportional cap.
            "max_tokens": max(int(base_max * 0.85),
                              min(1536, max(256, int(_base_n_ctx * 0.4)))),
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


def _external_tool_env() -> Dict[str, str]:
    """Environment for subprocess calls to a SYSTEM binary (nvidia-smi,
    rocm-smi, lspci) — never the frozen app's own inherited environment.

    PyInstaller's bootloader points LD_LIBRARY_PATH at the bundle's own
    _internal/ dir so ELI's bundled .so files take precedence over the
    system's, and saves the pre-bootloader value in LD_LIBRARY_PATH_ORIG for
    exactly this situation. Calling a real system binary without restoring it
    hands that binary the WRONG shared libraries by soname — nvidia-smi can
    then fail to run at all, which silently falls through to a conservative
    4096 MB VRAM guess and roughly halves every GPU layer count downstream.
    Not frozen: LD_LIBRARY_PATH_ORIG is unset and this is a no-op copy.
    """
    from eli.core.host_env import host_env
    return host_env()


def nvidia_smi_path() -> Optional[str]:
    """Absolute path to nvidia-smi, PATH or not.

    On Windows nvidia-smi is frequently NOT on PATH: the driver drops it in
    System32 and the CUDA toolkit in its own directory, and a frozen
    PyInstaller app inherits a different environment again. Calling it by bare
    name therefore fails on machines that have a perfectly good GPU -- which
    is precisely how a working NVIDIA card ended up reported as absent.
    """
    found = shutil.which("nvidia-smi")
    if found:
        return found
    if os.name == "nt":
        candidates = [
            Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "nvidia-smi.exe",
            Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
            / "NVIDIA Corporation" / "NVSMI" / "nvidia-smi.exe",
            Path(os.environ.get("ProgramW6432", r"C:\Program Files"))
            / "NVIDIA Corporation" / "NVSMI" / "nvidia-smi.exe",
        ]
    else:
        candidates = [
            Path("/usr/bin/nvidia-smi"), Path("/usr/local/bin/nvidia-smi"),
            Path("/opt/nvidia/bin/nvidia-smi"),
        ]
    for c in candidates:
        try:
            if c.is_file():
                return str(c)
        except Exception:
            log.debug("nvidia-smi probe failed", exc_info=True)
    return None


def _macos_gpus() -> List[tuple]:
    """[(name, vram_mb)] on macOS. Apple Silicon reports unified memory."""
    if sys.platform != "darwin":
        return []
    sp = shutil.which("system_profiler")
    if not sp:
        return []
    try:
        raw = subprocess.check_output([sp, "-json", "SPDisplaysDataType"],
                                      stderr=subprocess.DEVNULL, timeout=30)
        import json as _json
        data = _json.loads(raw.decode("utf-8", "replace"))
    except Exception:
        log.debug("macOS GPU enumeration failed", exc_info=True)
        return []
    gpus = []
    for item in (data.get("SPDisplaysDataType") or []):
        name = str(item.get("sppci_model") or item.get("_name") or "").strip()
        if not name:
            continue
        mb = 0
        # Discrete cards report VRAM directly; Apple Silicon does not, because
        # the GPU shares system memory. Report 0 and let the caller decide.
        for key in ("spdisplays_vram_shared", "spdisplays_vram", "sppci_vram"):
            val = str(item.get(key) or "").strip()
            if not val:
                continue
            try:
                num = float(val.split()[0])
                mb = int(num * 1024) if "gb" in val.lower() else int(num)
                break
            except Exception:
                continue
        gpus.append((name, mb))
    return gpus


def _windows_dxgi_adapters(software: bool = False) -> Optional[List[Dict[str, Any]]]:
    """Every graphics adapter on Windows, any vendor, from DXGI (the API every Windows GPU driver
    implements): name, vendor, dedicated memory, and — IDXGIAdapter3.QueryVideoMemoryInfo, Windows 10
    and later — the memory budget Windows gives this process on that adapter and how much of it is
    in use, so free memory is the driver's figure, not a guess. The software renderer is left out
    unless `software` (a machine without a GPU, such as a CI runner, has only that one). None off
    Windows or when DXGI cannot be asked."""
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    class _LUID(ctypes.Structure):
        _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]

    class _DESC1(ctypes.Structure):
        _fields_ = [("Description", wintypes.WCHAR * 128), ("VendorId", wintypes.UINT),
                    ("DeviceId", wintypes.UINT), ("SubSysId", wintypes.UINT), ("Revision", wintypes.UINT),
                    ("DedicatedVideoMemory", ctypes.c_size_t), ("DedicatedSystemMemory", ctypes.c_size_t),
                    ("SharedSystemMemory", ctypes.c_size_t), ("AdapterLuid", _LUID), ("Flags", wintypes.UINT)]

    class _MEMINFO(ctypes.Structure):
        _fields_ = [("Budget", ctypes.c_uint64), ("CurrentUsage", ctypes.c_uint64),
                    ("AvailableForReservation", ctypes.c_uint64), ("CurrentReservation", ctypes.c_uint64)]

    class _GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                    ("Data4", ctypes.c_ubyte * 8)]

    def _guid(text: str) -> "_GUID":
        h = text.replace("-", "")
        return _GUID(int(h[0:8], 16), int(h[8:12], 16), int(h[12:16], 16),
                     (ctypes.c_ubyte * 8)(*bytes.fromhex(h[16:32])))

    def _call(obj, index, restype, *types):
        vtable = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        return ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *types)(vtable[index])

    iid_factory1 = _guid("770aae78-f26f-4dba-a829-253c83d1b387")
    iid_adapter3 = _guid("645967a4-1392-4310-a798-8053ce3e93fd")
    try:
        dxgi = ctypes.WinDLL("dxgi")
        factory = ctypes.c_void_p()
        if dxgi.CreateDXGIFactory1(ctypes.byref(iid_factory1), ctypes.byref(factory)) != 0 or not factory:
            return None
    except Exception:
        log.debug("DXGI unavailable", exc_info=True)
        return None
    adapters: List[Dict[str, Any]] = []
    try:
        index = 0
        while index < 64:
            adapter = ctypes.c_void_p()
            # IDXGIFactory1::EnumAdapters1 (vtable 12); DXGI_ERROR_NOT_FOUND ends the list
            if _call(factory, 12, ctypes.c_long, wintypes.UINT, ctypes.POINTER(ctypes.c_void_p))(
                    factory, index, ctypes.byref(adapter)) != 0 or not adapter:
                break
            index += 1
            try:
                desc = _DESC1()
                # IDXGIAdapter1::GetDesc1 (vtable 10); flag 2 is the software renderer
                if _call(adapter, 10, ctypes.c_long, ctypes.POINTER(_DESC1))(adapter, ctypes.byref(desc)) != 0 \
                        or (desc.Flags & 2 and not software):
                    continue
                dedicated = int(desc.DedicatedVideoMemory) // 1_048_576
                shared = int(desc.SharedSystemMemory) // 1_048_576
                entry: Dict[str, Any] = {
                    "index": len(adapters), "name": desc.Description.strip(),
                    "vendor": _PCI_VENDORS.get(int(desc.VendorId), "unknown"),
                    # an integrated GPU keeps a small carve-out (or none) and works from shared memory
                    "integrated": dedicated < 512 and shared > dedicated,
                    "total_mb": dedicated if dedicated >= 512 else shared,
                    "free_mb": None, "used_mb": None}
                a3 = ctypes.c_void_p()
                # IUnknown::QueryInterface (vtable 0) for IDXGIAdapter3
                if _call(adapter, 0, ctypes.c_long, ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p))(
                        adapter, ctypes.byref(iid_adapter3), ctypes.byref(a3)) == 0 and a3:
                    try:
                        info = _MEMINFO()
                        # QueryVideoMemoryInfo (vtable 14): node 0, local segment (the adapter's own
                        # memory; on an integrated GPU, the share of system memory it may use)
                        if _call(a3, 14, ctypes.c_long, wintypes.UINT, ctypes.c_int, ctypes.POINTER(_MEMINFO))(
                                a3, 0, 0, ctypes.byref(info)) == 0 and info.Budget:
                            budget = int(info.Budget) // 1_048_576
                            used = int(info.CurrentUsage) // 1_048_576
                            entry["free_mb"] = max(0, budget - used)
                            entry["used_mb"] = max(0, int(entry["total_mb"]) - entry["free_mb"])
                    finally:
                        _call(a3, 2, ctypes.c_ulong)(a3)
                adapters.append(entry)
            finally:
                _call(adapter, 2, ctypes.c_ulong)(adapter)
    except Exception:
        log.debug("DXGI adapter enumeration failed", exc_info=True)
    finally:
        _call(factory, 2, ctypes.c_ulong)(factory)
    return adapters


def _macos_accelerators() -> Optional[List[Dict[str, Any]]]:
    """Every GPU on macOS from the IOAccelerator registry (no root needed): name, use and the memory
    the driver reports in use or free — Apple Silicon and Intel Macs with AMD cards alike. None off
    macOS or when ioreg cannot be read."""
    if sys.platform != "darwin":
        return None
    import plistlib
    try:
        raw = subprocess.run([shutil.which("ioreg") or "/usr/sbin/ioreg", "-r", "-d", "1", "-c", "IOAccelerator",
                              "-a"], capture_output=True, timeout=10, check=False, env=_external_tool_env()).stdout
        entries = plistlib.loads(raw) if raw else []
    except Exception:
        log.debug("ioreg IOAccelerator query failed", exc_info=True)
        return None
    cards: List[Dict[str, Any]] = []
    for item in entries if isinstance(entries, list) else [entries]:
        if not isinstance(item, dict):
            continue
        stats = item.get("PerformanceStatistics") or {}

        def _stat(*names):
            for key, value in stats.items():
                if any(n.lower() in str(key).lower() for n in names) and isinstance(value, (int, float)):
                    return float(value)
            return None

        free_b, used_b = _stat("vramFreeBytes"), _stat("vramUsedBytes", "In use system memory")
        name = item.get("model") or item.get("IOGLBundleName") or item.get("IOClass") or "GPU"
        name = (name.decode("utf-8", "replace") if isinstance(name, bytes) else str(name)).strip("\x00 ")
        apple = "apple" in name.lower() or "AGX" in str(item.get("IOClass") or "")
        cards.append({
            "index": len(cards), "name": name, "vendor": "apple" if apple else (
                "amd" if "amd" in str(item.get("IOClass") or "").lower() else "unknown"),
            "integrated": apple,
            "total_mb": None if free_b is None or used_b is None else (free_b + used_b) / 1_048_576,
            "free_mb": None if free_b is None else free_b / 1_048_576,
            "used_mb": None if used_b is None else used_b / 1_048_576,
            "util_pct": _stat("Device Utilization %", "GPU Activity"),
            "temp_c": _stat("Temperature"), "power_w": None, "power_limit_w": None})
    return cards


def _nvidia_gpu_model_from_proc() -> str:
    """GPU model name straight from the NVIDIA kernel module's own /proc
    interface — populated from the hardware itself, independent of the NVML/
    nvidia-smi userspace library version. Still readable when nvidia-smi fails
    with a driver/library version mismatch."""
    try:
        for info_file in Path("/proc/driver/nvidia/gpus").glob("*/information"):
            for line in info_file.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("Model:"):
                    return line.split(":", 1)[1].strip()
    except Exception:
        log.debug("suppressed exception", exc_info=True)
    return ""


def _nvidia_driver_loaded() -> bool:
    """True when the NVIDIA kernel driver is loaded — using kernel-provided signals
    that exist identically on every Linux distro (Ubuntu/Debian/Arch/Fedora/RHEL/
    openSUSE), independent of whether nvidia-smi is installed or well-behaved:
    ``/proc/driver/nvidia/version``, ``/sys/module/nvidia``, or a PCI device whose
    vendor id is NVIDIA (0x10de)."""
    try:
        if Path("/proc/driver/nvidia/version").is_file() or Path("/sys/module/nvidia").is_dir():
            return True
        for e in Path("/sys/bus/pci/devices").glob("*/vendor"):
            try:
                if e.read_text().strip().lower() == "0x10de":
                    return True
            except Exception:
                continue
    except Exception:
        log.debug("suppressed exception", exc_info=True)
    return False


_PCI_VENDORS = {0x10DE: "nvidia", 0x1002: "amd", 0x8086: "intel", 0x5143: "qualcomm", 0x106B: "apple"}
# GPUs that are not PCI devices, by their kernel driver: Qualcomm Adreno on Snapdragon laptops,
# Apple's GPU under Asahi Linux
_DRM_DRIVER_VENDORS = {"msm": "qualcomm", "asahi": "apple"}
_DRM_ROOT = Path("/sys/class/drm")


def _linux_drm_gpus() -> List[tuple]:
    """(vendor, device directory) for each GPU the Linux kernel's display layer has, once per device:
    PCI cards by vendor id, system-on-chip GPUs by driver. Empty off Linux."""
    if not sys.platform.startswith("linux"):
        return []
    found: List[tuple] = []
    seen: set = set()
    for card in sorted(_DRM_ROOT.glob("card[0-9]*")):
        if "-" in card.name:            # a connector (card0-DP-1), not a device
            continue
        dev = card / "device"
        try:
            real = dev.resolve()
        except OSError:
            continue
        if real in seen:
            continue
        try:
            vendor = _PCI_VENDORS.get(int((dev / "vendor").read_text().strip(), 16))
        except (OSError, ValueError):
            try:
                vendor = _DRM_DRIVER_VENDORS.get((dev / "driver").resolve().name)
            except OSError:
                vendor = None
        if vendor:
            seen.add(real)
            found.append((vendor, dev))
    return found


_INTEL_ARC_DEVICE_RANGES = ((0x4F80, 0x4F8F), (0x5690, 0x56BF), (0xE200, 0xE21F))


def _intel_pci_device_is_discrete_arc(dev: Path) -> bool:
    """True for discrete Intel Arc — not laptop Iris Xe / UHD iGPUs."""
    try:
        if (dev / "driver").resolve().name.lower() == "xe":
            did = int((dev / "device").read_text().strip(), 16)
            if any(lo <= did <= hi for lo, hi in _INTEL_ARC_DEVICE_RANGES):
                return True
    except Exception:
        log.debug("suppressed exception", exc_info=True)
    try:
        did = int((dev / "device").read_text().strip(), 16)
        return any(lo <= did <= hi for lo, hi in _INTEL_ARC_DEVICE_RANGES)
    except Exception:
        return False


def _vulkan_loader_present() -> bool:
    """True when the OS Vulkan loader is installed (GPU drivers normally ship it)."""
    try:
        if sys.platform == "win32":
            return (Path(os.environ.get("SystemRoot", r"C:\Windows"))
                    / "System32" / "vulkan-1.dll").is_file()
        import ctypes.util
        return bool(ctypes.util.find_library("vulkan"))
    except Exception:
        return False


RAM_BUDGET_PERCENT_MIN = 10
RAM_BUDGET_PERCENT_MAX = 75
RAM_BUDGET_PERCENT_DEFAULT = 60


def _cpu_list(text: str) -> List[int]:
    """A kernel CPU list ("0-3,8,10-11") as numbers."""
    out: List[int] = []
    for part in str(text or "").strip().split(","):
        if "-" in part:
            a, b = part.split("-", 1)
            out.extend(range(int(a), int(b) + 1))
        elif part.strip():
            out.append(int(part))
    return out


def physical_performance_cores() -> int:
    """The cores llama.cpp's arithmetic runs best on: physical cores, and on a hybrid processor its
    performance cores only (llama.cpp's own default). Two threads on one core share its vector units."""
    logical = os.cpu_count() or 1
    try:
        # hybrid Intel on Linux: the kernel lists the performance cores' logical CPUs here
        p_cpus = _cpu_list(Path("/sys/devices/cpu_core/cpus").read_text(encoding="utf-8"))
        cores = set()
        for n in p_cpus:
            topo = Path(f"/sys/devices/system/cpu/cpu{n}/topology")
            cores.add(((topo / "physical_package_id").read_text().strip(), (topo / "core_id").read_text().strip()))
        if cores:
            return len(cores)
    except (OSError, ValueError):
        log.debug("no performance-core list: not a hybrid Intel processor on Linux")
    if sys.platform == "darwin":
        try:
            out = subprocess.run(["sysctl", "-n", "hw.perflevel0.physicalcpu"], capture_output=True,
                                 text=True, timeout=5, check=False).stdout.strip()
            if out.isdigit() and int(out) > 0:
                return int(out)
        except Exception:
            log.debug("performance core count unavailable", exc_info=True)
    try:
        import psutil
        physical = psutil.cpu_count(logical=False)
        if physical:
            return int(physical)
    except Exception:
        log.debug("physical core count unavailable", exc_info=True)
    return logical


def recommend_cpu_threads(cpu_threads: Optional[int] = None, *, physical: Optional[int] = None) -> int:
    """Threads for llama.cpp: the physical performance cores.

    A core running two threads shares its vector units between them, so threads beyond the cores
    slow llama.cpp down; measured on an i7-8700 (6 cores, 12 threads), the processor wrote 4.37
    tokens/s at 6 threads, 4.31 at 10 and 3.99 at 12, and with layers on a GPU the count made no
    difference. With hyper-threads the desktop keeps the second thread of every core; without them
    one core is left for it.

    `cpu_threads` is the logical CPU count and `physical` the core count; a caller that passes the
    first without the second has no core count, and the logical count stands for it. With neither,
    both are read from this machine."""
    if cpu_threads is None:
        logical = os.cpu_count() or 1
        cores = int(physical or physical_performance_cores())
    else:
        logical = max(1, int(cpu_threads))
        cores = int(physical) if physical else logical
    cores = max(1, min(cores, logical))
    return cores if logical > cores else max(1, cores - 1)


def ram_budget_fraction() -> float:
    """User-chosen fraction of available RAM for model weights + KV (cap 75%)."""
    pct: float | None = None
    try:
        from eli.core.runtime_settings import load_settings
        raw = (load_settings() or {}).get("ram_budget_percent")
        if raw is not None:
            pct = float(raw)
    except Exception:
        log.debug("suppressed exception", exc_info=True)
    if pct is None:
        env = (os.environ.get("ELI_RAM_BUDGET_PERCENT")
               or os.environ.get("ELI_RAM_BUDGET_FRACTION") or "").strip()
        if env:
            try:
                pct = float(env) * 100.0 if float(env) <= 1.0 else float(env)
            except Exception:
                pct = None
    if pct is None:
        # CPU-only / shared-memory iGPU machines ≤16 GB: prefer more of free RAM
        # for weights+KV (still capped at 75%). Discrete-GPU hosts keep 60%.
        try:
            hw = detect_hardware()
            _cpu_bound = (not bool(getattr(hw, "has_gpu", False))) or bool(
                getattr(hw, "gpu_integrated", False)
            )
            if _cpu_bound and float(getattr(hw, "ram_gb", 0) or 0) <= 16.0:
                pct = 70.0
            else:
                pct = float(RAM_BUDGET_PERCENT_DEFAULT)
        except Exception:
            pct = float(RAM_BUDGET_PERCENT_DEFAULT)
    lo = RAM_BUDGET_PERCENT_MIN / 100.0
    hi = RAM_BUDGET_PERCENT_MAX / 100.0
    return max(lo, min(hi, pct / 100.0))


FIT_PRIORITY_BALANCED = "balanced"
FIT_PRIORITY_MAX_GPU = "max_gpu"
FIT_PRIORITY_MAX_CTX = "max_ctx"
FIT_PRIORITIES = (
    FIT_PRIORITY_BALANCED,
    FIT_PRIORITY_MAX_GPU,
    FIT_PRIORITY_MAX_CTX,
)


def normalize_fit_priority(value: Optional[str] = None) -> str:
    """Return a valid fit priority token."""
    raw = (value or "").strip().lower().replace("-", "_")
    aliases = {
        "balance": FIT_PRIORITY_BALANCED,
        "gpu": FIT_PRIORITY_MAX_GPU,
        "maxgpu": FIT_PRIORITY_MAX_GPU,
        "max_gpu_layers": FIT_PRIORITY_MAX_GPU,
        "ctx": FIT_PRIORITY_MAX_CTX,
        "maxcontext": FIT_PRIORITY_MAX_CTX,
        "max_context": FIT_PRIORITY_MAX_CTX,
    }
    if raw in FIT_PRIORITIES:
        return raw
    return aliases.get(raw, FIT_PRIORITY_BALANCED)


def fit_priority() -> str:
    """User-chosen fit priority from settings or ELI_FIT_PRIORITY."""
    chosen: Optional[str] = None
    try:
        from eli.core.runtime_settings import load_settings
        raw = (load_settings() or {}).get("fit_priority")
        if raw is not None:
            chosen = str(raw)
    except Exception:
        log.debug("fit_priority settings read failed", exc_info=True)
    if not chosen:
        chosen = (os.environ.get("ELI_FIT_PRIORITY") or "").strip()
    return normalize_fit_priority(chosen)


def _estimate_integrated_vram_mb(ram_gb: float, available_ram_gb: float) -> tuple[int, int]:
    """Shared-memory budget for iGPU / APU / unified-memory systems.

    Same fraction-of-available-RAM basis as cpu_ram_budget_mb, uncapped.
    Unified memory on Apple Silicon and AMD APUs ranges from 8GB laptops to
    64-192GB Mac Studios / workstations; a flat ceiling here used to ignore
    that entirely (every one of those machines got capped at the same 8192MB
    GPU-layer budget as an 8GB laptop iGPU), throwing away most of a big
    unified pool's actual capacity on exactly the hardware whose whole selling
    point is having one.
    """
    frac = ram_budget_fraction()
    # Budget from AVAILABLE RAM (same basis as cpu_ram_budget_mb), not installed RAM.
    free_mb = int(max(0.0, float(available_ram_gb or 0)) * 1024.0 * frac)
    return free_mb, free_mb


# llama.cpp backends that run on one maker's cards only; Vulkan and others are told by the card's name
_BACKEND_VENDORS = {"cuda": "nvidia", "rocm": "amd", "hip": "amd", "mtl": "apple", "metal": "apple",
                    "sycl": "intel"}
_NAME_VENDORS = (("nvidia", ("nvidia", "geforce", "quadro", "tesla")), ("amd", ("amd", "radeon")),
                 ("intel", ("intel",)), ("qualcomm", ("qualcomm", "adreno", "snapdragon")),
                 ("apple", ("apple",)))


def _vendor_of(name: str, backend: str = "") -> str:
    """The card's maker, from its llama.cpp backend ("CUDA0") or its name; "" when neither says."""
    kind = re.sub(r"\d+$", "", (backend or "").strip()).lower()
    if kind in _BACKEND_VENDORS:
        return _BACKEND_VENDORS[kind]
    low = (name or "").lower()
    return next((v for v, words in _NAME_VENDORS if any(w in low for w in words)), "")


def _is_discrete_gpu_name(name: str) -> bool:
    """True for discrete GPUs with dedicated VRAM (not iGPU/APU/unified)."""
    low = (name or "").lower()
    if any(k in low for k in ("geforce", "quadro", "tesla", "rtx ", "gtx ", "nvidia")):
        return True
    if any(k in low for k in ("radeon pro", "instinct", "firepro")):
        return True
    if "arc" in low and "intel" in low:
        return True
    if re.search(r"\brx\s*\d", low):
        return True
    if re.search(r"\brx\s*\d{3,4}\b", low):
        return True
    return False


def _is_integrated_gpu_name(name: str, vendor: str = "") -> bool:
    """True when the adapter shares system RAM (Intel iGPU, AMD APU, Apple Silicon)."""
    if _is_discrete_gpu_name(name):
        return False
    low = (name or "").lower()
    v = (vendor or "").lower()
    if v == "apple" or any(k in low for k in ("apple m1", "apple m2", "apple m3", "apple m4")):
        return True
    if sys.platform == "darwin" and any(k in low for k in ("apple", "m1", "m2", "m3", "m4")):
        return True
    if v == "intel" or any(k in low for k in ("intel", "iris", "uhd")):
        return "arc" not in low
    if v == "amd" or any(k in low for k in ("amd", "radeon", "ati", "vega")):
        return not _is_discrete_gpu_name(name)
    if v == "qualcomm" or any(k in low for k in ("qualcomm", "adreno", "snapdragon", "hexagon")):
        return True
    return False


def integrated_gpu_label(name: str = "", vendor: str = "") -> str:
    """Short label for status bars — Intel iGPU, AMD APU, Apple unified memory, etc."""
    low = (name or "").lower()
    v = (vendor or "").lower()
    if v == "apple" or sys.platform == "darwin" and "apple" in low:
        return "Apple unified memory"
    if "iris" in low:
        return "Intel Iris Xe"
    if "uhd" in low:
        return "Intel UHD"
    if v == "intel" or "intel" in low:
        return "Intel iGPU"
    if any(k in low for k in ("apu", "vega", "raphael", "phoenix", "renoir", "cezanne")):
        return "AMD APU"
    if v == "amd" or "radeon" in low:
        return "AMD integrated GPU"
    if "adreno" in low or v == "qualcomm":
        if "snapdragon" in low or "x elite" in low or "x1" in low:
            return "Snapdragon Adreno"
        return "Qualcomm Adreno"
    if "snapdragon" in low:
        return "Snapdragon"
    return "integrated GPU"


def runtime_effective_gpu_layers(snapshot: Optional[dict] = None) -> int:
    """Layers actually driving inference (0 = CPU-only), not requested settings."""
    try:
        snap: dict = {}
        if snapshot is not None:
            snap = dict(snapshot or {})
        else:
            from eli.cognition import gguf_inference as gi
            snap = dict(
                gi.get_live_runtime_override()
                or getattr(gi, "_live_runtime_params", None)
                or {}
            )
        eff = snap.get("effective") if isinstance(snap.get("effective"), dict) else {}
        if "n_gpu_layers" in eff:
            return max(0, int(eff.get("n_gpu_layers") or 0))
        if str(snap.get("load_mode") or "").upper() == "CPU":
            return 0
        if snap.get("on_gpu") is False:
            return 0
        if snap.get("gpu_offload_supported") is False:
            return 0
        return max(0, int(snap.get("n_gpu_layers") or 0))
    except Exception:
        return 0


def runtime_cpu_only(snapshot: Optional[dict] = None) -> bool:
    """True when the loaded model is running with zero GPU layers."""
    return runtime_effective_gpu_layers(snapshot) <= 0


def format_gpu_layers_status(
    active_layers: int,
    *,
    fitted_layers: int = 0,
    gpu_integrated: bool = False,
    gpu_name: str = "",
    gpu_vendor: str = "",
) -> str:
    """Human-readable GPU layer count for status bars and hardware panels.

    Reports only layers that are ACTIVE. Fitted-but-unavailable counts belong in
    the hardware panel / startup dialog — not the live status bar (showing "6 fit,
    CPU active" while gpu=0 misled Iris Xe users into thinking offload was on).
    """
    active = max(0, int(active_layers or 0))
    igpu_label = integrated_gpu_label(gpu_name, gpu_vendor) if gpu_integrated else ""

    if active <= 0:
        if gpu_integrated:
            return f"0 ({igpu_label or 'integrated'}, CPU only)"
        return "0 (CPU only)"
    if gpu_integrated:
        label = igpu_label or "integrated GPU"
        return f"{active} ({label})"
    return str(active)


def _pci_addr_from_drm_device(dev: Path) -> str:
    try:
        return dev.resolve().name
    except Exception:
        return ""


@functools.lru_cache(maxsize=None)
def _lspci_name_for_pci_addr(addr: str) -> str:
    if not addr or not shutil.which("lspci"):
        return ""
    try:
        proc = subprocess.run(
            ["lspci", "-s", addr, "-nn"],
            capture_output=True, text=True, timeout=5,
            env=_external_tool_env(),
        )
        if proc.returncode != 0:
            return ""
        line = (proc.stdout or "").strip().splitlines()[0]
        if ":" in line:
            return line.split(":", 2)[-1].strip()
    except Exception:
        log.debug("lspci lookup failed for %s", addr, exc_info=True)
    return ""


def _linux_intel_display_adapters() -> List[tuple[str, bool]]:
    """Return (human_name, is_discrete_arc) for each Intel DRM adapter."""
    out: List[tuple[str, bool]] = []
    for vendor, dev in _linux_drm_gpus():
        if vendor != "intel":
            continue
        is_arc = _intel_pci_device_is_discrete_arc(dev)
        name = _lspci_name_for_pci_addr(_pci_addr_from_drm_device(dev))
        out.append((name or ("Intel Arc" if is_arc else "Intel integrated graphics (Iris Xe / UHD)"), is_arc))
    return out


def _linux_soc_display_adapters() -> List[tuple[str, str]]:
    """(name, vendor) for each system-on-chip GPU on Linux: Qualcomm Adreno (Snapdragon), Apple
    (Asahi Linux). Unified memory, like an integrated GPU."""
    out: List[tuple[str, str]] = []
    for vendor, dev in _linux_drm_gpus():
        if vendor not in ("qualcomm", "apple"):
            continue
        name = _lspci_name_for_pci_addr(_pci_addr_from_drm_device(dev))
        if not name:
            try:      # device-tree name, e.g. "qcom,adreno-43050c01"
                name = (dev / "of_node" / "compatible").read_bytes().split(b"\0")[0].decode("ascii", "replace")
            except OSError:
                name = ""
        out.append((name or ("Qualcomm Adreno (Snapdragon)" if vendor == "qualcomm" else "Apple GPU"), vendor))
    return out


def _apply_integrated_gpu_profile(hw: HardwareProfile, name: str, vendor: str) -> None:
    """Mark a shared-memory GPU (Intel iGPU, AMD APU, Apple unified memory)."""
    hw.has_gpu = True
    hw.gpu_vendor = vendor or "unknown"
    hw.gpu_integrated = True
    hw.gpu_name = name
    hw.vulkan_available = _vulkan_loader_present()
    free_mb, total_mb = _estimate_integrated_vram_mb(hw.ram_gb, hw.available_ram_gb)
    hw.free_vram_mb = free_mb
    hw.total_vram_mb = total_mb
    hw.vram_gb = hw.free_vram_mb / 1024.0


def _apply_intel_integrated_profile(hw: HardwareProfile, name: str) -> None:
    _apply_integrated_gpu_profile(hw, name, "intel")


def _llama_gpu_offload_available() -> bool:
    try:
        import llama_cpp
        return bool(llama_cpp.llama_supports_gpu_offload())
    except Exception:
        return False


def effective_use_gpu_layers(hw: HardwareProfile, *, force_cpu: bool = False) -> bool:
    """True when GPU layer offload should be planned (backend active, not CPU-forced).

    iGPU machines without a GPU pack report has_gpu=True but llama-cpp is CPU-only —
    sizing ctx/layers from shared-memory VRAM then misleads the startup dialog (e.g.
    ctx=3996 gpu_layers=2 on Iris Xe while the loader runs CPU-only at ctx=8092).
    """
    if force_cpu:
        return False
    if (os.environ.get("ELI_FORCE_GPU_LAYERS") or "").strip() == "0":
        return False
    try:
        from eli.core.runtime_settings import load_settings
        if str((load_settings() or {}).get("compute_mode") or "auto").lower() == "cpu":
            return False
    except Exception:
        log.debug("suppressed exception", exc_info=True)
    return bool(hw.has_gpu and (hw.free_vram_mb > 0 or hw.gpu_detection_uncertain)
                and _llama_gpu_offload_available())


def cpu_ram_budget_mb(available_ram_gb: float, *, fraction: float | None = None) -> int:
    """RAM budget (MB) for cpu_ram_fit — same shape as free VRAM for smart_fit_config."""
    frac = ram_budget_fraction() if fraction is None else float(fraction)
    return int(max(0.0, float(available_ram_gb)) * 1024.0 * frac)


def cpu_ram_fit_config(
    model_size_gb: float,
    available_ram_gb: float,
    *,
    user_ctx: int,
    user_batch: int,
    model_path: Optional[str] = None,
    kv_quantized: bool = False,
    min_batch: int = 128,
) -> tuple[int, int]:
    """Fit n_ctx and batch for CPU-only inference from live RAM.

    Uses the same smart_fit_config arithmetic as GPU systems so recommendations
    match what the loader's RAM smart-fit produces — one calculation, not two.
    """
    budget = cpu_ram_budget_mb(available_ram_gb)
    ctx, _layers, batch = smart_fit_config(
        model_size_gb,
        budget,
        user_ctx=max(1, int(user_ctx)),
        user_batch=max(min_batch, int(user_batch)),
        reserve_mb=0,                    # the budget is already a fraction of the free RAM
        kv_quantized=kv_quantized,
        model_path=model_path,
        min_batch=min_batch,
        min_gpu_fraction=0.0,
    )
    return int(ctx), max(min_batch, int(batch))


_DETECT_HW_CACHE: Optional[tuple[float, HardwareProfile]] = None
_DETECT_HW_CACHE_TTL_S = 30.0


def detect_hardware(*, force: bool = False) -> HardwareProfile:
    """Probe the host for CPU/RAM/free-VRAM. Reads FREE VRAM from nvidia-smi.

    Results are cached briefly so repeated startup probes (startup dialog,
    smart-fit, status bar) do not re-run nvidia-smi/lspci/sysfs or spam logs.
    Pass ``force=True`` to bypass the cache.
    """
    global _DETECT_HW_CACHE
    now = time.monotonic()
    if not force and _DETECT_HW_CACHE is not None:
        ts, cached = _DETECT_HW_CACHE
        if now - ts < _DETECT_HW_CACHE_TTL_S:
            return copy.deepcopy(cached)
    hw = _detect_hardware_impl()
    _DETECT_HW_CACHE = (now, copy.deepcopy(hw))
    return hw


def _service_of(pid: int) -> str:
    """The system service a Linux process runs under ("ollama.service"), else "". Only system
    services: a desktop app sits under the login session, which is nothing to stop."""
    try:
        for line in Path(f"/proc/{int(pid)}/cgroup").read_text(encoding="utf-8").splitlines():
            parts = line.split(":", 2)[-1].strip("/").split("/")
            if len(parts) >= 2 and parts[0] == "system.slice" and parts[1].endswith(".service"):
                return parts[1]
    except Exception:
        log.debug("service of pid %s unreadable", pid, exc_info=True)
    return ""


def vram_holders(*, exclude_pid: Optional[int] = None) -> List[Dict[str, Any]]:
    """Processes holding GPU memory, largest first: {pid, name, mb, service}.

    NVIDIA on any OS through nvidia-smi's compute list; AMD on Linux through the kernel's
    per-process ROCm counters (/sys/class/kfd/kfd/proc/<pid>/vram_*). Not covered: Intel and
    Apple GPUs and AMD on Windows. mb is None where the driver does not say (Windows display
    driver mode). This process is left out.
    """
    own = os.getpid() if exclude_pid is None else int(exclude_pid)
    found: Dict[int, Dict[str, Any]] = {}
    smi = nvidia_smi_path()
    if smi:
        try:
            proc = subprocess.run(
                [smi, "--query-compute-apps=pid,process_name,used_memory", "--format=csv,noheader,nounits"],
                timeout=6, capture_output=True, text=True, check=False, env=_external_tool_env())
            for line in (proc.stdout or "").splitlines() if proc.returncode == 0 else []:
                parts = [x.strip() for x in line.split(",")]
                if len(parts) < 3 or not parts[0].isdigit():
                    continue
                cmd = ",".join(parts[1:-1]).strip()
                try:
                    mb: Optional[float] = float(parts[-1])
                except ValueError:
                    mb = None
                pid = int(parts[0])
                entry = found.setdefault(pid, {"pid": pid, "name": Path(cmd.split(" ")[0]).name or cmd, "mb": None})
                if mb is not None:
                    entry["mb"] = (entry["mb"] or 0.0) + mb
        except Exception:
            log.debug("nvidia-smi process list unavailable", exc_info=True)
    kfd = Path("/sys/class/kfd/kfd/proc")
    if kfd.is_dir():
        for pdir in kfd.iterdir():
            try:
                pid = int(pdir.name)
                used = sum(int(f.read_text().strip() or 0) for f in pdir.glob("vram_*"))
                name = Path(f"/proc/{pid}/comm").read_text(encoding="utf-8").strip()
            except Exception:
                continue
            if used > 0:
                found.setdefault(pid, {"pid": pid, "name": name, "mb": used / 1_048_576})
    holders = [h for pid, h in found.items() if pid != own]
    for h in holders:
        h["service"] = _service_of(h["pid"])
    return sorted(holders, key=lambda h: -(h["mb"] or 0.0))


def describe_vram_holders(holders: List[Dict[str, Any]], *, total_mb: Optional[int] = None) -> str:
    """'llama-server (ollama.service, pid 1172557) 5146 MB, ...' — holders of at least a
    hundredth of the card when its size is known, so a file manager's few MB is not listed."""
    shown = []
    for h in holders:
        mb = h.get("mb")
        if total_mb and mb is not None and mb < total_mb / 100:
            continue
        where = ", ".join(x for x in (h.get("service") or "", f"pid {h['pid']}") if x)
        shown.append(f"{h['name']} ({where})" + (f" {mb:.0f} MB" if mb is not None else ""))
    return ", ".join(shown)


def _nvidia_cards(timeout: float = 6.0) -> Optional[List[Dict[str, Any]]]:
    """Every NVIDIA card from nvidia-smi (any OS), or None when the tool is absent or fails. The first
    call after boot can take seconds while the driver initialises, hence detection's longer timeout."""
    smi = nvidia_smi_path()
    if not smi:
        return None
    try:
        proc = subprocess.run(
            [smi, "--query-gpu=name,memory.total,memory.used,memory.free,"
                  "utilization.gpu,temperature.gpu,power.draw,power.limit,driver_version",
             "--format=csv,noheader,nounits"],
            timeout=timeout, capture_output=True, text=True, check=False, env=_external_tool_env())
    except Exception:
        log.debug("nvidia-smi query failed", exc_info=True)
        return None
    if proc.returncode != 0 or not (proc.stdout or "").strip():
        return None

    def _num(row, i):
        try:
            return float(row[i]) if i < len(row) and row[i] not in ("", "[N/A]", "N/A") else None
        except ValueError:
            return None

    cards = []
    for line in proc.stdout.strip().splitlines():
        row = [c.strip() for c in line.split(",")]
        if _num(row, 1) is None:     # a message, not a card
            continue
        cards.append({"index": len(cards), "name": row[0] or "NVIDIA GPU", "vendor": "nvidia",
                      "total_mb": _num(row, 1), "used_mb": _num(row, 2), "free_mb": _num(row, 3),
                      "util_pct": _num(row, 4), "temp_c": _num(row, 5), "power_w": _num(row, 6),
                      "power_limit_w": _num(row, 7), "integrated": False,
                      "driver": row[8] if len(row) > 8 and row[8] else None})
    return cards or None


# An AMD APU's amdgpu "VRAM" is the firmware carve-out from system memory (none, or a few dozen MB, when
# the firmware leaves it to the driver); a discrete card has its own. Firmware can also set a carve-out
# of 512 MB or more, which this cannot tell from a small discrete card; llama.cpp's own device type
# decides at load (eli/core/load_plan.py).
_AMD_APU_CARVEOUT_MAX_BYTES = 64 * 1_048_576


def _amd_cards() -> Optional[List[Dict[str, Any]]]:
    """Every AMD GPU, live: the amdgpu kernel driver's own counters on Linux (no ROCm needed; APUs are
    included and marked integrated, with no memory of their own), else rocm-smi. None when neither
    can be read; a card whose counters cannot be read is left to detection's "a GPU is here but
    could not be characterised"."""
    cards: List[Dict[str, Any]] = []
    if sys.platform.startswith("linux"):
        for vendor, dev in _linux_drm_gpus():
            if vendor != "amd":
                continue

            def _read(name):
                try:
                    return int((dev / name).read_text().strip())
                except (OSError, ValueError):
                    return None

            total, used = _read("mem_info_vram_total"), _read("mem_info_vram_used")
            if total is None:        # unreadable (permissions, an old driver): not characterised here
                continue
            integrated = total <= _AMD_APU_CARVEOUT_MAX_BYTES
            card: Dict[str, Any] = {
                "index": len(cards),
                "name": _lspci_name_for_pci_addr(_pci_addr_from_drm_device(dev))
                or ("AMD integrated graphics (APU)" if integrated else "AMD GPU"),
                "vendor": "amd", "integrated": integrated,
                "total_mb": None if integrated else total / 1_048_576,
                "used_mb": None if integrated or used is None else used / 1_048_576,
                "free_mb": None if integrated or used is None else max(0, total - used) / 1_048_576,
                "util_pct": _read("gpu_busy_percent"), "temp_c": None, "power_w": None, "power_limit_w": None}
            for hwmon in sorted(dev.glob("hwmon/hwmon*")):
                def _hw(name, scale):
                    try:
                        return int((hwmon / name).read_text().strip()) / scale
                    except (OSError, ValueError):
                        return None
                card["temp_c"] = _hw("temp1_input", 1000.0)
                card["power_w"] = _hw("power1_average", 1_000_000.0) or _hw("power1_input", 1_000_000.0)
                card["power_limit_w"] = _hw("power1_cap", 1_000_000.0)
            cards.append(card)
        if cards:
            return cards
    if not shutil.which("rocm-smi"):
        return None
    try:
        proc = subprocess.run(["rocm-smi", "--showmeminfo", "vram", "--json"], timeout=6,
                              capture_output=True, text=True, check=False, env=_external_tool_env())
        data = json.loads(proc.stdout or "{}") if proc.returncode == 0 else {}
    except Exception:
        log.debug("rocm-smi query failed", exc_info=True)
        return None
    for card_name, info in sorted((data or {}).items()):
        if not isinstance(info, dict):
            continue
        total = used = None
        for k, v in info.items():
            kl = str(k).lower()
            try:
                if all(n in kl for n in ("vram", "total", "memory")) and "used" not in kl:
                    total = int(v)
                elif all(n in kl for n in ("vram", "used", "memory")):
                    used = int(v)
            except (TypeError, ValueError):
                continue
        if total:
            cards.append({"index": len(cards), "name": f"AMD GPU ({card_name})", "vendor": "amd",
                          "total_mb": total / 1_048_576,
                          "used_mb": None if used is None else used / 1_048_576,
                          "free_mb": None if used is None else max(0, total - used) / 1_048_576,
                          "util_pct": None, "temp_c": None, "power_w": None, "power_limit_w": None,
                          "integrated": False})
    return cards or None


def _llama_cpp_cards() -> Optional[List[Dict[str, Any]]]:
    """The GPUs llama.cpp itself sees, with their free memory, on whatever backend it was built for
    (CUDA, Vulkan, Metal, HIP, SYCL) and on any OS. Only when llama.cpp is already loaded in this
    process: importing it here would load the bundled runtime before a GPU pack could."""
    if "llama_cpp" not in sys.modules:
        return None
    try:
        from eli.core.load_plan import devices
        found = devices()
    except Exception:
        log.debug("llama.cpp device list unavailable", exc_info=True)
        return None
    return [{"index": d.index, "name": d.description or d.name, "vendor": _vendor_of(d.description, d.name),
             "total_mb": d.total_mb,
             "used_mb": max(0, d.total_mb - d.free_mb), "free_mb": d.free_mb, "util_pct": None,
             "temp_c": None, "power_w": None, "power_limit_w": None, "integrated": d.integrated,
             "backend": d.name} for d in found] or None


def _cards_in_use(cards: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The cards llama.cpp loads onto: the discrete ones, or the integrated ones when there is no
    discrete one."""
    return [c for c in cards if not c.get("integrated")] or [c for c in cards if c.get("integrated")]


def _card_names(cards: List[Dict[str, Any]]) -> str:
    names = [str(c.get("name") or "GPU") for c in cards]
    if len(set(names)) == 1:
        return names[0] + (f" ×{len(names)}" if len(names) > 1 else "")
    return " + ".join(names)


def _apply_cards(hw: HardwareProfile, cards: List[Dict[str, Any]]) -> bool:
    """Record every card on the profile and size it from the cards a model would use. False when
    there are none."""
    use = _cards_in_use(cards)
    if not use:
        return False
    first = use[0]
    if first.get("integrated"):
        _apply_integrated_gpu_profile(hw, str(first.get("name") or "GPU"), str(first.get("vendor") or "unknown"))
        if first.get("free_mb") is not None:      # the OS's own figure for its share of system memory
            hw.free_vram_mb = int(first["free_mb"])
            hw.total_vram_mb = int(first.get("total_mb") or hw.free_vram_mb)
            hw.vram_gb = hw.free_vram_mb / 1024.0
    else:
        hw.has_gpu = True
        hw.gpu_vendor = str(first.get("vendor") or "unknown")
        hw.gpu_integrated = False
        hw.gpu_name = _card_names(use)
        hw.total_vram_mb = int(sum(float(c.get("total_mb") or 0) for c in use))
        # no free figure (Windows before 10, Arc on Linux): total, flagged uncertain until llama.cpp reads it
        hw.free_vram_mb = int(sum(float(c["free_mb"]) if c.get("free_mb") is not None
                                  else float(c.get("total_mb") or 0) for c in use))
        if any(c.get("free_mb") is None for c in use):
            hw.gpu_detection_uncertain = True
        hw.vram_gb = hw.free_vram_mb / 1024.0
    hw.gpus = [{"index": i, "name": str(c.get("name") or "GPU"), "vendor": str(c.get("vendor") or "unknown"),
                "free_mb": None if c.get("free_mb") is None else int(c["free_mb"]),
                "total_mb": None if c.get("total_mb") is None else int(c["total_mb"]),
                "integrated": bool(c.get("integrated"))} for i, c in enumerate(cards)]
    return True


def get_live_gpu_telemetry() -> Dict[str, Any]:
    """The one place every caller asks "what are my GPUs doing right now": names, memory and, where
    the vendor's tool or driver says, use, temperature and power — for every card, every vendor and
    every OS. Eight call sites used to run nvidia-smi themselves and read its first line.

    Sources, per vendor: nvidia-smi (NVIDIA, any OS); the amdgpu kernel driver's counters (AMD on
    Linux, no ROCm needed), else rocm-smi; and for every other GPU — Intel, Apple, AMD on Windows,
    anything llama.cpp drives through Vulkan, Metal, HIP or SYCL — llama.cpp's own device list
    when it is loaded, else the adapters detect_hardware() found (memory only, estimated where the
    OS gives no free figure).

    Always returns a dict (never raises): {ok, name, vendor, estimated, total_mb, free_mb, used_mb,
    util_pct, temp_c, power_w, power_limit_w, driver, devices, live_probe_failed}. Several GPUs:
    memory and power are their sums, use and temperature the busiest card's, `devices` each card.
    What no source supplies is None, not made up. live_probe_failed: the vendor's live tool exists
    but its call failed, so the figures are detect_hardware()'s."""
    out: Dict[str, Any] = {
        "ok": False, "name": "", "vendor": "", "estimated": False,
        "total_mb": None, "free_mb": None, "used_mb": None,
        "util_pct": None, "temp_c": None, "power_w": None, "power_limit_w": None,
        "driver": None, "live_probe_failed": False, "devices": [],
    }
    try:
        hw = detect_hardware()
    except Exception:
        hw = None
    if hw is None or not hw.has_gpu:
        return out
    vendor = (hw.gpu_vendor or "").lower()
    out.update({"ok": True, "name": hw.gpu_name, "vendor": vendor,
                "estimated": bool(hw.gpu_detection_uncertain),
                "total_mb": int(hw.total_vram_mb) if hw.total_vram_mb else None,
                "free_mb": int(hw.free_vram_mb) if hw.free_vram_mb else None,
                "devices": [dict(g) for g in (hw.gpus or [])]})

    cards = None
    if vendor == "nvidia":
        cards = _nvidia_cards()
        out["live_probe_failed"] = cards is None and nvidia_smi_path() is not None
    elif vendor == "amd" and sys.platform.startswith("linux") and not hw.gpu_integrated:
        cards = _cards_in_use(_amd_cards() or []) or None
        out["live_probe_failed"] = cards is None and shutil.which("rocm-smi") is not None
    if not cards and os.name == "nt":
        cards = _cards_in_use(_windows_dxgi_adapters() or []) or None
    if not cards and sys.platform == "darwin":
        cards = _macos_accelerators() or None
    llama = _llama_cpp_cards()
    if not cards:
        cards = llama
    elif llama and len(llama) == len(cards):
        # what a vendor tool leaves out (Apple's total, an old Windows' free) llama.cpp knows
        for card, seen in zip(cards, llama):
            for key in ("total_mb", "free_mb", "used_mb"):
                if card.get(key) is None:
                    card[key] = seen.get(key)
    if not cards:
        return out

    def _sum(key):
        vals = [float(c[key]) for c in cards if c.get(key) is not None]
        return sum(vals) if vals else None

    def _max(key):
        vals = [float(c[key]) for c in cards if c.get(key) is not None]
        return max(vals) if vals else None

    out.update({
        "name": _card_names(cards),
        "estimated": False,
        "total_mb": int(_sum("total_mb")) if _sum("total_mb") is not None else out["total_mb"],
        "used_mb": int(_sum("used_mb")) if _sum("used_mb") is not None else None,
        "free_mb": int(_sum("free_mb")) if _sum("free_mb") is not None else out["free_mb"],
        "util_pct": int(_max("util_pct")) if _max("util_pct") is not None else None,
        "temp_c": int(_max("temp_c")) if _max("temp_c") is not None else None,
        "power_w": _sum("power_w"),
        "power_limit_w": _sum("power_limit_w"),
        "driver": next((c.get("driver") for c in cards if c.get("driver")), None),
        "devices": [{k: (int(v) if k.endswith(("_mb", "_pct", "_c")) and v is not None else v)
                     for k, v in c.items() if k != "driver"} for c in cards],
    })
    return out


def gpu_label(telemetry: Dict[str, Any]) -> str:
    """The GPU name for a status line, marked when it is detect_hardware()'s estimate rather than a
    live reading."""
    name = str(telemetry.get("name") or "")
    return name + (" (estimated)" if telemetry.get("estimated") or telemetry.get("live_probe_failed") else "")


def describe_gpus(telemetry: Optional[Dict[str, Any]] = None) -> str:
    """Each GPU's name and memory in one line, for evidence and replies (get_live_gpu_telemetry);
    "unavailable" when no GPU is known."""
    t = telemetry if telemetry is not None else get_live_gpu_telemetry()
    if not t.get("ok"):
        return "unavailable"
    note = " (estimated)" if t.get("estimated") or t.get("live_probe_failed") else ""
    driver = f", driver {t['driver']}" if t.get("driver") else ""
    devices = list(t.get("devices") or [])
    if len(devices) > 1:
        parts = [f"GPU {d.get('index', i)} {d.get('name', '')}: {d.get('total_mb')} MiB total, "
                 f"{d.get('free_mb')} MiB free" for i, d in enumerate(devices)]
        return f"{len(devices)} GPUs{note}: " + "; ".join(parts) + driver
    used = f", {t['used_mb']} MiB used" if t.get("used_mb") is not None else ""
    free = f", {t['free_mb']} MiB free" if t.get("free_mb") is not None else ""
    return f"{t.get('name') or 'GPU'}{note}: {t.get('total_mb')} MiB total{used}{free}{driver}"


def gpu_offload_unavailable_message(
    *,
    gpu_vendor: str = "",
    gpu_integrated: bool = False,
    vulkan_available: bool = False,
) -> str:
    """User-facing hint when llama.cpp reports no active GPU backend."""
    vendor = (gpu_vendor or "").lower()
    if gpu_integrated:
        kind = integrated_gpu_label("", vendor)
        if vendor == "qualcomm":
            return (
                f"⚠️ GPU offload unavailable; running CPU-only. "
                f"{kind} detected — install the Vulkan GPU pack "
                f"(ELI --install-gpu-pack --vulkan) and keep batch ≤ 32."
            )
        if vendor in ("intel", "amd", "apple"):
            hint = (
                "install the Vulkan GPU pack (ELI --install-gpu-pack --vulkan)"
                if vulkan_available or vendor != "apple"
                else "install GPU drivers / vulkan-icd, then the Vulkan GPU pack"
            )
            return (
                f"⚠️ GPU offload unavailable; running CPU-only. "
                f"{kind} budget is still used for layer sizing — {hint} to offload."
            )
    if vendor == "nvidia":
        return (
            "⚠️ GPU offload unavailable; running CPU-only. "
            "Check NVIDIA driver/CUDA runtime or reinstall the GPU pack "
            "(ELI --install-gpu-pack --force)."
        )
    if vendor == "amd":
        return (
            "⚠️ GPU offload unavailable; running CPU-only. "
            "Install AMD GPU drivers or the Vulkan GPU pack "
            "(ELI --install-gpu-pack --vulkan)."
        )
    return (
        "⚠️ GPU offload unavailable; running CPU-only. "
        "Install the GPU pack for your vendor (ELI --install-gpu-pack)."
    )


def _detect_hardware_impl() -> HardwareProfile:
    """Uncached hardware probe — use detect_hardware() instead."""
    hw = HardwareProfile()
    hw.cpu_threads = multiprocessing.cpu_count()
    hw.cpu_cores = physical_performance_cores()

    # RAM total + available — binary GiB, matching free_vram_mb/total_vram_mb below and
    # every model-size figure (mem_units.py): the psutil path used to divide by decimal
    # 1e9 while this same function's /proc/meminfo fallback already divided by binary
    # 1_048_576, so which branch ran changed the number for identical physical RAM.
    try:
        import psutil
        vm = psutil.virtual_memory()
        hw.ram_gb = mem_units.bytes_to_gib(vm.total)
        hw.available_ram_gb = mem_units.bytes_to_gib(vm.available)
    except Exception:
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        hw.ram_gb = int(line.split()[1]) / 1_048_576
                    elif line.startswith("MemAvailable:"):
                        hw.available_ram_gb = int(line.split()[1]) / 1_048_576
        except Exception:
            log.debug("suppressed exception", exc_info=True)

    # Reserve room for ELI's own always-on support models — the STT model and the
    # memory/RAG embedder — both load once at startup and stay resident all session,
    # independent of whichever chat model the user picks. A capacity check that runs
    # before them (the startup dialog's tuning pass fires before the engine and its
    # embedder exist) would otherwise size the chat model, and an MoE model's expert
    # split, off RAM that's about to be spoken for. If they've already loaded by the
    # time this runs, `available` above already reflects it and this double-reserves
    # a few hundred MB — the safe direction of error (conservative, never overcommits).
    try:
        from eli.perception.local_whisper_stt import resident_footprint_gib as _whisper_gib
        hw.available_ram_gb = max(0.0, hw.available_ram_gb - _whisper_gib())
    except Exception:
        log.debug("suppressed exception", exc_info=True)
    try:
        from eli.memory.vector_store import embedder_footprint_gib as _embedder_gib
        hw.available_ram_gb = max(0.0, hw.available_ram_gb - _embedder_gib())
    except Exception:
        log.debug("suppressed exception", exc_info=True)

    # Every GPU, any vendor, any OS. Each source is read by one function that get_live_gpu_telemetry()
    # shares, and a model uses the discrete cards, or the integrated ones when there is no discrete
    # one (llama.cpp's rule). Free memory, not total: the desktop, a browser or another model's
    # server already hold some of it.
    _apply_cards(hw, _nvidia_cards(timeout=15) or [])

    # nvidia-smi missing or broken but the driver loaded: name from /proc, memory left to llama.cpp
    if not hw.has_gpu and sys.platform.startswith("linux") and _nvidia_driver_loaded():
        _model = _nvidia_gpu_model_from_proc()
        hw.total_vram_mb = 0
        hw.free_vram_mb = 0
        hw.gpu_name = _model or "NVIDIA GPU"
        hw.vram_gb = hw.free_vram_mb / 1024.0
        hw.has_gpu = True
        hw.gpu_vendor = "nvidia"
        hw.gpu_detection_uncertain = True

    # Windows, any vendor: DXGI lists every adapter with its memory and the budget Windows gives this
    # process on it.
    if not hw.has_gpu and os.name == "nt":
        _apply_cards(hw, _windows_dxgi_adapters() or [])

    # macOS: Apple Silicon (unified memory) and Intel Macs with an AMD card.
    if not hw.has_gpu and sys.platform == "darwin":
        _mac = []
        for _name, _mb in _macos_gpus():
            _vendor = _vendor_of(_name) or "apple"
            _integrated = _vendor == "apple" or _is_integrated_gpu_name(_name, _vendor)
            _mac.append({"name": _name, "vendor": _vendor, "integrated": _integrated,
                         "total_mb": None if _integrated else (_mb or None), "free_mb": None})
        if _apply_cards(hw, _mac):
            log.info("[HW] GPU: %s (%d MB usable)", hw.gpu_name, hw.free_vram_mb)

    # AMD on Linux: the amdgpu driver's counters (no ROCm needed; what the Vulkan pack targets), else
    # rocm-smi. APUs are kept for the integrated step below.
    _amd = None if hw.has_gpu else (_amd_cards() or [])
    if _amd:
        _apply_cards(hw, [c for c in _amd if not c["integrated"]])

    # Intel on Linux: Arc before Iris Xe / UHD; no memory counter, so llama.cpp measures it
    if not hw.has_gpu:
        _intel = [{"name": _name, "vendor": "intel", "integrated": not _is_arc, "total_mb": None,
                   "free_mb": None} for _name, _is_arc in _linux_intel_display_adapters()]
        if _apply_cards(hw, _intel):
            log.info("[HW] Intel GPU: %s (~%d MB, Vulkan=%s)", hw.gpu_name, hw.free_vram_mb, hw.vulkan_available)

    if not hw.has_gpu and _amd and _apply_cards(hw, [c for c in _amd if c["integrated"]]):
        log.info("[HW] AMD iGPU/APU detected: %s (~%d MB shared-memory budget, Vulkan=%s)",
                 hw.gpu_name, hw.free_vram_mb, hw.vulkan_available)

    # System-on-chip GPUs on Linux (Qualcomm Adreno, Apple under Asahi Linux): unified memory.
    if not hw.has_gpu and _apply_cards(hw, [{"name": n, "vendor": v, "integrated": True}
                                            for n, v in _linux_soc_display_adapters()]):
        log.info("[HW] %s GPU: %s (~%d MB shared-memory budget, Vulkan=%s)",
                 hw.gpu_vendor, hw.gpu_name, hw.free_vram_mb, hw.vulkan_available)

    # Last resort before concluding "no GPU": a real GPU PCI device may be in /sys/class/drm that
    # every vendor probe failed to characterise (unrecognised subvendor, a driver not exposing the
    # sysfs files, permissions).
    if not hw.has_gpu and _linux_drm_gpus():
        hw.gpu_detection_uncertain = True

    if not hw.has_gpu and not hw.gpu_name:
        hw.gpu_name = "CPU detection uncertain" if hw.gpu_detection_uncertain else "CPU only"
    if hw.has_gpu and not hw.gpus:
        hw.gpus.append({"index": 0, "name": hw.gpu_name, "vendor": hw.gpu_vendor or "unknown",
                        "free_mb": int(hw.free_vram_mb), "total_mb": int(hw.total_vram_mb),
                        "integrated": bool(hw.gpu_integrated)})

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
    from eli.cognition.model_load_diagnostics import not_a_chat_model
    for f in sorted(models_dir.rglob("*.gguf")):
        # a vision projector or a draft head is not a model to talk to either (by its metadata)
        if not include_embedders and (_is_embedder_path(f) or not_a_chat_model(f)):
            continue
        size = f.stat().st_size
        out.append({
            "name": f.name,
            "path": str(f.resolve()),
            "size_bytes": size,
            "size_gb": mem_units.bytes_to_gib(size),
        })
    return out


def _gpu_layers_for_model(size_gb: float, free_vram_mb: int, n_ctx: int,
                          kv_quantized: bool = False,
                          model_path: Optional[str] = None) -> int:
    """Compute n_gpu_layers from FREE VRAM minus KV-cache and CUDA overhead.

    When kv_quantized=True, the KV cache is the quantized type ELI loads (q8_0, about half of
    fp16), letting a longer n_ctx fit on the same GPU.

    Returns ALL_GPU_LAYERS (-1, llama.cpp's every layer) if the entire model fits (it used to return
    99, which is not above every
    real-world 7–70B model's layer count and avoids the 9999 sentinel that
    _eli_requested_runtime_from_kwargs() treats as an uncalibrated user value).
    Returns 0 if no GPU or insufficient VRAM, or a partial layer count otherwise.
    """
    if free_vram_mb <= 0:
        return 0
    cost = model_cost(model_path, kv_quantized=kv_quantized)
    if cost is not None:
        blocks = cost.weights.blocks
        fixed = _CUDA_OVERHEAD_MB + _compute_graph_reserve_mb(n_ctx)
        n = 0
        while n <= blocks and (cost.gpu_weights_mb(n + 1) + cost.kv_mb(n_ctx, gpu_layers=min(n + 1, blocks))
                               + fixed) <= free_vram_mb:
            n += 1
        return ALL_GPU_LAYERS if n > blocks else n
    total_layers = layers_for_model(model_path, size_gb)
    kv_mb = _kv_cache_mb(n_ctx, total_layers, quant=kv_quantized)
    # Reserve the decode-time compute/graph buffer too, not just model+KV+overhead.
    # Without this, full offload (every layer) gets chosen at max ctx, loads fine, then
    # OOMs on the first decode when the compute buffer is allocated.
    compute_mb = _compute_graph_reserve_mb(n_ctx)
    available_for_model = free_vram_mb - kv_mb - _CUDA_OVERHEAD_MB - compute_mb
    mb_per_layer = (size_gb * 1024) / max(1, total_layers + 2)
    if available_for_model <= 0 or mb_per_layer <= 0:
        return 0
    n = int(available_for_model / mb_per_layer)
    if n >= total_layers:
        return ALL_GPU_LAYERS  # all layers fit
    return max(0, n)


def describe_gpu_layers(n_gpu_layers: Optional[int], total_layers: Optional[int] = None) -> str:
    """Render a gpu_layers value for a human to read.

    -1 (or anything >= the model's real layer count) is llama.cpp's own
    convention for "offload every layer there is" — not a literal count
    layers. Printed raw next to the actual, usually much lower, layer count
    used elsewhere in the same panel (e.g. a 40-layer MoE fit), it reads as a
    conflicting, higher number rather than the same "everything that fits"
    outcome restated. Every user-facing gpu_layers string should go through
    this rather than an f-string embedding the raw int.
    """
    if n_gpu_layers is None:
        return "unset"
    n = int(n_gpu_layers)
    if total_layers and (n < 0 or n >= int(total_layers)):
        return f"all {int(total_layers)} layers"
    # No total on hand, but still never print the raw sentinel itself.
    if n < 0:
        return "all layers"
    return str(n)


def _fit_needed_mb(
    model_size_gb: float,
    total_layers: int,
    ctx: int,
    layers: int,
    batch: int,
    *,
    kv_quantized: bool,
    cost: Optional["ModelCost"] = None,
) -> float:
    """VRAM bytes for GPU-resident weights + KV + compute graph."""
    compute = _compute_graph_reserve_mb(ctx, batch)
    if cost is not None:
        real = _fit_layers_real(layers, total_layers)
        return (cost.gpu_weights_mb(int(layers)) + cost.kv_mb(ctx, gpu_layers=real)
                + compute + _CUDA_OVERHEAD_MB)
    mb_per_layer = (model_size_gb * 1024.0) / max(1, total_layers + 2)
    gpu_model = mb_per_layer * layers
    kv = _kv_cache_mb(ctx, total_layers, quant=kv_quantized)
    return gpu_model + kv + compute + _CUDA_OVERHEAD_MB


def _layer_ceiling(total: int, user_gpu_layers: Optional[int]) -> int:
    """The most layers a fit may put on the GPU: every one when nothing or -1 was asked."""
    if user_gpu_layers is None or int(user_gpu_layers) < 0:
        return int(total)
    return min(int(total), int(user_gpu_layers))


def _fit_layers_real(layers: int, total_layers: int) -> int:
    if int(layers) < 0 or int(layers) >= int(total_layers):
        return int(total_layers)
    return max(0, min(int(layers), int(total_layers)))


def _estimate_cpu_spill_mb(
    model_size_gb: float,
    total_layers: int,
    gpu_layers_real: int,
    ctx: int,
    batch: int,
    *,
    kv_quantized: bool = False,
    cost: Optional["ModelCost"] = None,
) -> float:
    """System RAM for CPU-resident weights and KV when running CPU-only."""
    if cost is not None:
        spill = cost.cpu_weights_mb(gpu_layers_real) + cost.kv_mb(ctx) - cost.kv_mb(ctx, gpu_layers=gpu_layers_real)
        if gpu_layers_real <= 0:
            spill += _compute_graph_reserve_mb(ctx, batch) * 0.25
        return spill + 256.0
    mb_per_layer = (model_size_gb * 1024.0) / max(1, total_layers + 2)
    cpu_layers = max(0, int(total_layers) - int(gpu_layers_real))
    spill = mb_per_layer * cpu_layers
    if gpu_layers_real <= 0:
        spill += _kv_cache_mb(ctx, total_layers, quant=kv_quantized)
        spill += _compute_graph_reserve_mb(ctx, batch) * 0.25
    spill += 256.0
    return spill


def _smart_fit_balanced(
    model_size_gb: float,
    budget: int,
    *,
    user_ctx: int,
    user_batch: int,
    kv_quantized: bool,
    total: int,
    ctx_grain: int,
    min_ctx: int,
    min_batch: int,
    min_gpu_fraction: float,
    user_gpu_layers: Optional[int] = None,
    cost: Optional["ModelCost"] = None,
) -> tuple[int, int, int]:
    """Balanced: shed GPU layers → batch → ctx (context preserved as long as possible)."""
    ctx = max(min_ctx, int(user_ctx))
    _target_ctx = int(ctx)
    batch = max(min_batch, int(user_batch))
    # The operator's layer count is a ceiling: never return more layers than asked, even if headroom opens up.
    ceiling = _layer_ceiling(total, user_gpu_layers)
    layers = ceiling

    if budget <= 0:
        return ctx, 0, batch

    floor = min(max(0, int(total * min_gpu_fraction)), ceiling)
    step = max(1, total // 10)

    while layers > floor and _fit_needed_mb(
            model_size_gb, total, ctx, layers, batch, kv_quantized=kv_quantized, cost=cost) > budget:
        layers = max(floor, layers - step)
    while batch > min_batch and _fit_needed_mb(
            model_size_gb, total, ctx, layers, batch, kv_quantized=kv_quantized, cost=cost) > budget:
        batch = max(min_batch, batch // 2)
    while layers > 0 and _fit_needed_mb(
            model_size_gb, total, ctx, layers, batch, kv_quantized=kv_quantized, cost=cost) > budget:
        layers = max(0, layers - step)
    while ctx > min_ctx and _fit_needed_mb(
            model_size_gb, total, ctx, layers, batch, kv_quantized=kv_quantized, cost=cost) > budget:
        ctx = max(min_ctx, ctx - ctx_grain)

    while layers < ceiling and _fit_needed_mb(
            model_size_gb, total, ctx, layers + 1, batch, kv_quantized=kv_quantized, cost=cost) <= budget:
        layers += 1

    if layers <= 0 and budget > 0 and ctx < _target_ctx:
        probe_layers = 0
        while probe_layers < ceiling and _fit_needed_mb(
                model_size_gb, total, min_ctx, probe_layers + 1, min_batch,
                kv_quantized=kv_quantized, cost=cost) <= budget:
            probe_layers += 1
        if probe_layers > 0:
            ctx, batch, layers = min_ctx, min_batch, probe_layers

    n_layers = ALL_GPU_LAYERS if layers >= total else layers
    return ctx, n_layers, batch


def _smart_fit_max_gpu(
    model_size_gb: float,
    budget: int,
    *,
    user_ctx: int,
    user_batch: int,
    kv_quantized: bool,
    total: int,
    ctx_grain: int,
    min_ctx: int,
    min_batch: int,
    user_gpu_layers: Optional[int] = None,
    cost: Optional["ModelCost"] = None,
) -> tuple[int, int, int]:
    """Max GPU: shrink ctx/batch before shedding layers; pack VRAM with layers."""
    ctx = max(min_ctx, int(user_ctx))
    batch = max(min_batch, int(user_batch))
    # See _smart_fit_balanced: the operator's layer count is a ceiling the
    # backfill loop below must not exceed, same reasoning as ctx/batch above.
    ceiling = _layer_ceiling(total, user_gpu_layers)
    layers = ceiling

    if budget <= 0:
        return ctx, 0, batch

    step = max(1, total // 10)

    while layers == ceiling and _fit_needed_mb(
            model_size_gb, total, ctx, layers, batch, kv_quantized=kv_quantized, cost=cost) > budget:
        if ctx > min_ctx:
            ctx = max(min_ctx, ctx - ctx_grain)
        elif batch > min_batch:
            batch = max(min_batch, batch // 2)
        else:
            break

    while layers > 0 and _fit_needed_mb(
            model_size_gb, total, ctx, layers, batch, kv_quantized=kv_quantized, cost=cost) > budget:
        layers = max(0, layers - step)

    while layers < ceiling and _fit_needed_mb(
            model_size_gb, total, ctx, layers + 1, batch, kv_quantized=kv_quantized, cost=cost) <= budget:
        layers += 1

    n_layers = ALL_GPU_LAYERS if layers >= total else layers
    return ctx, n_layers, batch


def _smart_fit_max_ctx(
    model_size_gb: float,
    budget: int,
    *,
    user_ctx: int,
    user_batch: int,
    kv_quantized: bool,
    total: int,
    ctx_grain: int,
    min_ctx: int,
    min_batch: int,
    user_gpu_layers: Optional[int] = None,
    cost: Optional["ModelCost"] = None,
) -> tuple[int, int, int]:
    """Max context: preserve ctx via CPU/RAM spill; add GPU layers only if ctx stays."""
    ctx = max(min_ctx, int(user_ctx))
    batch = max(min_batch, int(user_batch))
    # See _smart_fit_balanced: the operator's layer count is a ceiling the
    # backfill loop below must not exceed, same reasoning as ctx/batch above.
    ceiling = _layer_ceiling(total, user_gpu_layers)
    layers = ceiling

    if budget <= 0:
        return ctx, 0, batch

    if _fit_needed_mb(model_size_gb, total, ctx, layers, batch, kv_quantized=kv_quantized, cost=cost) > budget:
        layers = 0
        while batch > min_batch and _fit_needed_mb(
                model_size_gb, total, ctx, 0, batch, kv_quantized=kv_quantized, cost=cost) > budget:
            batch = max(min_batch, batch // 2)
        while ctx > min_ctx and _fit_needed_mb(
                model_size_gb, total, ctx, 0, batch, kv_quantized=kv_quantized, cost=cost) > budget:
            ctx = max(min_ctx, ctx - ctx_grain)

    while layers < ceiling and _fit_needed_mb(
            model_size_gb, total, ctx, layers + 1, batch, kv_quantized=kv_quantized, cost=cost) <= budget:
        layers += 1

    n_layers = ALL_GPU_LAYERS if layers >= total else layers
    return ctx, n_layers, batch


def _clamp_fit_to_ram_budget(
    model_size_gb: float,
    vram_budget: int,
    ram_budget_mb: int,
    ctx: int,
    layers: int,
    batch: int,
    *,
    user_ctx: int,
    kv_quantized: bool,
    total: int,
    ctx_grain: int,
    min_ctx: int,
    min_batch: int,
    priority: str,
    user_gpu_layers: Optional[int] = None,
    cost: Optional["ModelCost"] = None,
) -> tuple[int, int, int]:
    """Joint planner: CPU spill from partial offload must fit the RAM slider budget."""
    if ram_budget_mb <= 0:
        return ctx, layers, batch

    priority = normalize_fit_priority(priority)
    step = max(1, total // 10)
    # Same ceiling as the VRAM-only fit functions: never grow layers past what
    # the operator asked for just because RAM/VRAM headroom allows it.
    ceiling = _layer_ceiling(total, user_gpu_layers)

    for _ in range(128):
        real = _fit_layers_real(layers, total)
        spill = _estimate_cpu_spill_mb(
            model_size_gb, total, real, ctx, batch, kv_quantized=kv_quantized, cost=cost)
        if spill <= ram_budget_mb:
            break

        if real < ceiling and _fit_needed_mb(
                model_size_gb, total, ctx, real + 1, batch,
                kv_quantized=kv_quantized, cost=cost) <= vram_budget:
            real += 1
            layers = ALL_GPU_LAYERS if real >= total else real
            continue

        # With any layer on the GPU the spill is weights only, so ctx and batch cannot change it,
        # and the weights are memory-mapped, so a shortfall is paged from disk rather than fatal.
        # Shrinking ctx here only threw away the operator's context for nothing.
        if real > 0:
            break

        moved = False
        if priority == FIT_PRIORITY_MAX_GPU and ctx > min_ctx:
            ctx = max(min_ctx, ctx - ctx_grain)
            moved = True
        elif batch > min_batch:
            batch = max(min_batch, batch // 2)
            moved = True
        elif ctx > min_ctx:
            ctx = max(min_ctx, ctx - ctx_grain)
            moved = True
        if not moved:
            break

    if priority == FIT_PRIORITY_MAX_GPU and vram_budget > 0:
        real = _fit_layers_real(layers, total)
        if 0 < real < total:
            probe = ctx
            target = max(min_ctx, int(user_ctx))
            while probe + ctx_grain <= target:
                probe += ctx_grain
                if _fit_needed_mb(
                        model_size_gb, total, probe, real, batch,
                        kv_quantized=kv_quantized, cost=cost) > vram_budget:
                    break
                spill = _estimate_cpu_spill_mb(
                    model_size_gb, total, real, probe, batch, kv_quantized=kv_quantized, cost=cost)
                if spill > ram_budget_mb:
                    break
                ctx = probe

    n_layers = ALL_GPU_LAYERS if _fit_layers_real(layers, total) >= total else _fit_layers_real(layers, total)
    return ctx, n_layers, batch


def smart_fit_config(
    model_size_gb: float,
    free_vram_mb: int,
    *,
    user_ctx: int,
    user_batch: int,
    reserve_mb: int = 700,
    kv_quantized: bool = False,
    total_layers: Optional[int] = None,
    model_path: Optional[str] = None,
    ctx_grain: int = 2048,
    min_ctx: int = 2048,
    min_batch: int = 128,
    min_gpu_fraction: float = 0.25,
    fit_priority: Optional[str] = None,
    user_gpu_layers: Optional[int] = None,
    moe_resident_gb: Optional[float] = None,
    kv_cache_type: Optional[str] = None,
) -> tuple[int, int, int]:
    """VRAM-only smart loader fit (backward compatible).

    Dispatches to balanced / max_gpu / max_ctx reduction order. For joint
    VRAM+RAM planning on discrete GPUs, use ``unified_fit_config``.

    ``user_gpu_layers``, when given, is a CEILING: the fit may reduce it to
    make the request fit, but will never hand back more layers than the
    operator asked for. Omit it (as every pre-2.4.55 caller does) to keep the
    old behaviour of backfilling spare VRAM up to the model's full layer count.

    ``moe_resident_gb``, when given, is the real GPU-resident weight size for a
    mixture-of-experts model under expert offload (everything except expert
    tensors, which stay in RAM regardless of layer count — see
    ``eli.core.moe_offload``). The per-layer VRAM cost is sized from this
    instead of the full file size; the layer-count CEILING still comes from
    the model's real total layer count (``total_layers`` / ``model_path``),
    which is unaffected. Omit it for ordinary dense models.
    """
    total = int(total_layers or layers_for_model(model_path, model_size_gb))
    budget = max(0, int(free_vram_mb) - int(reserve_mb))
    priority = normalize_fit_priority(fit_priority or FIT_PRIORITY_BALANCED)
    _fit_size_gb = float(moe_resident_gb) if moe_resident_gb is not None else float(model_size_gb)
    common = dict(
        user_ctx=user_ctx,
        user_batch=user_batch,
        kv_quantized=kv_quantized,
        total=total,
        ctx_grain=ctx_grain,
        min_ctx=min_ctx,
        min_batch=min_batch,
        user_gpu_layers=user_gpu_layers,
        cost=model_cost(model_path, experts_in_ram=moe_resident_gb is not None,
                        kv_quantized=kv_quantized, kv_cache_type=kv_cache_type),
    )
    if priority == FIT_PRIORITY_MAX_GPU:
        return _smart_fit_max_gpu(_fit_size_gb, budget, **common)
    if priority == FIT_PRIORITY_MAX_CTX:
        return _smart_fit_max_ctx(_fit_size_gb, budget, **common)
    return _smart_fit_balanced(
        _fit_size_gb, budget, min_gpu_fraction=min_gpu_fraction, **common)


def unified_fit_config(
    model_size_gb: float,
    free_vram_mb: int,
    available_ram_gb: float,
    *,
    user_ctx: int,
    user_batch: int,
    reserve_mb: int = 700,
    kv_quantized: bool = False,
    total_layers: Optional[int] = None,
    model_path: Optional[str] = None,
    ctx_grain: int = 2048,
    min_ctx: int = 2048,
    min_batch: int = 128,
    min_gpu_fraction: float = 0.25,
    fit_priority_mode: Optional[str] = None,
    gpu_integrated: bool = False,
    force_cpu: bool = False,
    user_gpu_layers: Optional[int] = None,
    moe_resident_gb: Optional[float] = None,
    kv_cache_type: Optional[str] = None,
) -> tuple[int, int, int]:
    """Joint VRAM + RAM planner for every OS and GPU class.

    • Discrete GPU — sizes layers from free VRAM, then verifies CPU spill fits
      the RAM budget (startup slider). Raising RAM % allows more CPU spill so
      mid-tier cards can supercharge context without OOM.
    • Integrated / CPU-only — budgets from available RAM (same math as before).

    ``user_gpu_layers``, when given, caps every fallback this function can
    produce — it will reduce that value to fit, never grow it. See
    ``smart_fit_config`` for why this matters.

    ``moe_resident_gb``, when given, is passed straight through to
    ``smart_fit_config`` — see its docstring. With a readable model file both
    the VRAM fit and the RAM clamp use its tensor sizes (``model_cost``).

    ``kv_cache_type`` is the cache type asked for; it is sized as the one that loads for it
    (gguf_sizes.effective_cache_type).
    """
    total = int(total_layers or layers_for_model(model_path, model_size_gb))
    priority = (
        normalize_fit_priority(fit_priority_mode)
        if fit_priority_mode is not None
        else fit_priority()
    )
    ram_budget_mb = cpu_ram_budget_mb(available_ram_gb)
    _cost = model_cost(model_path, experts_in_ram=moe_resident_gb is not None,
                       kv_quantized=kv_quantized, kv_cache_type=kv_cache_type)

    if force_cpu or int(free_vram_mb) <= 0:
        ctx, layers, batch = smart_fit_config(
            model_size_gb,
            ram_budget_mb,
            user_ctx=user_ctx,
            user_batch=user_batch,
            reserve_mb=512,
            kv_quantized=kv_quantized,
            total_layers=total,
            model_path=model_path,
            ctx_grain=ctx_grain,
            min_ctx=min_ctx,
            min_batch=min_batch,
            min_gpu_fraction=0.0,
            fit_priority=priority,
            user_gpu_layers=user_gpu_layers,
            moe_resident_gb=moe_resident_gb,
            kv_cache_type=kv_cache_type,
        )
        return ctx, 0, batch

    if gpu_integrated:
        shared_budget = min(int(free_vram_mb), ram_budget_mb)
        ctx, layers, batch = smart_fit_config(
            model_size_gb,
            shared_budget,
            user_ctx=user_ctx,
            user_batch=user_batch,
            reserve_mb=reserve_mb,
            kv_quantized=kv_quantized,
            total_layers=total,
            model_path=model_path,
            ctx_grain=ctx_grain,
            min_ctx=min_ctx,
            min_batch=min_batch,
            min_gpu_fraction=min_gpu_fraction,
            fit_priority=priority,
            user_gpu_layers=user_gpu_layers,
            moe_resident_gb=moe_resident_gb,
            kv_cache_type=kv_cache_type,
        )
        return _clamp_fit_to_ram_budget(
            model_size_gb,
            max(0, shared_budget - int(reserve_mb)),
            ram_budget_mb,
            ctx,
            layers,
            batch,
            user_ctx=user_ctx,
            kv_quantized=kv_quantized,
            total=total,
            ctx_grain=ctx_grain,
            min_ctx=min_ctx,
            min_batch=min_batch,
            priority=priority,
            user_gpu_layers=user_gpu_layers,
            cost=_cost,
        )

    vram_budget = max(0, int(free_vram_mb) - int(reserve_mb))
    ctx, layers, batch = smart_fit_config(
        model_size_gb,
        free_vram_mb,
        user_ctx=user_ctx,
        user_batch=user_batch,
        reserve_mb=reserve_mb,
        kv_quantized=kv_quantized,
        total_layers=total,
        model_path=model_path,
        ctx_grain=ctx_grain,
        min_ctx=min_ctx,
        min_batch=min_batch,
        min_gpu_fraction=min_gpu_fraction,
        fit_priority=priority,
        user_gpu_layers=user_gpu_layers,
        moe_resident_gb=moe_resident_gb,
        kv_cache_type=kv_cache_type,
    )
    return _clamp_fit_to_ram_budget(
        model_size_gb,
        vram_budget,
        ram_budget_mb,
        ctx,
        layers,
        batch,
        user_ctx=user_ctx,
        kv_quantized=kv_quantized,
        total=total,
        ctx_grain=ctx_grain,
        min_ctx=min_ctx,
        min_batch=min_batch,
        priority=priority,
        user_gpu_layers=user_gpu_layers,
        cost=_cost,
    )


def _auto_ctx_limits(
    model_path: Optional[str],
    model_size_gb: float,
    *,
    free_vram_mb: int,
    available_ram_gb: float,
    use_gpu: bool,
    kv_quantized: bool = False,
    kv_cache_type: Optional[str] = None,
) -> tuple[int, Optional[int]]:
    """(wanted, cap): the model's trained context x ELI_CTX_FRACTION (0 when unread), and the
    ctx whose KV cache fits ELI_CTX_KV_SHARE of the memory left after the weights (None when
    memory cannot be measured)."""
    wanted = 0
    try:
        # Only a trained context that was actually read counts; train_ctx_for_model substitutes a constant.
        from eli.core.startup_hardware_optimizer import _gguf_metadata_ctx
        _forced = (os.environ.get("ELI_MODEL_TRAIN_CTX") or "").strip()
        if _forced.isdigit():
            wanted = int(_forced)
        elif model_path:
            wanted = int(_gguf_metadata_ctx(str(model_path)) or 0)
        frac = float(os.environ.get("ELI_CTX_FRACTION", "0.9") or "0.9")
        wanted = int(wanted * max(0.05, min(1.0, frac)))
    except Exception:
        log.debug("trained context unavailable for auto ctx", exc_info=True)
        wanted = 0

    cap = None
    try:
        share = float(os.environ.get("ELI_CTX_KV_SHARE", "0.5") or "0.5")
        spare_mb = (int(free_vram_mb) if use_gpu else 0) \
            + cpu_ram_budget_mb(available_ram_gb) - float(model_size_gb) * 1024.0
        cost = model_cost(model_path, kv_quantized=kv_quantized, kv_cache_type=kv_cache_type)
        if cost is not None:
            per_token = cost.kv_mb(1)
        else:
            per_token = _kv_cache_mb(1024, layers_for_model(model_path, model_size_gb),
                                     quant=kv_quantized) / 1024.0
        if per_token > 0:
            # A measured shortage is a cap of zero (the floor), not "no limit".
            cap = max(0, int(max(0.0, spare_mb) * max(0.05, min(1.0, share)) / per_token))
    except Exception:
        log.debug("memory-derived ctx cap unavailable", exc_info=True)
        cap = None
    return wanted, cap


def auto_ctx_target(
    model_path: Optional[str],
    model_size_gb: float,
    *,
    free_vram_mb: int,
    available_ram_gb: float,
    use_gpu: bool,
    kv_quantized: bool = False,
    grain: int = 2048,
    kv_cache_type: Optional[str] = None,
) -> int:
    """The ctx "auto" aims for: the smaller of the model's trained context x ELI_CTX_FRACTION
    and the ctx whose KV cache fits ELI_CTX_KV_SHARE of the memory left after the weights.

    A target only; the fit still reduces it. When neither limit can be measured (no model file
    and no memory reading) it is the smallest window ELI loads, the grain: nothing here picks a
    size for the operator's machine.
    """
    wanted, cap = _auto_ctx_limits(
        model_path, model_size_gb, free_vram_mb=free_vram_mb, available_ram_gb=available_ram_gb,
        use_gpu=use_gpu, kv_quantized=kv_quantized, kv_cache_type=kv_cache_type)
    limits = [v for v in (wanted if wanted > 0 else None, cap) if v is not None]
    if not limits:
        return int(grain)
    return max(grain, (min(limits) // grain) * grain)


def mlock_holds(model_size_gb: float, available_ram_gb: float) -> bool:
    """Whether pinning this model in RAM is safe and possible: it fits the RAM budget ELI may use,
    and the OS memory-lock limit (often a few MB) covers it. Where the limit cannot be read
    (Windows), no."""
    try:
        import resource
        soft, _hard = resource.getrlimit(resource.RLIMIT_MEMLOCK)
    except Exception:
        return False
    model_bytes = float(model_size_gb) * 1024 ** 3
    if soft != resource.RLIM_INFINITY and soft < model_bytes:
        return False
    return model_bytes / 1_048_576 <= cpu_ram_budget_mb(available_ram_gb)


def auto_ctx_for(model_path: Optional[str]) -> int:
    """auto_ctx_target for this model on this machine as measured now; 0 without a readable model."""
    try:
        p = Path(str(model_path or ""))
        if not p.is_file():
            return 0
        size_gb = mem_units.file_size_gib(p)
        hw = detect_hardware()
        use_gpu = bool(effective_use_gpu_layers(hw))
        free = int(hw.free_vram_mb) if use_gpu else 0
        kvq = kv_cache_quantized(str(p), size_gb, free_vram_mb=free,
                                 available_ram_gb=float(hw.available_ram_gb), use_gpu=use_gpu)
        return int(auto_ctx_target(str(p), size_gb, free_vram_mb=free,
                                   available_ram_gb=float(hw.available_ram_gb), use_gpu=use_gpu,
                                   kv_quantized=kvq))
    except Exception:
        log.debug("auto context unavailable for %s", model_path, exc_info=True)
        return 0


def kv_cache_quantized(
    model_path: Optional[str],
    model_size_gb: float,
    *,
    free_vram_mb: int,
    available_ram_gb: float,
    use_gpu: bool,
    target_ctx: Optional[int] = None,
) -> bool:
    """Quantize the KV cache only when memory, not the model, limits the context: an fp16 cache
    in the memory left after the weights holds less than the context wanted (the operator's
    target_ctx, else the auto target). Replaces a card-size rule (q4_0 below 12000 MB) that
    quantized a model whose fp16 cache fitted easily and left a 16 GB card at fp16 when it did
    not. Unknown either way: fp16, llama.cpp's default."""
    wanted, cap = _auto_ctx_limits(
        model_path, model_size_gb, free_vram_mb=free_vram_mb, available_ram_gb=available_ram_gb,
        use_gpu=use_gpu, kv_cache_type="f16")
    want = int(target_ctx or 0) or wanted
    return bool(cap is not None and want > 0 and cap < want)


def recommend(hw: Optional[HardwareProfile] = None,
              models: Optional[List[Dict[str, Any]]] = None,
              user_ctx: Optional[int] = None) -> ModelRecommendation:
    """Generate optimal model + parameter recommendation for this hardware.

    Picks the largest model that fits within free VRAM (after KV cache +
    CUDA overhead) OR within available RAM if no GPU.

    ``user_ctx`` (when > 0) is the user's EXPLICITLY chosen context window —
    it anchors n_ctx instead of the auto target, and the VRAM refinement
    below only ever REDUCES it to fit (never inflates, never silently replaces).
    This is what makes "what you type is what loads" hold: the chosen value wins,
    and is only trimmed on a real VRAM constraint (and the reasoning log says so).
    """
    if hw is None:
        hw = detect_hardware()
    if models is None:
        models = discover_models()

    rec = ModelRecommendation()
    rec.reasoning = []

    rec.n_threads = recommend_cpu_threads(hw.cpu_threads, physical=hw.cpu_cores)
    rec.reasoning.append(
        f"CPU: {hw.cpu_cores or hw.cpu_threads} cores, {hw.cpu_threads} threads → using {rec.n_threads} "
        f"(one per core: a core's second thread shares its vector units)"
    )
    rec.reasoning.append(
        f"RAM: {hw.ram_gb:.1f}GB total, {hw.available_ram_gb:.1f}GB available"
    )
    if hw.has_gpu:
        if hw.gpu_integrated:
            _igpu_kind = integrated_gpu_label(hw.gpu_name, hw.gpu_vendor)
            rec.reasoning.append(
                f"GPU: {hw.gpu_name} — {_igpu_kind} using shared system RAM "
                f"(~{hw.free_vram_mb/1024.0:.1f}GB budgeted, not dedicated VRAM)"
            )
            if hw.gpu_vendor == "apple":
                rec.reasoning.append(
                    "Apple unified memory — Metal backend when available; "
                    "layer count reflects shared-memory fit"
                )
            elif hw.gpu_vendor == "qualcomm":
                rec.reasoning.append(
                    "Snapdragon / Adreno unified memory — Vulkan offload is "
                    "experimental; batch capped at 32 for driver stability"
                )
            elif hw.vulkan_available:
                rec.reasoning.append(
                    "Vulkan loader present — optional GPU offload via "
                    "ELI --install-gpu-pack --vulkan (experimental on shared-memory GPUs)"
                )
            else:
                rec.reasoning.append(
                    "Vulkan loader not found — CPU mode until GPU drivers / "
                    "vulkan-icd are installed"
                )
            if not _llama_gpu_offload_available():
                rec.reasoning.append(
                    "llama-cpp has no active GPU backend — CPU inference for now "
                    f"(reliable on {_igpu_kind}; install the GPU pack to try offload)"
                )
        else:
            rec.reasoning.append(
                f"GPU: {hw.gpu_name} — {hw.free_vram_mb/1024.0:.2f}GB free / "
                f"{hw.total_vram_mb/1024.0:.1f}GB total"
            )
    else:
        rec.reasoning.append("GPU: none detected (CPU-only mode)")

    use_gpu_layers = effective_use_gpu_layers(hw)
    _backend_ready = _llama_gpu_offload_available()
    if hw.has_gpu and not _backend_ready:
        _igpu_kind = integrated_gpu_label(hw.gpu_name, hw.gpu_vendor)
        rec.reasoning.append(
            f"{_igpu_kind} layer count below reflects shared-memory fit; "
            "install the GPU pack to offload them (CPU remains reliable "
            "when no GPU backend is active)"
        )

    if not models:
        # The provider stays as it is: Ollama is used only when the user chooses it.
        rec.reasoning.append("No GGUF models found: download one, or choose an Ollama model as the provider.")
        return rec

    # One model to tune for (the startup window's choice): the plan the loader will use, so the
    # recommendation and the load are the same numbers.
    if len(models) == 1 and use_gpu_layers and _recommend_from_plan(rec, hw, models[0], user_ctx):
        return rec

    # KV-cache quantization: only when memory, not the model, limits the context. q8_0 holds
    # nearly twice the context of fp16 in the same memory and answers the same; q4_0 does not
    # (gguf_sizes.QUANTIZED_CACHE).
    from eli.core.gguf_sizes import QUANTIZED_CACHE as _kv_quantized_type
    _kv_m = max(models, key=lambda m: m["size_gb"]) if models else None
    rec.cache_type_k = _kv_quantized_type if (_kv_m and kv_cache_quantized(
        _kv_m["path"], _kv_m["size_gb"],
        free_vram_mb=hw.free_vram_mb if use_gpu_layers else 0,
        available_ram_gb=hw.available_ram_gb, use_gpu=bool(use_gpu_layers),
        target_ctx=int(user_ctx) if user_ctx and int(user_ctx) > 0 else None,
    )) else ""
    rec.cache_type_v = rec.cache_type_k  # match K and V quantization
    kv_q = bool(rec.cache_type_k)
    if kv_q:
        rec.reasoning.append(f"KV cache: {_kv_quantized_type} (an fp16 cache would not hold the context in the memory left after the weights)")
    else:
        rec.reasoning.append("KV cache: fp16 (it fits the context in the memory left after the weights)")

    # Context window: on GPU systems drive ctx from the VRAM KV budget, not RAM (available RAM
    # fluctuates and gave ctx=2048 on a machine that handles 18K+). Start from the model's full
    # training window and let the VRAM refinement below set the ceiling. CPU-only is RAM-bound.
    _ctx_grain = 2048
    if user_ctx and int(user_ctx) > 0:
        rec.n_ctx = int(user_ctx)                  # what was typed, not rounded to the auto grain
        _ctx_note = "user-pinned — reduced to fit only if memory is tight"
    else:
        _auto_m = max(models, key=lambda m: m["size_gb"]) if models else None
        rec.n_ctx = auto_ctx_target(
            _auto_m["path"] if _auto_m else None,
            _auto_m["size_gb"] if _auto_m else 0.0,
            free_vram_mb=hw.free_vram_mb, available_ram_gb=hw.available_ram_gb,
            use_gpu=bool(use_gpu_layers), kv_quantized=bool(rec.cache_type_k),
            grain=_ctx_grain,
        )
        _ctx_note = (f"auto {rec.n_ctx} — from the model's trained context and this "
                     f"machine's memory, reduced to fit if memory is tight")
    if use_gpu_layers:
        rec.reasoning.append(f"n_ctx={rec.n_ctx} (GPU — {_ctx_note})")
    else:
        rec.reasoning.append(
            f"n_ctx={rec.n_ctx} (CPU/RAM — {_ctx_note}; "
            f"ram={hw.ram_gb:.1f}GB available={hw.available_ram_gb:.1f}GB)"
        )

    # Pick the largest model that actually fits, given the chosen ctx and
    # KV-quantization regime.
    models_sorted = sorted(models, key=lambda m: m["size_gb"])
    chosen = None
    chosen_layers = 0
    for m in reversed(models_sorted):
        if use_gpu_layers:
            layers = _fit_layers_real(_gpu_layers_for_model(
                m["size_gb"], hw.free_vram_mb, rec.n_ctx, kv_quantized=kv_q,
                model_path=m["path"],
            ), layers_for_model(m["path"], m["size_gb"]))
            if hw.gpu_integrated:
                layers = min(layers, max(4, int(layers_for_model(m["path"], m["size_gb"]) * 0.25)))
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
        chosen_layers = (_fit_layers_real(_gpu_layers_for_model(
            chosen["size_gb"], hw.free_vram_mb, rec.n_ctx, kv_quantized=kv_q,
            model_path=chosen["path"],
        ), layers_for_model(chosen["path"], chosen["size_gb"])) if use_gpu_layers else 0)
        if use_gpu_layers and hw.gpu_integrated and chosen_layers > 0:
            chosen_layers = min(
                chosen_layers,
                max(4, int(layers_for_model(chosen["path"], chosen["size_gb"]) * 0.25)),
            )
        rec.reasoning.append(
            f"Falling back to smallest: {chosen['name']} ({chosen['size_gb']:.1f}GB)"
        )

    # If the largest-model attempt found 0 GPU layers at this ctx, retry smaller-model first: ctx is
    # so big the KV cache eats VRAM. recommend() should give something usable on GPU whenever one
    # exists.

    rec.model_path = chosen["path"]
    rec.model_name = chosen["name"]
    rec.model_size_gb = chosen["size_gb"]
    rec.n_gpu_layers = chosen_layers

    # One fit, not two. This recommendation is shown to the operator and stored as the hw_profile_*
    # fallback, so it has to predict what the loader does. The old blocks cut ctx to pay for layers,
    # while smart_fit_config keeps ctx and sheds layers, so the tuner and the load disagreed.
    import os as _os_fit
    _env_target_batch = int(_os_fit.environ.get("ELI_TARGET_BATCH", "0") or "0")
    _fit_batch_in = (
        _env_target_batch
        if _env_target_batch > 0
        else max(128, int(_os_fit.environ.get("ELI_MIN_BATCH", "128") or "128"))
    )
    _igpu_min_batch = 32 if hw.gpu_integrated else 128
    if hw.gpu_integrated:
        _fit_batch_in = min(_fit_batch_in, _igpu_min_batch)

    _pre_fit_ctx = rec.n_ctx  # the MoE re-fit below must start from this, not the naive
                               # fit's (possibly needlessly shrunk) result — captured
                               # unconditionally since the MoE block can run even when
                               # use_gpu_layers is False (GPU present, backend not active)
    _dense_fit_line = None
    if use_gpu_layers:
        _total_layers_est = layers_for_model(chosen["path"], chosen["size_gb"])
        _fit_ctx, _fit_layers, _fit_batch = unified_fit_config(
            chosen["size_gb"], hw.free_vram_mb, hw.available_ram_gb,
            user_ctx=rec.n_ctx, user_batch=_fit_batch_in,
            reserve_mb=vram_reserve_mb(gpu_integrated=hw.gpu_integrated),
            kv_quantized=kv_q,
            model_path=chosen["path"], total_layers=_total_layers_est,
            min_batch=_igpu_min_batch,
            gpu_integrated=hw.gpu_integrated,
        )
        _fit_count = _fit_layers_real(_fit_layers, _total_layers_est)
        _old_ctx, _old_layers = rec.n_ctx, rec.n_gpu_layers
        rec.n_ctx = int(_fit_ctx)
        rec.n_gpu_layers = _fit_count
        rec.batch_size = max(rec.batch_size, int(_fit_batch))
        chosen_layers = _fit_count
        _fp = fit_priority()
        _dense_fit_line = len(rec.reasoning)
        rec.reasoning.append(
            f"Fit ({_fp}, joint VRAM+RAM): ctx={rec.n_ctx} "
            f"gpu_layers={rec.n_gpu_layers} batch={rec.batch_size} "
            f"for {hw.free_vram_mb:.0f}MB free VRAM + "
            f"{cpu_ram_budget_mb(hw.available_ram_gb)}MB RAM spill budget "
            f"(reserve {vram_reserve_mb()}MB, kv={_kv_quantized_type if kv_q else 'fp16'}) "
            f"— was ctx={_old_ctx} gpu_layers={_old_layers} before the fit"
        )
    else:
        try:
            from eli.core.startup_hardware_optimizer import cpu_ctx_ceiling_from_ram as _ram_ceil
            from eli.core.startup_hardware_optimizer import train_ctx_for_model as _train_ctx
            _train = int(_train_ctx(chosen["path"]) or 0)
            _ceil = int(_ram_ceil(chosen["size_gb"], _train, model_path=chosen["path"]))
        except Exception:
            _ceil = 0
        _target_ctx = min(rec.n_ctx, _ceil) if _ceil > 0 else rec.n_ctx
        _fit_ctx, _fit_batch = cpu_ram_fit_config(
            chosen["size_gb"], hw.available_ram_gb,
            user_ctx=_target_ctx, user_batch=_fit_batch_in,
            model_path=chosen["path"], kv_quantized=kv_q,
            min_batch=_igpu_min_batch,
        )
        _old_ctx = rec.n_ctx
        rec.n_ctx = int(_fit_ctx)
        rec.n_gpu_layers = 0
        rec.batch_size = max(128, int(_fit_batch))
        chosen_layers = 0
        rec.reasoning.append(
            f"Fit (CPU/RAM — same calculation the loader runs): ctx={rec.n_ctx} "
            f"gpu_layers=0 batch={rec.batch_size} "
            f"for {hw.available_ram_gb:.1f}GB available RAM "
            f"(total {hw.ram_gb:.1f}GB, kv={_kv_quantized_type if kv_q else 'fp16'}) "
            f"— was ctx={_old_ctx} before the fit"
        )
        if hw.has_gpu and not _backend_ready:
            _igpu_kind = integrated_gpu_label(hw.gpu_name, hw.gpu_vendor)
            rec.reasoning.append(
                f"GPU pack not active — {_igpu_kind or hw.gpu_name} will stay CPU-only "
                f"until ELI --install-gpu-pack is run (optional Vulkan offload)"
            )

    total_layers = layers_for_model(chosen["path"], chosen["size_gb"])
    _full_offload = chosen_layers >= total_layers

    # The loader (and the GUI's own loader) may push a mixture-of-experts model onto more layers
    # than a naive split would, since expert tensors stay in RAM regardless of layer count and the
    # non-expert ("core") per-layer footprint is much smaller than the full file size. That real
    # core-layer fit is decided BEFORE the recommendation is built, so the number this panel shows
    # (rec.n_gpu_layers, also what gets saved as the canonical pin) is the one that actually loads
    # — a MEASURED fit against moe_resident_gb, not an unconditional "always all layers" assertion
    # (which had no fallback for a machine where even the core weights don't fit).
    _moe_plan = None
    if use_gpu_layers and not _full_offload:
        # Gated on use_gpu_layers (not chosen_layers > 0): a dense fit that already gave up
        # entirely (0 layers, VRAM too small for the full file) is exactly the case MoE offload
        # exists to rescue. But NOT when use_gpu_layers is False (GPU present with free VRAM yet
        # the llama.cpp backend isn't active) — offloading anything there, MoE or not, isn't
        # actually usable, matching the dense-fit branch's own CPU-only decision above.
        try:
            from eli.core import moe_offload as _moe_hw
            _moe_plan = _moe_hw.plan(
                chosen["path"], chosen["size_gb"], gpu_supported=bool(use_gpu_layers),
                free_vram_mb=int(hw.free_vram_mb), available_ram_gb=float(hw.available_ram_gb),
            )
        except Exception:
            _moe_plan = None
        if _moe_plan:
            _mf_ctx, _mf_layers, _mf_batch = unified_fit_config(
                chosen["size_gb"], hw.free_vram_mb, hw.available_ram_gb,
                user_ctx=_pre_fit_ctx, user_batch=_fit_batch_in,
                reserve_mb=vram_reserve_mb(gpu_integrated=hw.gpu_integrated),
                kv_quantized=kv_q, model_path=chosen["path"], total_layers=total_layers,
                min_batch=_igpu_min_batch, gpu_integrated=hw.gpu_integrated,
                moe_resident_gb=_moe_plan["resident_gb"],
            )
            chosen_layers = total_layers if int(_mf_layers) < 0 else int(_mf_layers)
            rec.n_ctx = int(_mf_ctx)
            rec.n_gpu_layers = chosen_layers
            rec.batch_size = max(rec.batch_size, int(_mf_batch))
            _full_offload = chosen_layers >= total_layers

    _rec_cost = model_cost(chosen["path"], experts_in_ram=bool(_moe_plan), kv_quantized=kv_q)
    if _moe_plan:
        if _dense_fit_line is not None:
            # Read as "only 8 layers load" (live, 2026-10-03). It's the whole-layer
            # calculation, superseded for an MoE model by the line below.
            rec.reasoning[_dense_fit_line] += (
                " — whole-layer fit, experts included; NOT used for this mixture-of-experts "
                "model (see the next line)")
        rec.reasoning.append(
            f"Model: {chosen['name']} ({chosen['size_gb']:.2f}GB), mixture-of-experts — "
            f"{chosen_layers}/{total_layers} layers' core weights fit in {hw.free_vram_mb:.0f}MB "
            f"free VRAM (~{_moe_plan['resident_gb']}GB); ~{_moe_plan['experts_gb']}GB of experts "
            f"stay in RAM regardless of layer count. This is what actually loads."
        )
    elif _full_offload:
        rec.reasoning.append(
            f"Model: {chosen['name']} ({chosen['size_gb']:.2f}GB) — "
            f"all layers on GPU (free VRAM sufficient)"
        )
    elif chosen_layers > 0:
        # Report the KV size actually budgeted, honouring kv_q: the figure in this line and the
        # one the fit reserves are the same call.
        rec.reasoning.append(
            f"Model: {chosen['name']} ({chosen['size_gb']:.2f}GB) — "
            f"{chosen_layers}/{total_layers} layers on GPU "
            f"(KV {_kv_cache_mb(rec.n_ctx, total_layers, quant=kv_q, cost=_rec_cost):.0f}MB "
            f"{_kv_quantized_type if kv_q else 'fp16'} + "
            f"{_CUDA_OVERHEAD_MB}MB CUDA overhead, "
            f"~{_kv_cache_mb(1024, total_layers, quant=kv_q, cost=_rec_cost):.0f}MB per 1k ctx)"
        )
    else:
        if hw.has_gpu and hw.gpu_integrated and not _backend_ready:
            _igpu_kind = integrated_gpu_label(hw.gpu_name, hw.gpu_vendor)
            rec.reasoning.append(
                f"Model: {chosen['name']} ({chosen['size_gb']:.2f}GB) — "
                f"CPU inference ({_igpu_kind}; install GPU pack to try offload)"
            )
        else:
            rec.reasoning.append(
                f"Model: {chosen['name']} ({chosen['size_gb']:.2f}GB) — CPU only"
            )

    # Batch size. The operator's target (startup dialog -> ELI_TARGET_BATCH) is the request; only
    # the VRAM-headroom pass below may reduce it, same as ctx and layers. It used to be overwritten
    # from the offload ratio (a dialog set to 512 stored 128). No target means the heuristic default.
    if _env_target_batch > 0:
        rec.batch_size = max(_igpu_min_batch, int(_env_target_batch))
        rec.reasoning.append(
            f"batch {rec.batch_size} — your target (reduced below only if the "
            f"measured compute headroom cannot hold it)"
        )
    elif chosen_layers == 0:
        # CPU: keep the RAM fit's batch when it asked for less (iGPU floors at 32);
        # otherwise the 128 default, since larger batches buy little without offload.
        rec.batch_size = max(_igpu_min_batch, min(int(rec.batch_size or 128), 128))
    elif _full_offload:
        rec.batch_size = 512
    else:
        _offload = min(1.0, chosen_layers / max(1, total_layers))
        _raw_b = int(128 + _offload * (512 - 128))
        rec.batch_size = max(128, (_raw_b // 64) * 64)

    # VRAM headroom check: llama.cpp compute buffers (rope, attention, graph workspace) use VRAM
    # beyond model + KV. On 8 GB cards with full offload and long ctx that leaves too little for
    # batch=512 (about 750 MB needed on 7B models, empirically).
    if hw.has_gpu and hw.free_vram_mb > 0 and chosen_layers > 0 and rec.batch_size > 128:
        _kv_at_ctx = _kv_cache_mb(rec.n_ctx, total_layers, quant=kv_q, cost=_rec_cost)
        if _rec_cost is not None:
            _gpu_model_for_batch = _rec_cost.gpu_weights_mb(chosen_layers)
        elif _moe_plan:
            # chosen_layers reads "all of them" here, but most of that is expert tensors kept in
            # RAM — sizing the compute-headroom check off the full model would see a huge deficit
            # that isn't real and needlessly crush the batch size.
            _gpu_model_for_batch = float(_moe_plan["resident_gb"]) * 1024.0
        else:
            _offload_f = min(1.0, chosen_layers / max(1, total_layers))
            _gpu_model_for_batch = chosen["size_gb"] * 1024.0 * _offload_f
        _compute_headroom = (hw.free_vram_mb
                             - _gpu_model_for_batch
                             - _kv_at_ctx
                             - float(_CUDA_OVERHEAD_MB))
        # Pick the largest batch whose decode-time compute buffer fits the remaining headroom plus a
        # margin. The buffer grows with ctx and batch, so the old fixed thresholds under-estimated at
        # long ctx and OOMed on first decode. _compute_graph_reserve_mb errs high on purpose.
        _SAFETY_MARGIN_MB = 400.0
        _safe_batch = _igpu_min_batch
        # The operator's own value leads the ladder: a target above 512 was
        # previously unreachable because the list started there, so a deliberate
        # 768 was silently served as 512 even on a card with room for it.
        _batch_candidates = sorted(
            {int(rec.batch_size), 512, 448, 384, 320, 256, 192, 128, _igpu_min_batch},
            reverse=True,
        )
        for _cand_b in _batch_candidates:
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

    # ELI_TARGET_BATCH is applied as the anchor where batch is chosen above, not as
    # a late cap: capping there could only ever LOWER the value, so a target higher
    # than the offload heuristic was unreachable and the setting looked ignored.

    # Adreno Vulkan in llama.cpp is unstable above batch 32 on Snapdragon laptops.
    if hw.gpu_vendor == "qualcomm" and chosen_layers > 0 and rec.batch_size > 32:
        rec.reasoning.append(f"batch capped {rec.batch_size}→32 — Adreno Vulkan stability limit")
        rec.batch_size = 32

    _finish_recommendation(rec, chosen, hw)
    return rec


def _finish_recommendation(rec: ModelRecommendation, chosen: Dict[str, Any], hw: HardwareProfile) -> None:
    """What every recommendation ends with: memory mapping, the reply ceiling and the reasoning-mode
    budgets, from the context it settled on."""
    # mmap lets the OS page weights from disk. mlock pins the whole model in RAM: only when this
    # model fits the RAM ELI may use and the OS lock limit allows it (it was "16 GB or more").
    rec.use_mmap = True
    rec.use_mlock = mlock_holds(chosen["size_gb"], hw.available_ram_gb)
    rec.max_tokens = -1   # unlimited — use full remaining context
    rec.temperature = 0.7

    # Per-reasoning-mode presets derived from the base tune: Quick is the reference and each other
    # mode carves a stage budget. The base max_tokens is the larger of the configured cap and a
    # ctx-scaled ceiling; `-1` (unlimited) uses n_ctx/4 capped at 4096.
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
        f"(ctx={rec.n_ctx}, max_tokens_ref={_max_for_derivation}); re-derived at load "
        f"time from the ctx actually loaded, which may be higher than this estimate"
    )


def _recommend_from_plan(rec: ModelRecommendation, hw: HardwareProfile, chosen: Dict[str, Any],
                         user_ctx: Optional[int]) -> bool:
    """Fill the recommendation from the load planner (eli/core/load_plan.py): the plan the loader
    will load with, measured by llama.cpp on every GPU it sees. False when the planner cannot run
    here (no GPU device llama.cpp can use, or a runtime without load simulation)."""
    try:
        from eli.core import load_plan
        if not load_plan.devices() or not load_plan.simulation_supported():
            return False
        from eli.cognition.gguf_inference import load_request
        req = load_request(chosen["path"])
        req.n_gpu_layers = None          # the recommendation is the most that fits, not a pin
        req.n_ctx = int(user_ctx) if user_ctx and int(user_ctx) > 0 else 0
        _target_batch = int(os.environ.get("ELI_TARGET_BATCH", "0") or "0")
        if _target_batch > 0:
            req.n_batch = _target_batch
        plan = load_plan.plan(req)
    except Exception:
        log.debug("load plan unavailable for the recommendation", exc_info=True)
        return False
    if plan is None or not plan.measured:      # an estimate is what the tuner below already makes
        return False
    rec.model_path = chosen["path"]
    rec.model_name = chosen["name"]
    rec.model_size_gb = chosen["size_gb"]
    rec.n_ctx = int(plan.n_ctx)
    rec.n_gpu_layers = int(plan.n_gpu_layers)
    rec.batch_size = int(plan.n_batch)
    rec.n_threads = int(plan.n_threads)
    rec.cache_type_k = plan.cache_type_k
    rec.cache_type_v = plan.cache_type_v
    rec.reasoning.append(f"Plan, as the model will load ({'measured by llama.cpp' if plan.measured else 'estimated'}): "
                         f"{plan.describe()}")
    rec.reasoning.extend(plan.notes)
    _finish_recommendation(rec, chosen, hw)
    return True


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
        settings["max_tokens"] = rec.max_tokens
        settings["temperature"] = rec.temperature
        settings["use_mmap"] = rec.use_mmap
        settings["use_mlock"] = rec.use_mlock
        settings["provider"] = rec.provider
        settings["cache_type_k"] = rec.cache_type_k
        settings["cache_type_v"] = rec.cache_type_v
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


# Hardware-profile authority: the profiler is the source of truth. At startup, settings above
# what recommend() would give here are re-applied. Only the runtime tune (n_ctx, n_gpu_layers,
# batch) changes, never the model; swap suggestions are a warning banner, never auto-applied.

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
        log.debug("suppressed exception", exc_info=True)
    try:
        # n_gpu_layers: -1 means every layer. Compare raw.
        s_layers = int(settings.get("n_gpu_layers", 0))
        r_layers = int(rec.n_gpu_layers)
        # every layer (-1) asked where the recommendation is a partial count is more than it found room for
        if r_layers > 0 and (s_layers < 0 or s_layers > r_layers):
            reasons.append(f"n_gpu_layers {describe_gpu_layers(s_layers)} > recommended {r_layers}")
    except Exception:
        log.debug("suppressed exception", exc_info=True)
    try:
        if int(settings.get("batch_size", 0)) > int(rec.batch_size):
            reasons.append(f"batch_size {settings.get('batch_size')} > recommended {rec.batch_size}")
    except Exception:
        log.debug("suppressed exception", exc_info=True)
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

    # If this process already has a GGUF loaded, live free_vram_mb is artificially small (the model
    # is eating its own budget) and gave n_gpu_layers -> 1. Predict free VRAM as if no chat model
    # were loaded: total minus the display server (~500MB) and KV cache.
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
        log.debug("suppressed exception", exc_info=True)

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
            log.debug("suppressed exception", exc_info=True)

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
