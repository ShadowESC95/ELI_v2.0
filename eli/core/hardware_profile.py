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

log = get_logger(__name__)
from typing import Any, Dict, List, Optional


# KV-cache overhead constants (matched against eli/gui/app.py — keep in sync)
_KV_BYTES_PER_TOKEN_PER_LAYER = 6_000
_CUDA_OVERHEAD_MB = 350

# Headroom left unallocated on the GPU, and the ONE default for it.
#
# This knob had two different defaults in four places: the startup dialog's
# spin box and the startup optimizer said 250, while the loader and
# gguf_inference said 700. The dialog exports its value into
# ELI_VRAM_RESERVE_MB, so the 250 always won — and 250 is on the wrong side of
# a cliff. Measured on a 2060 SUPER with 6,346MB free and a 4.68GB model at
# ctx=10384:
#
#     reserve=250MB -> "all 99 layers fit"   <- llama.cpp then REFUSED to
#                                               create the context
#     reserve=400MB -> reduce to 31 layers
#     reserve=700MB -> reduce to 29 layers   <- loads
#
# A 150MB swing flips the answer from 99 layers to 31, so at 250 the fit sits
# exactly on the boundary and whether it loads depends on fragmentation. It had
# been loading; on 2.1.98 it did not, the loader fell through to a static 4,096
# profile, and the whole session ran in a window smaller than its own prompt.
#
# 700MB is the value the loader already trusted. Anyone who wants the layers
# back can lower the spin box deliberately — that is what it is for; it just
# must not DEFAULT to the edge of what the driver will allocate.
DEFAULT_VRAM_RESERVE_MB = 700
# Integrated / unified-memory GPUs (Intel Iris Xe, AMD APU, Adreno) share RAM with
# the display stack but do not hit the same CUDA lazy-allocation cliff as discrete
# cards. Reserving 700MB on a ~1.4GB budget left zero room for even partial layer
# offload — every iGPU machine reported gpu_layers=0 despite a usable budget.
DEFAULT_IGPU_VRAM_RESERVE_MB = 400


def vram_reserve_mb(*, gpu_integrated: Optional[bool] = None) -> int:
    """The VRAM headroom to keep free, honouring ELI_VRAM_RESERVE_MB.

    Single source of truth: the startup spin box, the startup optimizer and both
    loader paths all resolve through here, so they cannot disagree again.

    Integrated GPUs use a lower default reserve unless ELI_IGPU_VRAM_RESERVE_MB or
    ELI_VRAM_RESERVE_MB overrides it.
    """
    import os as _os
    raw = (_os.environ.get("ELI_VRAM_RESERVE_MB") or "").strip()
    try:
        value = int(raw) if raw else DEFAULT_VRAM_RESERVE_MB
    except ValueError:
        value = DEFAULT_VRAM_RESERVE_MB
    if value <= 0:
        value = DEFAULT_VRAM_RESERVE_MB

    if gpu_integrated is None:
        try:
            gpu_integrated = bool(getattr(detect_hardware(), "gpu_integrated", False))
        except Exception:
            gpu_integrated = False

    if gpu_integrated and not raw:
        igpu_raw = (_os.environ.get("ELI_IGPU_VRAM_RESERVE_MB") or "").strip()
        try:
            igpu_val = int(igpu_raw) if igpu_raw else DEFAULT_IGPU_VRAM_RESERVE_MB
        except ValueError:
            igpu_val = DEFAULT_IGPU_VRAM_RESERVE_MB
        return min(value, igpu_val) if igpu_val > 0 else min(value, DEFAULT_IGPU_VRAM_RESERVE_MB)
    return value


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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cpu_threads": self.cpu_threads,
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
            # CoT spends tokens on hidden reasoning BEFORE the visible answer,
            # so it needs more budget than the base, not less — below ~1536 the
            # answer truncates mid-reasoning. Floor there whenever ctx allows
            # (still ctx-derived: tiny-ctx machines keep a proportional cap).
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


def _windows_gpus() -> List[tuple]:
    """[(name, vram_mb)] for every adapter on Windows, any vendor.

    Uses CIM for the names and the driver registry for VRAM: WMI's AdapterRAM
    is a signed 32-bit value and saturates at 4 GB, so an 8 GB card reports
    4095 MB and the loader then under-provisions it. qwMemorySize in
    HardwareInformation is 64-bit and correct.
    """
    if os.name != "nt":
        return []
    ps = shutil.which("powershell") or shutil.which("pwsh")
    if not ps:
        return []
    script = (
        "$ErrorActionPreference='SilentlyContinue';"
        "Get-CimInstance Win32_VideoController | ForEach-Object {"
        "  $n=$_.Name; $ram=0;"
        "  $k=Get-ItemProperty -Path ('HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Class\\'"
        "    +'{4d36e968-e325-11ce-bfc1-08002be10318}\\*') |"
        "    Where-Object { $_.'HardwareInformation.qwMemorySize' -and $_.DriverDesc -eq $n } |"
        "    Select-Object -First 1;"
        "  if($k){ $ram=[int64]$k.'HardwareInformation.qwMemorySize' }"
        "  elseif($_.AdapterRAM){ $ram=[int64]$_.AdapterRAM }"
        "  '{0}|{1}' -f $n, $ram }"
    )
    try:
        out = subprocess.check_output([ps, "-NoProfile", "-Command", script],
                                      stderr=subprocess.DEVNULL, timeout=25)
        text = out.decode("utf-8", "replace")
    except Exception:
        log.debug("windows GPU enumeration failed", exc_info=True)
        return []
    gpus = []
    for line in text.splitlines():
        if "|" not in line:
            continue
        name, _, ram = line.rpartition("|")
        name = name.strip()
        if not name or "microsoft basic display" in name.lower():
            continue
        try:
            mb = int(int(ram.strip()) / (1024 * 1024))
        except Exception:
            mb = 0
        gpus.append((name, mb))
    return gpus


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


_PCI_VENDOR_INTEL = "0x8086"
_PCI_VENDOR_QUALCOMM = "0x5143"
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
    """Shared-memory budget for iGPU / APU / unified-memory systems."""
    frac = ram_budget_fraction()
    # Budget from AVAILABLE RAM (same basis as cpu_ram_budget_mb), not installed RAM.
    avail_gb = max(float(available_ram_gb or 0), 1.0)
    free_mb = int(max(512, avail_gb * 1024.0 * frac))
    total_mb = int(min(8192, max(2048, free_mb)))
    free_mb = min(free_mb, total_mb)
    return free_mb, total_mb


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


def _lspci_name_for_pci_addr(addr: str) -> str:
    if not addr or not shutil.which("lspci"):
        return ""
    try:
        proc = subprocess.run(
            ["lspci", "-s", addr, "-nn"],
            capture_output=True, text=True, timeout=5,
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
    seen: set[str] = set()
    for vendor_file in Path("/sys/class/drm").glob("card[0-9]*/device/vendor"):
        try:
            if vendor_file.read_text().strip().lower() != _PCI_VENDOR_INTEL:
                continue
            dev = vendor_file.parent
            card = vendor_file.parents[1].name
            if card in seen:
                continue
            seen.add(card)
            is_arc = _intel_pci_device_is_discrete_arc(dev)
            name = _lspci_name_for_pci_addr(_pci_addr_from_drm_device(dev))
            if not name:
                name = "Intel Arc" if is_arc else "Intel integrated graphics (Iris Xe / UHD)"
            out.append((name, is_arc))
        except Exception:
            continue
    return out


def _linux_qualcomm_display_adapters() -> List[str]:
    """Return human-readable names for Qualcomm Adreno DRM adapters (Linux ARM)."""
    out: List[str] = []
    seen: set[str] = set()
    for vendor_file in Path("/sys/class/drm").glob("card[0-9]*/device/vendor"):
        try:
            if vendor_file.read_text().strip().lower() != _PCI_VENDOR_QUALCOMM:
                continue
            dev = vendor_file.parent
            card = vendor_file.parents[1].name
            if card in seen:
                continue
            seen.add(card)
            name = _lspci_name_for_pci_addr(_pci_addr_from_drm_device(dev))
            if not name:
                name = "Qualcomm Adreno (Snapdragon)"
            out.append(name)
        except Exception:
            continue
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
    return bool(hw.has_gpu and hw.free_vram_mb > 0 and _llama_gpu_offload_available())


def cpu_ram_budget_mb(available_ram_gb: float, *, fraction: float | None = None) -> int:
    """RAM budget (MB) for cpu_ram_fit — same shape as free VRAM for smart_fit_config."""
    frac = ram_budget_fraction() if fraction is None else float(fraction)
    return int(max(512.0, float(available_ram_gb) * 1024.0 * frac))


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
        user_ctx=max(2048, int(user_ctx)),
        user_batch=max(min_batch, int(user_batch)),
        reserve_mb=512,
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
            log.debug("suppressed exception", exc_info=True)

    # FREE VRAM — critical for GPU layer counts. Display server, browser,
    # games, etc all consume VRAM before ELI launches. Total VRAM
    # oversubscribes and OOMs.
    _smi = nvidia_smi_path()
    if _smi:
        try:
            proc = subprocess.run(
                [_smi,
                 "--query-gpu=memory.free,memory.total,name",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=15,
            )
            if proc.returncode == 0:
                out = (proc.stdout or "").strip().splitlines()
            else:
                out = []
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
                hw.gpu_vendor = "nvidia"
        except Exception:
            log.debug("nvidia-smi query unavailable", exc_info=True)

    # NVIDIA driver-loaded fallback — if nvidia-smi is missing or its query failed
    # (a broken/partial userspace, an Optimus card the tool couldn't read) but the
    # kernel driver is clearly loaded, still report the GPU so the smart loader and
    # the GPU pack engage. ``_nvidia_driver_loaded`` reads kernel-provided signals
    # that are identical on every distro. VRAM isn't exposed without nvidia-smi, so
    # use a conservative estimate the loader's reduce-to-fit corrects.
    if not hw.has_gpu and sys.platform.startswith("linux") and _nvidia_driver_loaded():
        hw.total_vram_mb = 4096       # conservative; loader refines / OOM-falls-back
        hw.free_vram_mb = int(hw.total_vram_mb * 0.85)
        hw.gpu_name = "NVIDIA GPU"
        hw.vram_gb = hw.free_vram_mb / 1024.0
        hw.has_gpu = True
        hw.gpu_vendor = "nvidia"

    # Windows / macOS fallback. This block used to be Linux-only -- the whole
    # fallback was gated on sys.platform.startswith("linux") -- so on Windows a
    # machine whose nvidia-smi was simply not on PATH reported NO GPU AT ALL and
    # loaded with 0 offloaded layers. The kernel-signal rewrite made Linux robust
    # and left the other two platforms with nothing behind nvidia-smi.
    if not hw.has_gpu:
        _native = _windows_gpus() or _macos_gpus()
        if _native:
            # Prefer a discrete card over an integrated one when both exist.
            def _rank(g):
                n = g[0].lower()
                disc = any(k in n for k in ("nvidia", "geforce", "rtx", "gtx", "quadro",
                                            "tesla", "radeon", "rx ", "arc"))
                return (disc, g[1])
            name, vram_mb = sorted(_native, key=_rank, reverse=True)[0]
            hw.gpu_name = name
            name_l = name.lower()
            if any(k in name_l for k in ("nvidia", "geforce", "rtx", "gtx", "quadro", "tesla")):
                hw.gpu_vendor = "nvidia"
            elif any(k in name_l for k in ("amd", "radeon", "rx ", "ati", "vega")):
                hw.gpu_vendor = "amd"
                if _is_integrated_gpu_name(name, "amd"):
                    hw.gpu_integrated = True
                    hw.vulkan_available = _vulkan_loader_present()
            elif "intel" in name_l or "iris" in name_l or "uhd" in name_l:
                hw.gpu_vendor = "intel"
                if _is_integrated_gpu_name(name, "intel"):
                    hw.gpu_integrated = True
                    hw.vulkan_available = _vulkan_loader_present()
            elif any(k in name_l for k in ("qualcomm", "adreno", "snapdragon")):
                hw.gpu_vendor = "qualcomm"
                hw.gpu_integrated = True
                hw.vulkan_available = _vulkan_loader_present()
            elif sys.platform == "darwin":
                hw.gpu_vendor = "apple"
                hw.gpu_integrated = True
            if vram_mb > 0 and not hw.gpu_integrated:
                hw.total_vram_mb = vram_mb
                # No free-VRAM API here, so assume the desktop already holds
                # some. The smart loader's reduce-to-fit corrects downward on
                # OOM; over-reporting is the only unsafe direction.
                hw.free_vram_mb = int(vram_mb * 0.80)
            elif hw.gpu_integrated or sys.platform == "darwin":
                # iGPU / APU / Apple unified memory share system RAM with the GPU.
                free_mb, total_mb = _estimate_integrated_vram_mb(hw.ram_gb, hw.available_ram_gb)
                hw.total_vram_mb = total_mb
                hw.free_vram_mb = free_mb
            else:
                hw.total_vram_mb = 4096
                hw.free_vram_mb = int(hw.total_vram_mb * 0.85)
            hw.vram_gb = hw.free_vram_mb / 1024.0
            hw.has_gpu = True
            log.info("[HW] GPU detected without nvidia-smi: %s (%d MB usable)",
                     hw.gpu_name, hw.free_vram_mb)

    # AMD ROCm fallback — nvidia-smi doesn't exist on AMD GPUs, so the block above finds
    # nothing there. Read free/total VRAM from rocm-smi so the smart loader can size GPU
    # layers on AMD too (mirrors the nvidia path; llama.cpp + hipBLAS splits across HIP
    # devices the same way). Non-fatal: if rocm-smi is absent it falls through to CPU.
    if not hw.has_gpu:
        try:
            import json as _json
            import shutil as _shutil
            proc = None
            if _shutil.which("rocm-smi"):
                proc = subprocess.run(
                    ["rocm-smi", "--showmeminfo", "vram", "--json"],
                    capture_output=True, text=True, timeout=5,
                )
            _out = (proc.stdout or "").strip() if proc and proc.returncode == 0 else ""
            _data = _json.loads(_out) if _out else {}

            def _amd_mb(info: dict, must: tuple, mustnot: tuple = ()) -> int:
                # rocm-smi field names drift across versions ("VRAM Total Memory (B)" etc.),
                # so match by keyword instead of an exact key.
                for k, v in info.items():
                    kl = str(k).lower()
                    if all(n in kl for n in must) and not any(n in kl for n in mustnot):
                        try:
                            return int(v)
                        except Exception:
                            continue
                return 0

            free_sum = total_sum = cards = 0
            for _card, _info in _data.items():
                if not isinstance(_info, dict):
                    continue
                tot = _amd_mb(_info, ("vram", "total", "memory"), mustnot=("used",))
                used = _amd_mb(_info, ("vram", "used", "memory"))
                if tot <= 0:
                    continue
                total_sum += tot // (1024 * 1024)
                free_sum += max(0, tot - used) // (1024 * 1024)
                cards += 1
            if total_sum > 0:
                hw.free_vram_mb = free_sum
                hw.total_vram_mb = total_sum
                hw.gpu_name = "AMD GPU" + (f" ×{cards}" if cards > 1 else "")
                hw.vram_gb = hw.free_vram_mb / 1024.0
                hw.has_gpu = True
                hw.gpu_vendor = "amd"
        except Exception:
            log.debug("suppressed exception", exc_info=True)

    # AMD without ROCm (the common desktop case, and what the Vulkan GPU pack
    # targets) — rocm-smi rarely exists there. Read VRAM from the stock
    # amdgpu driver's sysfs so AMD flows through the SAME HardwareProfile
    # fields (and therefore the same smart-fit layer allocation) as NVIDIA.
    if not hw.has_gpu and sys.platform.startswith("linux"):
        try:
            free_sum = total_sum = cards = 0
            for vendor_file in Path("/sys/class/drm").glob("card[0-9]*/device/vendor"):
                try:
                    if vendor_file.read_text().strip().lower() != "0x1002":  # AMD
                        continue
                    dev = vendor_file.parent
                    total = int((dev / "mem_info_vram_total").read_text().strip())
                    used = int((dev / "mem_info_vram_used").read_text().strip())
                except Exception:
                    continue
                if total <= 0:
                    continue
                total_sum += total // (1024 * 1024)
                free_sum += max(0, total - used) // (1024 * 1024)
                cards += 1
            if total_sum > 0:
                hw.free_vram_mb = free_sum
                hw.total_vram_mb = total_sum
                hw.gpu_name = "AMD GPU (amdgpu)" + (f" ×{cards}" if cards > 1 else "")
                hw.vram_gb = hw.free_vram_mb / 1024.0
                hw.has_gpu = True
                hw.gpu_vendor = "amd"
        except Exception:
            log.debug("suppressed exception", exc_info=True)

    # Discrete Intel Arc (Linux) — same HardwareProfile pipeline as NVIDIA/AMD so
    # the smart loader and the Vulkan GPU pack see it. Only DISCRETE Arc (the newer
    # `xe` driver, or an Arc-family PCI device id) — an Intel iGPU (Iris/UHD) is left
    # on CPU because Vulkan offload to shared memory rarely beats CPU. Intel exposes
    # no stable free-VRAM sysfs, so total is a conservative estimate the loader's
    # reduce-to-fit corrects at load time.
    if not hw.has_gpu and sys.platform.startswith("linux"):
        try:
            _INTEL = _PCI_VENDOR_INTEL
            for dev in Path("/sys/class/drm").glob("card*/device"):
                try:
                    if (dev / "vendor").read_text().strip().lower() != _INTEL:
                        continue
                    if not _intel_pci_device_is_discrete_arc(dev):
                        continue
                    hw.total_vram_mb = 8192       # conservative Arc estimate; loader refines
                    hw.free_vram_mb = int(hw.total_vram_mb * 0.85)
                    hw.gpu_name = "Intel Arc"
                    hw.vram_gb = hw.free_vram_mb / 1024.0
                    hw.has_gpu = True
                    hw.gpu_vendor = "intel"
                    break
                except Exception:
                    continue
        except Exception:
            log.debug("suppressed exception", exc_info=True)

    # AMD (and discrete Intel Arc) on Windows — no CLI ships with the driver; VRAM
    # total + name live in the display-class registry keys. Free VRAM is not
    # exposed, so estimate conservatively (85% of total on an idle desktop); the
    # loader's reduce-to-fit attempts and live tuner correct any optimism at load
    # time. Intel iGPUs (Iris/UHD) are skipped — only Arc is offered a GPU pack.
    if not hw.has_gpu and sys.platform == "win32":
        try:
            import winreg
            base = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as cls:
                i = 0
                while True:
                    try:
                        sub = winreg.EnumKey(cls, i)
                    except OSError:
                        break
                    i += 1
                    if not sub.isdigit():
                        continue
                    try:
                        with winreg.OpenKey(cls, sub) as k:
                            desc = str(winreg.QueryValueEx(k, "DriverDesc")[0])
                            _dl = desc.lower()
                            if not (("amd" in _dl or "radeon" in _dl) or "arc" in _dl):
                                continue
                            qw = int(winreg.QueryValueEx(k, "HardwareInformation.qwMemorySize")[0])
                    except OSError:
                        continue
                    if qw > 0:
                        hw.total_vram_mb = qw // (1024 * 1024)
                        hw.free_vram_mb = int(hw.total_vram_mb * 0.85)
                        hw.gpu_name = desc
                        hw.vram_gb = hw.free_vram_mb / 1024.0
                        hw.has_gpu = True
                        hw.gpu_vendor = "amd" if ("amd" in _dl or "radeon" in _dl) else "intel"
                        break
        except Exception:
            log.debug("suppressed exception", exc_info=True)

    # Integrated graphics (Intel iGPU, AMD APU) — shared system RAM, no nvidia-smi.
    if not hw.has_gpu and sys.platform.startswith("linux"):
        try:
            integrated = [name for name, is_arc in _linux_intel_display_adapters() if not is_arc]
            if integrated:
                _apply_integrated_gpu_profile(hw, integrated[0], "intel")
                log.info(
                    "[HW] Intel iGPU detected: %s (~%d MB shared-memory budget, Vulkan=%s)",
                    hw.gpu_name, hw.free_vram_mb, hw.vulkan_available,
                )
        except Exception:
            log.debug("suppressed exception", exc_info=True)
    if not hw.has_gpu and sys.platform.startswith("linux"):
        try:
            _AMD = "0x1002"
            for vendor_file in Path("/sys/class/drm").glob("card[0-9]*/device/vendor"):
                if vendor_file.read_text().strip().lower() != _AMD:
                    continue
                dev = vendor_file.parent
                dedicated = 0
                try:
                    dedicated = int((dev / "mem_info_vram_total").read_text().strip())
                except Exception:
                    pass
                if dedicated > 64 * 1024 * 1024:
                    continue
                name = _lspci_name_for_pci_addr(_pci_addr_from_drm_device(dev))
                if not name:
                    name = "AMD integrated graphics (APU)"
                _apply_integrated_gpu_profile(hw, name, "amd")
                log.info(
                    "[HW] AMD iGPU/APU detected: %s (~%d MB shared-memory budget, Vulkan=%s)",
                    hw.gpu_name, hw.free_vram_mb, hw.vulkan_available,
                )
                break
        except Exception:
            log.debug("suppressed exception", exc_info=True)

    # Qualcomm Adreno (Snapdragon X Elite laptops, Linux ARM) — unified memory.
    if not hw.has_gpu and sys.platform.startswith("linux"):
        try:
            qualcomm = _linux_qualcomm_display_adapters()
            if qualcomm:
                _apply_integrated_gpu_profile(hw, qualcomm[0], "qualcomm")
                log.info(
                    "[HW] Qualcomm Adreno detected: %s (~%d MB shared-memory budget, Vulkan=%s)",
                    hw.gpu_name, hw.free_vram_mb, hw.vulkan_available,
                )
        except Exception:
            log.debug("suppressed exception", exc_info=True)

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
                          kv_quantized: bool = False,
                          model_path: Optional[str] = None) -> int:
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
    total_layers = layers_for_model(model_path, size_gb)
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


def _fit_needed_mb(
    model_size_gb: float,
    total_layers: int,
    ctx: int,
    layers: int,
    batch: int,
    *,
    kv_quantized: bool,
) -> float:
    """VRAM bytes for GPU-resident weights + KV + compute graph."""
    mb_per_layer = (model_size_gb * 1024.0) / max(1, total_layers + 2)
    gpu_model = mb_per_layer * layers
    kv = _kv_cache_mb(ctx, total_layers, quant=kv_quantized)
    compute = _compute_graph_reserve_mb(ctx, batch)
    return gpu_model + kv + compute + _CUDA_OVERHEAD_MB


def _fit_layers_real(layers: int, total_layers: int) -> int:
    if int(layers) >= 99:
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
) -> float:
    """System RAM for CPU-resident weights and KV when running CPU-only."""
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
) -> tuple[int, int, int]:
    """Balanced: shed GPU layers → batch → ctx (context preserved as long as possible)."""
    ctx = max(min_ctx, int(user_ctx))
    _target_ctx = int(ctx)
    batch = max(min_batch, int(user_batch))
    layers = total

    if budget <= 0:
        return ctx, 0, batch

    floor = max(0, int(total * min_gpu_fraction))
    step = max(1, total // 10)

    while layers > floor and _fit_needed_mb(
            model_size_gb, total, ctx, layers, batch, kv_quantized=kv_quantized) > budget:
        layers = max(floor, layers - step)
    while batch > min_batch and _fit_needed_mb(
            model_size_gb, total, ctx, layers, batch, kv_quantized=kv_quantized) > budget:
        batch = max(min_batch, batch // 2)
    while layers > 0 and _fit_needed_mb(
            model_size_gb, total, ctx, layers, batch, kv_quantized=kv_quantized) > budget:
        layers = max(0, layers - step)
    while ctx > min_ctx and _fit_needed_mb(
            model_size_gb, total, ctx, layers, batch, kv_quantized=kv_quantized) > budget:
        ctx = max(min_ctx, ctx - ctx_grain)

    while layers < total and _fit_needed_mb(
            model_size_gb, total, ctx, layers + 1, batch, kv_quantized=kv_quantized) <= budget:
        layers += 1

    if layers <= 0 and budget > 0 and ctx < _target_ctx:
        probe_layers = 0
        while probe_layers < total and _fit_needed_mb(
                model_size_gb, total, min_ctx, probe_layers + 1, min_batch,
                kv_quantized=kv_quantized) <= budget:
            probe_layers += 1
        if probe_layers > 0:
            ctx, batch, layers = min_ctx, min_batch, probe_layers

    n_layers = 99 if layers >= total else layers
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
) -> tuple[int, int, int]:
    """Max GPU: shrink ctx/batch before shedding layers; pack VRAM with layers."""
    ctx = max(min_ctx, int(user_ctx))
    batch = max(min_batch, int(user_batch))
    layers = total

    if budget <= 0:
        return ctx, 0, batch

    step = max(1, total // 10)

    while layers == total and _fit_needed_mb(
            model_size_gb, total, ctx, layers, batch, kv_quantized=kv_quantized) > budget:
        if ctx > min_ctx:
            ctx = max(min_ctx, ctx - ctx_grain)
        elif batch > min_batch:
            batch = max(min_batch, batch // 2)
        else:
            break

    while layers > 0 and _fit_needed_mb(
            model_size_gb, total, ctx, layers, batch, kv_quantized=kv_quantized) > budget:
        layers = max(0, layers - step)

    while layers < total and _fit_needed_mb(
            model_size_gb, total, ctx, layers + 1, batch, kv_quantized=kv_quantized) <= budget:
        layers += 1

    n_layers = 99 if layers >= total else layers
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
) -> tuple[int, int, int]:
    """Max context: preserve ctx via CPU/RAM spill; add GPU layers only if ctx stays."""
    ctx = max(min_ctx, int(user_ctx))
    batch = max(min_batch, int(user_batch))
    layers = total

    if budget <= 0:
        return ctx, 0, batch

    if _fit_needed_mb(model_size_gb, total, ctx, layers, batch, kv_quantized=kv_quantized) > budget:
        layers = 0
        while batch > min_batch and _fit_needed_mb(
                model_size_gb, total, ctx, 0, batch, kv_quantized=kv_quantized) > budget:
            batch = max(min_batch, batch // 2)
        while ctx > min_ctx and _fit_needed_mb(
                model_size_gb, total, ctx, 0, batch, kv_quantized=kv_quantized) > budget:
            ctx = max(min_ctx, ctx - ctx_grain)

    while layers < total and _fit_needed_mb(
            model_size_gb, total, ctx, layers + 1, batch, kv_quantized=kv_quantized) <= budget:
        layers += 1

    n_layers = 99 if layers >= total else layers
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
) -> tuple[int, int, int]:
    """Joint planner: CPU spill from partial offload must fit the RAM slider budget."""
    if ram_budget_mb <= 0:
        return ctx, layers, batch

    priority = normalize_fit_priority(priority)
    step = max(1, total // 10)

    for _ in range(128):
        real = _fit_layers_real(layers, total)
        spill = _estimate_cpu_spill_mb(
            model_size_gb, total, real, ctx, batch, kv_quantized=kv_quantized)
        if spill <= ram_budget_mb:
            break

        if real < total and _fit_needed_mb(
                model_size_gb, total, ctx, real + 1, batch,
                kv_quantized=kv_quantized) <= vram_budget:
            real += 1
            layers = 99 if real >= total else real
            continue

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
        elif real > 0:
            real = max(0, real - step)
            layers = 99 if real >= total else real
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
                        kv_quantized=kv_quantized) > vram_budget:
                    break
                spill = _estimate_cpu_spill_mb(
                    model_size_gb, total, real, probe, batch, kv_quantized=kv_quantized)
                if spill > ram_budget_mb:
                    break
                ctx = probe

    n_layers = 99 if _fit_layers_real(layers, total) >= total else _fit_layers_real(layers, total)
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
) -> tuple[int, int, int]:
    """VRAM-only smart loader fit (backward compatible).

    Dispatches to balanced / max_gpu / max_ctx reduction order. For joint
    VRAM+RAM planning on discrete GPUs, use ``unified_fit_config``.
    """
    total = int(total_layers or layers_for_model(model_path, model_size_gb))
    budget = max(0, int(free_vram_mb) - int(reserve_mb))
    priority = normalize_fit_priority(fit_priority or FIT_PRIORITY_BALANCED)
    common = dict(
        user_ctx=user_ctx,
        user_batch=user_batch,
        kv_quantized=kv_quantized,
        total=total,
        ctx_grain=ctx_grain,
        min_ctx=min_ctx,
        min_batch=min_batch,
    )
    if priority == FIT_PRIORITY_MAX_GPU:
        return _smart_fit_max_gpu(model_size_gb, budget, **common)
    if priority == FIT_PRIORITY_MAX_CTX:
        return _smart_fit_max_ctx(model_size_gb, budget, **common)
    return _smart_fit_balanced(
        model_size_gb, budget, min_gpu_fraction=min_gpu_fraction, **common)


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
) -> tuple[int, int, int]:
    """Joint VRAM + RAM planner for every OS and GPU class.

    • Discrete GPU — sizes layers from free VRAM, then verifies CPU spill fits
      the RAM budget (startup slider). Raising RAM % allows more CPU spill so
      mid-tier cards can supercharge context without OOM.
    • Integrated / CPU-only — budgets from available RAM (same math as before).
    """
    total = int(total_layers or layers_for_model(model_path, model_size_gb))
    priority = (
        normalize_fit_priority(fit_priority_mode)
        if fit_priority_mode is not None
        else fit_priority()
    )
    ram_budget_mb = cpu_ram_budget_mb(available_ram_gb)

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
    )


def recommend(hw: Optional[HardwareProfile] = None,
              models: Optional[List[Dict[str, Any]]] = None,
              user_ctx: Optional[int] = None) -> ModelRecommendation:
    """Generate optimal model + parameter recommendation for this hardware.

    Picks the largest model that fits within free VRAM (after KV cache +
    CUDA overhead) OR within available RAM if no GPU.

    ``user_ctx`` (when >= 2048) is the user's EXPLICITLY chosen context window —
    it anchors n_ctx instead of the DEFAULT_N_CTX target, and the VRAM refinement
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

    rec.n_threads = max(1, hw.cpu_threads - 2)
    rec.reasoning.append(
        f"CPU: {hw.cpu_threads} threads → using {rec.n_threads}"
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
        rec.reasoning.append("No GGUF models found. Consider Ollama.")
        rec.provider = "ollama"
        rec.n_ctx = 8192
        rec.batch_size = 512
        return rec

    # KV-cache quantization decision. q4_0 K + q4_0 V cuts KV memory ~75%
    # with negligible quality loss for chat workloads. Enable on small GPUs
    # and on CPU-only hosts with <=16 GB RAM (integrated-GPU laptops).
    rec.cache_type_k = "q4_0" if (
        (hw.has_gpu and hw.total_vram_mb < 12000)
        or (not use_gpu_layers and hw.ram_gb <= 16)
    ) else ""
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
    try:
        from eli.core.runtime_settings import DEFAULT_N_CTX as _DEF_CTX
    except Exception:
        _DEF_CTX = 12288
    if user_ctx and int(user_ctx) >= 2048:
        rec.n_ctx = max(2048, (int(user_ctx) // _ctx_grain) * _ctx_grain)
        _ctx_note = "user-pinned — reduced to fit only if memory is tight"
    else:
        rec.n_ctx = int(_DEF_CTX)
        _ctx_note = f"default {_DEF_CTX} — reduced to fit if memory is tight"
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
            layers = _gpu_layers_for_model(
                m["size_gb"], hw.free_vram_mb, rec.n_ctx, kv_quantized=kv_q,
                model_path=m["path"],
            )
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
        chosen_layers = (_gpu_layers_for_model(
            chosen["size_gb"], hw.free_vram_mb, rec.n_ctx, kv_quantized=kv_q,
            model_path=chosen["path"],
        ) if use_gpu_layers else 0)
        if use_gpu_layers and hw.gpu_integrated and chosen_layers > 0:
            chosen_layers = min(
                chosen_layers,
                max(4, int(layers_for_model(chosen["path"], chosen["size_gb"]) * 0.25)),
            )
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

    # ONE fit, not two. This recommendation is shown to the operator and stored
    # as the hw_profile_* fallback, so it must predict what the loader will do —
    # and it did the opposite. Three blocks here picked layers first and then cut
    # CONTEXT to pay for them ("n_ctx set 12288 -> 8192", "n_gpu_layers adjusted
    # 28->30 after ctx settled", "n_ctx-> to reach 10 GPU layers"), while
    # smart_fit_config — the function the load ladder actually runs — keeps the
    # context and sheds LAYERS, reducing ctx only as a last resort.
    #
    # Same machine, same model, one second apart, the two disagreed in the
    # Hardware Tuning tab: the tuner reported ctx=8192 gpu_layers=30 while the
    # load selected ctx=12288 gpu_layers=27.
    #
    # smart_fit_config is the authority because it is what runs. Calling it here
    # means the recommendation is a prediction of the load rather than a second
    # opinion about it.
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
    if not _fit_batch_in:
        _fit_batch_in = max(128, (max(1, hw.cpu_threads) - 2) * 32)

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
        _fit_layers_real = _total_layers_est if int(_fit_layers) >= 99 else int(_fit_layers)
        _old_ctx, _old_layers = rec.n_ctx, rec.n_gpu_layers
        rec.n_ctx = int(_fit_ctx)
        rec.n_gpu_layers = _fit_layers_real
        rec.batch_size = max(rec.batch_size, int(_fit_batch))
        chosen_layers = _fit_layers_real
        _fp = fit_priority()
        rec.reasoning.append(
            f"Fit ({_fp}, joint VRAM+RAM): ctx={rec.n_ctx} "
            f"gpu_layers={rec.n_gpu_layers} batch={rec.batch_size} "
            f"for {hw.free_vram_mb:.0f}MB free VRAM + "
            f"{cpu_ram_budget_mb(hw.available_ram_gb)}MB RAM spill budget "
            f"(reserve {vram_reserve_mb()}MB, kv={'q4_0' if kv_q else 'fp16'}) "
            f"— was ctx={_old_ctx} gpu_layers={_old_layers} before the fit"
        )
    else:
        try:
            from eli.core.startup_hardware_optimizer import cpu_ctx_ceiling_from_ram as _ram_ceil
            from eli.core.startup_hardware_optimizer import train_ctx_for_model as _train_ctx
            _train = int(_train_ctx(chosen["path"]) or 0)
            _ceil = int(_ram_ceil(chosen["size_gb"], _train))
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
            f"(total {hw.ram_gb:.1f}GB, kv={'q4_0' if kv_q else 'fp16'}) "
            f"— was ctx={_old_ctx} before the fit"
        )
        if hw.has_gpu and not _backend_ready:
            _igpu_kind = integrated_gpu_label(hw.gpu_name, hw.gpu_vendor)
            rec.reasoning.append(
                f"GPU pack not active — {_igpu_kind or hw.gpu_name} will stay CPU-only "
                f"until ELI --install-gpu-pack is run (optional Vulkan offload)"
            )

    total_layers = layers_for_model(chosen["path"], chosen["size_gb"])
    _full_offload = chosen_layers >= total_layers  # 99 >= actual layer count → all layers on GPU
    if _full_offload:
        rec.reasoning.append(
            f"Model: {chosen['name']} ({chosen['size_gb']:.2f}GB) — "
            f"all layers on GPU (free VRAM sufficient)"
        )
    elif chosen_layers > 0:
        # Report the KV size actually being BUDGETED, which means honouring kv_q —
        # every fit call above already passes it. This line did not, so on a card
        # using q4_0 it printed the fp16 figure: 1901MB where the loader had
        # reserved 475MB, four lines under "KV cache: q4_0 (4x more ctx for the same
        # VRAM)". Overstating KV fourfold makes context look like the lever for
        # winning back GPU layers when it is nearly the weakest one — on a 5GB/32
        # layer model at q4_0, cutting 1900 tokens frees 87MB against a 161MB layer,
        # i.e. half a layer, while the panel implied roughly two.
        rec.reasoning.append(
            f"Model: {chosen['name']} ({chosen['size_gb']:.2f}GB) — "
            f"{chosen_layers}/{total_layers} layers on GPU "
            f"(KV {_kv_cache_mb(rec.n_ctx, total_layers, quant=kv_q):.0f}MB "
            f"{'q4_0' if kv_q else 'fp16'} + "
            f"{_CUDA_OVERHEAD_MB}MB CUDA overhead, "
            f"~{_kv_cache_mb(1024, total_layers, quant=kv_q):.0f}MB per 1k ctx)"
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

    # Adreno Vulkan in llama.cpp is unstable above batch 32 on Snapdragon laptops.
    if hw.gpu_vendor == "qualcomm" and chosen_layers > 0 and rec.batch_size > 32:
        rec.reasoning.append(f"batch capped {rec.batch_size}→32 — Adreno Vulkan stability limit")
        rec.batch_size = 32

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
        f"(ctx={rec.n_ctx}, max_tokens_ref={_max_for_derivation}); re-derived at load "
        f"time from the ctx actually loaded, which may be higher than this estimate"
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
        # eli_pro_audio_gui_v2_0.py reads artifacts/runtime_hardware_profile.json
        # (keys: n_ctx, n_gpu_layers, batch_size) as its hw-profile fallback.
        # Without this write the GUI would show stale values from a previous
        # optimizer run, making it look like the profile wasn't updated.
        try:
            import json as _json
            from eli.core.paths import artifacts_dir as _artifacts_dir
            _art_path = _artifacts_dir() / "runtime_hardware_profile.json"
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
        log.debug("suppressed exception", exc_info=True)
    try:
        # n_gpu_layers: -1 / 99 / 9999 sentinels mean "all layers". Compare raw.
        s_layers = int(settings.get("n_gpu_layers", 0))
        r_layers = int(rec.n_gpu_layers)
        # Treat 99+ (full offload sentinel) as a legitimate ceiling on either side.
        if 0 < r_layers < 99 and s_layers > r_layers:
            reasons.append(f"n_gpu_layers {s_layers} > recommended {r_layers}")
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
