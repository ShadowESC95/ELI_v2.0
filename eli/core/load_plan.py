"""What a model loads with on this machine, and where each part of it goes, measured before it loads.

llama.cpp can simulate a load (`no_alloc`, llama-cpp-python 0.3.35 and later): it builds the model and a
context the way a real load would and, without allocating anything, logs which device each layer and
each cache goes to and how large every compute buffer is. The planner asks it about the operator's
settings and, when they don't fit the memory each GPU has free now, about smaller ones in the order the
fit profile gives — Balanced: GPU layers, then batch, then context; Max GPU: context first; Max context:
layers to the processor first — and keeps the largest that fits every device.

Several GPUs: the layers are shared out so each card keeps the same share of what it can hold after its
own compute buffers and its headroom (tensor_split), rather than one card being filled to the brim while
the other has room.

Headroom: what llama.cpp takes on a card after the load, as it works through the first prompts (its
temporary buffers), measured on this machine and remembered per card and model (`watch_headroom`,
`note_headroom`). Until a card has been measured, the plan leaves llama.cpp's own compute-buffer figure
for it free. A value the operator sets (ELI_VRAM_RESERVE_MB) is used as given. Measured on two RTX 2060
SUPER: 28-82 MB after an 8,000-token prompt, where a fixed 700 MB used to be held back on every card.
Flash attention is used wherever llama.cpp says this model and device support it.

A mixture-of-experts model that doesn't fit keeps the experts of its first layers in RAM: as few of them
as the GPUs need. On the processor alone, the context is the largest that fits the RAM budget by the
same simulation.

An older llama.cpp has no simulation: the same search runs on the file's own tensor sizes and the KV size
it records (eli/core/gguf_sizes.py) with the compute buffers estimated, and the plan says it is an
estimate.
"""
from __future__ import annotations

import ctypes
import math
import os
import re
import sys
import threading
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from eli.utils.log import get_logger

log = get_logger(__name__)

MIB = 1024 * 1024
_TYPE_GPU, _TYPE_IGPU = 1, 2          # enum ggml_backend_dev_type
# Layer split only: a row split spreads every layer over the GPUs, which the log does not show per device.
_SPLIT_MODES = {"none": 0, "layer": 1}


# ── devices ──────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Device:
    index: int            # position in llama.cpp's device list for a model: its place in tensor_split
    name: str             # "CUDA0", "Vulkan1", "MTL0"
    description: str      # "NVIDIA GeForce RTX 2060 SUPER"
    free_mb: int
    total_mb: int
    integrated: bool


_libs_lock = threading.Lock()
_libs: Dict[str, Tuple[Any, Any]] = {}


def _ggml():
    """libggml (the device registry) and libggml-base (device queries) of the llama.cpp in use."""
    import llama_cpp
    from llama_cpp import _ctypes_extensions as ext
    libdir = Path(llama_cpp.__file__).resolve().parent / "lib"
    key = str(libdir)
    with _libs_lock:
        if key in _libs:
            return _libs[key]
        reg = ext.load_shared_library("ggml", libdir)
        base = ext.load_shared_library("ggml-base", libdir)
        reg.ggml_backend_dev_count.restype = ctypes.c_size_t
        reg.ggml_backend_dev_get.restype = ctypes.c_void_p
        reg.ggml_backend_dev_get.argtypes = [ctypes.c_size_t]
        for fn in ("ggml_backend_dev_name", "ggml_backend_dev_description"):
            getattr(base, fn).restype = ctypes.c_char_p
            getattr(base, fn).argtypes = [ctypes.c_void_p]
        base.ggml_backend_dev_type.restype = ctypes.c_int
        base.ggml_backend_dev_type.argtypes = [ctypes.c_void_p]
        base.ggml_backend_dev_memory.restype = None
        base.ggml_backend_dev_memory.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t),
                                                 ctypes.POINTER(ctypes.c_size_t)]
        _libs[key] = (reg, base)
        return reg, base


def _runtime_ready() -> bool:
    """llama_cpp can be asked about devices: imported, after the GPU pack had its chance to load
    (importing it first would pin the bundled processor-only build)."""
    if "llama_cpp" not in sys.modules:
        try:
            from eli.core.gpu_pack_runtime import try_activate_gpu_pack
            try_activate_gpu_pack(verify=False)
        except Exception:
            log.debug("load_plan: GPU pack activation skipped", exc_info=True)
    try:
        import llama_cpp
    except Exception:
        log.debug("load_plan: llama_cpp not importable", exc_info=True)
        return False
    # a stand-in (tests mock the native library) is not llama.cpp: calling it with real pointers crashes
    from unittest.mock import Mock
    return not isinstance(llama_cpp, Mock) and not isinstance(getattr(llama_cpp, "llama_cpp", None), Mock)


def devices() -> List[Device]:
    """The GPUs llama.cpp loads a model onto, in its order, with what each has free now: the discrete
    ones, the integrated ones only when there is no discrete one (llama.cpp's own rule). [] when the
    runtime has no GPU backend or cannot be asked."""
    if not _runtime_ready():
        return []
    try:
        reg, base = _ggml()
        found: List[Tuple[int, str, str, int, int]] = []
        for i in range(int(reg.ggml_backend_dev_count())):
            dev = reg.ggml_backend_dev_get(i)
            kind = int(base.ggml_backend_dev_type(dev))
            if kind not in (_TYPE_GPU, _TYPE_IGPU):
                continue
            free, total = ctypes.c_size_t(0), ctypes.c_size_t(0)
            base.ggml_backend_dev_memory(dev, ctypes.byref(free), ctypes.byref(total))
            found.append((kind, (base.ggml_backend_dev_name(dev) or b"").decode("utf-8", "replace"),
                          (base.ggml_backend_dev_description(dev) or b"").decode("utf-8", "replace"),
                          int(free.value // MIB), int(total.value // MIB)))
    except Exception:
        log.debug("load_plan: llama.cpp device list unavailable", exc_info=True)
        return []
    chosen = [f for f in found if f[0] == _TYPE_GPU] or [f for f in found if f[0] == _TYPE_IGPU]
    return [Device(i, name, desc, free, total, kind == _TYPE_IGPU)
            for i, (kind, name, desc, free, total) in enumerate(chosen)]


# ── request and plan ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Request:
    model_path: str
    n_ctx: int = 0                       # 0: auto for this model on this machine
    n_gpu_layers: Optional[int] = None   # None or -1: as many as fit; a number is a ceiling, never exceeded
    n_batch: int = 0                     # 0: the batch setting's default
    n_threads: int = 0                   # 0: the physical performance cores
    cache_type_k: str = ""
    cache_type_v: str = ""
    use_mmap: bool = True
    use_mlock: bool = False
    fit_priority: str = ""               # "": the setting (hardware_profile.fit_priority)
    tensor_split: str = ""               # "": shared out by measurement; else the operator's weights
    gpu_devices: str = ""                # "": every GPU; else the ones to use ("0,1")
    split_mode: str = ""                 # "" or "layer"; "none": the main GPU alone
    main_gpu: int = 0
    cpu_only: bool = False               # compute mode CPU: no GPU at all, not even for compute


@dataclass
class Plan:
    model_path: str
    n_ctx: int
    n_gpu_layers: int                    # llama.cpp's count: blocks + 1 is every layer and the head
    n_batch: int
    n_threads: int
    cache_type_k: str
    cache_type_v: str
    flash_attn: bool
    split_mode: int
    main_gpu: int
    tensor_split: Optional[List[float]]
    experts_in_ram: Optional[int]        # leading layers whose expert tensors stay in RAM; None: none
    blocks: int
    devices: List[Device] = field(default_factory=list)
    use_mb: Dict[int, float] = field(default_factory=dict)    # planned use per device index
    host_mb: float = 0.0
    measured: bool = False
    use_mmap: bool = True
    use_mlock: bool = False
    cpu_only: bool = False
    notes: List[str] = field(default_factory=list)
    asked: Dict[str, int] = field(default_factory=dict)   # what the search started from

    @property
    def layers_on_gpu(self) -> int:
        """Transformer blocks on a GPU (the output head not counted)."""
        if self.n_gpu_layers < 0:                 # -1: every layer
            return self.blocks
        return max(0, min(self.blocks, self.n_gpu_layers - (1 if self.n_gpu_layers > self.blocks else 0)))

    def llama_kwargs(self) -> Dict[str, Any]:
        from eli.core.gguf_sizes import llama_cache_args
        kw: Dict[str, Any] = dict(
            model_path=self.model_path, n_ctx=int(self.n_ctx), n_gpu_layers=int(self.n_gpu_layers),
            n_batch=int(self.n_batch),           # llama-cpp-python sets the micro-batch to min(batch, its own)
            n_threads=int(self.n_threads), n_threads_batch=int(self.n_threads),
            use_mmap=bool(self.use_mmap), use_mlock=bool(self.use_mlock), verbose=False)
        kw.update(llama_cache_args(self.cache_type_k, self.cache_type_v))
        if self.flash_attn:
            kw["flash_attn"] = True
        if self.cpu_only:
            # no device at all: llama.cpp otherwise still sends large batches to a GPU for compute
            kw.update(n_gpu_layers=0, split_mode=_SPLIT_MODES["none"], main_gpu=-1,
                      offload_kqv=False, op_offload=False)
            return kw
        kw["split_mode"] = int(self.split_mode)
        kw["main_gpu"] = int(self.main_gpu)
        if self.tensor_split:
            kw["tensor_split"] = [float(x) for x in self.tensor_split]
        return kw

    def describe(self) -> str:
        """One line: what loads and where."""
        if self.cpu_only or self.n_gpu_layers <= 0 or not self.devices:
            where = "on the processor"
        else:
            parts = []
            for d in self.devices:
                if self.tensor_split and self.tensor_split[d.index] <= 0:
                    continue
                used = self.use_mb.get(d.index)
                parts.append(f"{d.name} {d.description}: uses {used:.0f} of {d.free_mb:.0f} MB free"
                             if used is not None else f"{d.name} {d.description}")
            where = (f"{self.layers_on_gpu}/{self.blocks} layers on GPU"
                     + (" + output" if self.n_gpu_layers > self.blocks else "")
                     + (f" ({'; '.join(parts)})" if parts else ""))
        experts = (f", experts of the first {self.experts_in_ram} layers in RAM"
                   if self.experts_in_ram else "")
        kv = self.cache_type_k or "f16"
        return (f"ctx={self.n_ctx} batch={self.n_batch} {where}{experts}, KV {kv}, "
                f"flash attention {'on' if self.flash_attn else 'off'}, "
                f"{'measured' if self.measured else 'estimated'}")




# ── headroom: what a card needs free after the load ─────────────────────────────────────────────

_headroom_lock = threading.Lock()
_watch: Dict[str, Any] = {}


def _headroom_file() -> Path:
    from eli.core.paths import data_dir
    return Path(data_dir()) / "runtime" / "gpu_headroom.json"


def _card(dev: Device) -> str:
    """A card's identity across runs and machines' device order: its name and size."""
    return f"{dev.description or dev.name}|{int(round(dev.total_mb))}"


def _headroom_table() -> Dict[str, Any]:
    import json
    try:
        return json.loads(_headroom_file().read_text(encoding="utf-8"))
    except Exception:
        return {}


def measured_headroom(dev: Device, model_path: str = "", n_batch: int = 0) -> Optional[float]:
    """MiB llama.cpp took on this card after loading this model (or, not measured for it, any model),
    scaled to `n_batch` when it was measured at a smaller batch: its working buffers grow with the
    batch. None when the card has never been measured."""
    seen = (_headroom_table().get(_card(dev)) or {})
    entry = seen.get(Path(str(model_path)).name) if model_path else None
    if entry is None and seen:
        entry = max(seen.values(), key=lambda e: float(e.get("mb") or 0.0))
    if not entry:
        return None
    mb, batch = float(entry.get("mb") or 0.0), int(entry.get("batch") or 0)
    return mb * (n_batch / batch) if batch and n_batch > batch else mb


def headroom_mb(dev: Device, model_path: str, n_batch: int, compute_mb: float) -> float:
    """What the plan leaves free on a card: the operator's own figure, else what was measured here,
    else llama.cpp's compute-buffer figure for this card and load."""
    raw = (os.environ.get("ELI_VRAM_RESERVE_MB") or "").strip()
    if raw.isdigit() and int(raw) > 0:
        return float(raw)
    got = measured_headroom(dev, model_path, n_batch)
    return float(got) if got is not None else float(compute_mb)


def watch_headroom(plan: "Plan") -> None:
    """Start measuring a load: each card's free memory now, right after it."""
    with _headroom_lock:
        _watch.clear()
        if plan.cpu_only or plan.n_gpu_layers <= 0 or not plan.devices:
            return
        try:
            after = {d.index: d.free_mb for d in devices()}
        except Exception:
            log.debug("headroom watch could not read the cards", exc_info=True)
            return
        _watch.update(model=Path(plan.model_path).name, batch=int(plan.n_batch), calls=0,
                      after_load=after, cards={d.index: d for d in plan.devices})


def note_headroom() -> None:
    """After a generation call: what each card gave up since the load, remembered when it is more than
    known. Read over the first calls after a load only, so memory another program takes later is not
    put down to ELI."""
    import json
    with _headroom_lock:
        if not _watch or _watch["calls"] >= len(_watch["cards"]) + 2:
            return
        _watch["calls"] += 1
        try:
            now = {d.index: d.free_mb for d in devices()}
        except Exception:
            return
        table = _headroom_table()
        changed = False
        for idx, dev in _watch["cards"].items():
            if idx not in now or idx not in _watch["after_load"]:
                continue
            grown = max(0.0, float(_watch["after_load"][idx]) - float(now[idx]))
            entry = table.setdefault(_card(dev), {}).get(_watch["model"]) or {}
            if grown > float(entry.get("mb") or 0.0) or "mb" not in entry:
                table[_card(dev)][_watch["model"]] = {"mb": round(grown, 1), "batch": _watch["batch"]}
                changed = True
        if changed:
            try:
                path = _headroom_file()
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix(".tmp")
                tmp.write_text(json.dumps(table, indent=1), encoding="utf-8")
                tmp.replace(path)
            except Exception:
                log.debug("headroom not recorded", exc_info=True)


# ── measuring a configuration ────────────────────────────────────────────────────────────────────

@dataclass
class Footprint:
    ok: bool
    error: str = ""
    unreadable: bool = False           # llama.cpp could not open the model at all: no setting helps
    per_device: Dict[str, float] = field(default_factory=dict)   # GPU name -> MiB
    host_weights_mb: float = 0.0       # weights left on the processor (file-mapped, experts in RAM)
    host_kv_mb: float = 0.0
    host_compute_mb: float = 0.0
    flash_attn: Optional[bool] = None
    layer_dev: Dict[int, str] = field(default_factory=dict)      # unit (block; `blocks` = head) -> device
    layer_kv_mb: Dict[int, float] = field(default_factory=dict)  # block -> KV MiB at this context
    compute: Dict[str, float] = field(default_factory=dict)      # buffer name -> MiB

    @property
    def host_mb(self) -> float:
        return self.host_weights_mb + self.host_kv_mb + self.host_compute_mb


_ASSIGN = re.compile(r"load_tensors: layer\s+(\d+) assigned to device (\S+?),")
_CACHE_DEV = re.compile(r"(?:llama_kv_cache|llama_memory_recurrent)[:,] layer\s+(\d+): dev = (\S+)")
_CACHE_SIZE = re.compile(r"(?:llama_kv_cache|llama_memory_recurrent): size =\s*([\d.]+) MiB \(\s*\d+ cells,\s*(\d+) layers")
_COMPUTE = re.compile(r"\s(\S+) compute buffer size =\s*([\d.]+) MiB")
_FA_RESOLVED = re.compile(r"Flash Attention (enabled|not supported)")
_FA_PARAM = re.compile(r"flash_attn\s*=\s*(\w+)")


def parse_footprint(lines: Sequence[str], weights, gpu_names: Sequence[str], *,
                    experts_in_ram: Optional[int] = None) -> Footprint:
    """What llama.cpp's log of a (simulated) load says each device holds, in MiB: its layers' weights
    (from the file's tensor table), their caches (each cache's size shared over its layers) and its
    compute buffers. Anything not on a GPU in `gpu_names` is host memory."""
    fp = Footprint(ok=True)
    pending: List[Tuple[int, str]] = []
    for line in "".join(str(x) for x in lines).splitlines():
        m = _ASSIGN.search(line)
        if m:
            fp.layer_dev[int(m.group(1))] = m.group(2)
            continue
        m = _CACHE_DEV.search(line)
        if m:
            pending.append((int(m.group(1)), m.group(2)))
            continue
        m = _CACHE_SIZE.search(line)
        if m:
            each = float(m.group(1)) / max(1, int(m.group(2)))
            for il, dev in pending:
                fp.layer_kv_mb[il] = fp.layer_kv_mb.get(il, 0.0) + each
                if dev in gpu_names:
                    fp.per_device[dev] = fp.per_device.get(dev, 0.0) + each
                else:
                    fp.host_kv_mb += each
            pending = []
            continue
        m = _COMPUTE.search(line)
        if m:
            name, mb = m.group(1), float(m.group(2))
            fp.compute[name] = fp.compute.get(name, 0.0) + mb
            if name in gpu_names:
                fp.per_device[name] = fp.per_device.get(name, 0.0) + mb
            else:
                fp.host_compute_mb += mb
            continue
        m = _FA_RESOLVED.search(line)
        if m:
            fp.flash_attn = m.group(1) == "enabled"
            continue
        m = _FA_PARAM.search(line)
        if m and fp.flash_attn is None and m.group(1) in ("enabled", "disabled"):
            fp.flash_attn = m.group(1) == "enabled"
    if weights is not None:
        for unit, dev in fp.layer_dev.items():
            on_gpu = dev in gpu_names
            mb = _unit_weight_mb(weights, unit, experts_in_ram if on_gpu else None)
            if on_gpu:
                fp.per_device[dev] = fp.per_device.get(dev, 0.0) + mb
                if experts_in_ram is not None and unit < min(experts_in_ram, weights.blocks):
                    fp.host_weights_mb += weights.expert_bytes[unit] / MIB
            else:
                fp.host_weights_mb += mb
    return fp


def _unit_weight_mb(weights, unit: int, experts_in_ram: Optional[int]) -> float:
    """Weights of one unit where it is assigned: a block (without its experts when they stay in RAM)
    or, at index `blocks`, the output head."""
    if unit >= weights.blocks:
        return weights.output_bytes / MIB
    experts = 0 if (experts_in_ram is not None and unit < experts_in_ram) else weights.expert_bytes[unit]
    return (weights.block_bytes[unit] + experts) / MIB


_simulate_lock = threading.Lock()


def simulation_supported() -> bool:
    """Whether this llama.cpp can simulate a load (llama_model_params.no_alloc; 0.3.35 has it)."""
    if not _runtime_ready():
        return False
    try:
        from llama_cpp import llama_cpp as lc
        return "no_alloc" in {f[0] for f in lc.llama_model_params._fields_}
    except Exception:
        return False


def simulate(model_path: str, *, n_ctx: int, n_batch: int, n_gpu_layers: int, split_mode: int,
             main_gpu: int, tensor_split: Optional[Sequence[float]], type_k: Optional[int],
             type_v: Optional[int], flash_attn: Optional[bool], experts_in_ram: Optional[int],
             weights, gpu_names: Sequence[str]) -> Footprint:
    """A load of these settings, simulated by llama.cpp: nothing is allocated. flash_attn None lets
    llama.cpp decide, as a real load asking for it would be told."""
    from llama_cpp import llama_cpp as lc
    from eli.cognition.model_load_diagnostics import capture_llama_log
    from eli.core import moe_offload
    mp = lc.llama_model_default_params()
    mp.n_gpu_layers = int(n_gpu_layers)
    mp.split_mode = int(split_mode)
    mp.main_gpu = int(main_gpu)
    keep = []
    if tensor_split:
        size = int(lc.llama_max_devices())
        vals = [float(v) for v in list(tensor_split)[:size]] + [0.0] * max(0, size - len(tensor_split))
        arr = (ctypes.c_float * size)(*vals)
        keep.append(arr)
        mp.tensor_split = arr
    mp.no_alloc = True
    if "load_mode" in {f[0] for f in type(mp)._fields_} and hasattr(lc, "LLAMA_LOAD_MODE_NONE"):
        mp.load_mode = lc.LLAMA_LOAD_MODE_NONE
    if experts_in_ram is not None:
        mp.tensor_buft_overrides = ctypes.cast(moe_offload.override_table(experts_in_ram), ctypes.c_void_p)
        moe_offload.apply_zero_copy(mp)
    cp = lc.llama_context_default_params()
    cp.n_ctx = int(n_ctx)
    cp.n_batch = int(n_batch)
    cp.n_ubatch = int(min(n_batch, cp.n_ubatch))          # llama.cpp's own micro-batch, as at load
    cp.n_seq_max = 1
    cp.flash_attn_type = (lc.LLAMA_FLASH_ATTN_TYPE_AUTO if flash_attn is None
                          else lc.LLAMA_FLASH_ATTN_TYPE_ENABLED if flash_attn
                          else lc.LLAMA_FLASH_ATTN_TYPE_DISABLED)
    if type_k is not None:
        cp.type_k = int(type_k)
    if type_v is not None:
        cp.type_v = int(type_v)
    ok = False
    with _simulate_lock, capture_llama_log() as lines:
        model = lc.llama_model_load_from_file(str(model_path).encode("utf-8"), mp)
        if model:
            try:
                ctx = lc.llama_init_from_model(model, cp)
                ok = bool(ctx)
                if ctx:
                    lc.llama_free(ctx)
            finally:
                lc.llama_model_free(model)
    if not ok:
        err = next((ln.strip() for ln in reversed(lines) if "error" in ln.lower() or "fail" in ln.lower()),
                   "llama.cpp could not build this configuration")
        return Footprint(ok=False, error=err, unreadable=not model)
    return parse_footprint(lines, weights, gpu_names, experts_in_ram=experts_in_ram)


# ── shares ───────────────────────────────────────────────────────────────────────────────────────

def layer_devices(n_units: int, n_gpu_layers: int, counts: Sequence[int]) -> Dict[int, int]:
    """llama.cpp's assignment: the last `n_gpu_layers` units (blocks, then the head) go to the GPUs in
    device order, `counts[d]` of them to device d (tensor_split given as these counts)."""
    act = min(int(n_gpu_layers), n_units)
    out: Dict[int, int] = {}
    unit = n_units - act
    for d, c in enumerate(counts):
        for _ in range(int(c)):
            if unit < n_units:
                out[unit] = d
                unit += 1
    return out


def balanced_counts(unit_mb: Sequence[float], n_gpu_layers: int, room: Sequence[float],
                    usable: Sequence[bool]) -> Optional[List[int]]:
    """Units per device for the last `n_gpu_layers` units, in device order, so every device fills the
    same share of its room (MiB after its compute buffers and the reserve). None when they don't fit."""
    n_units = len(unit_mb)
    act = min(int(n_gpu_layers), n_units)
    if act <= 0:
        return [0] * len(room)
    costs = list(unit_mb[n_units - act:])
    devs = [d for d in range(len(room)) if usable[d] and room[d] > 0]

    def fill(share: float) -> Optional[List[int]]:
        counts = [0] * len(room)
        i = 0
        for d in devs:
            cap, used = room[d] * share, 0.0
            while i < act and used + costs[i] <= cap:
                used += costs[i]
                counts[d] += 1
                i += 1
        return counts if i >= act else None

    if not devs or fill(1.0) is None:
        return None
    lo, hi = 0.0, 1.0
    for _ in range(30):
        mid = (lo + hi) / 2
        if fill(mid) is None:
            lo = mid
        else:
            hi = mid
    return fill(hi)


@dataclass
class _Costs:
    """Every unit's cost at one context, from one measurement (or the file): what predicts other layer
    counts and shares without simulating each."""
    weights_mb: List[float]            # per unit on a GPU (blocks, then the head)
    kv_mb: List[float]                 # per block at `ctx`
    ctx: int
    compute_mb: Dict[int, float]       # per device index
    host_compute_mb: float
    flash_attn: Optional[bool]

    def unit_mb(self, ctx: int) -> List[float]:
        scale = float(ctx) / float(max(1, self.ctx))
        kv = [k * scale for k in self.kv_mb] + [0.0]
        return [w + k for w, k in zip(self.weights_mb, kv)]

    def with_experts(self, weights, experts_in_ram: Optional[int]) -> "_Costs":
        return replace(self, weights_mb=_unit_weights(weights, experts_in_ram))


def _unit_weights(weights, experts_in_ram: Optional[int]) -> List[float]:
    return [_unit_weight_mb(weights, u, experts_in_ram) for u in range(weights.blocks + 1)]


def _predict(costs: _Costs, ctx: int, n_gpu_layers: int, counts: Sequence[int]) -> Dict[int, float]:
    units = costs.unit_mb(ctx)
    use = {d: float(costs.compute_mb.get(d, 0.0)) for d in range(len(counts)) if counts[d] > 0}
    for unit, d in layer_devices(len(units), n_gpu_layers, counts).items():
        use[d] = use.get(d, 0.0) + units[unit]
    return use


# ── the planner ──────────────────────────────────────────────────────────────────────────────────

def _parse_list(raw: Any, kind=float) -> List[Any]:
    out = []
    for part in str(raw or "").replace(";", ",").split(","):
        part = part.strip()
        if part:
            try:
                out.append(kind(part))
            except ValueError:
                return []
    return out


def _threads(requested: int) -> int:
    if int(requested or 0) > 0:
        return int(requested)
    from eli.core.hardware_profile import recommend_cpu_threads
    return int(recommend_cpu_threads())


class _Search:
    """The configurations tried for one plan, measured (or estimated) and remembered as they are."""

    def __init__(self, req: Request, devs: List[Device], weights, *, measure: bool):
        from eli.core.hardware_profile import cpu_ram_budget_mb, detect_hardware
        self.req = req
        self.devs = devs
        self.weights = weights
        self.measure = measure
        self.blocks = int(weights.blocks)
        self.units = self.blocks + 1
        self.names = [d.name for d in devs]
        chosen = set(_parse_list(req.gpu_devices, int)) if str(req.gpu_devices or "").strip() else None
        self.split_mode = _SPLIT_MODES.get(str(req.split_mode or "layer").strip().lower(), _SPLIT_MODES["layer"])
        self.main_gpu = max(0, min(len(devs) - 1, int(req.main_gpu or 0)))
        if self.split_mode == _SPLIT_MODES["none"]:
            chosen = {self.main_gpu}
        self.usable = [chosen is None or d.index in chosen for d in devs]
        self.free = [float(d.free_mb) for d in devs]
        self.fixed = _parse_list(req.tensor_split) if str(req.tensor_split or "").strip() else None
        self.ram_mb = float(cpu_ram_budget_mb(float(detect_hardware().available_ram_gb)))
        self.notes: List[str] = []
        self.tried = 0
        self.unreadable = ""
        self._costs: Dict[tuple, Optional[_Costs]] = {}
        self._verified: Dict[tuple, Optional[dict]] = {}

    def _split_for(self, n_gpu_layers: int, room: Optional[List[float]] = None) -> List[int]:
        """A share: by the operator's weights, else by room (free memory before the first measurement)."""
        weights = list(self.fixed or room or self.free) + [0.0] * len(self.devs)
        weights = [w if self.usable[i] else 0.0 for i, w in enumerate(weights[:len(self.devs)])]
        act = min(n_gpu_layers, self.units)
        total = sum(weights) or 1.0
        raw = [act * w / total for w in weights]
        counts = [int(math.floor(x)) for x in raw]
        for d in sorted(range(len(raw)), key=lambda i: raw[i] - counts[i], reverse=True)[:act - sum(counts)]:
            counts[d] += 1
        return counts

    def _sim(self, ctx, batch, layers, counts, kv, experts, flash) -> Footprint:
        from eli.core.gguf_sizes import _GGML_TYPE_ID, effective_cache_type
        self.tried += 1
        tk, tv = effective_cache_type(kv[0]), effective_cache_type(kv[1] or kv[0])
        return simulate(self.req.model_path, n_ctx=ctx, n_batch=batch, n_gpu_layers=layers,
                        split_mode=self.split_mode, main_gpu=self.main_gpu,
                        tensor_split=[float(c) for c in counts] if len(self.devs) > 1 else None,
                        type_k=_GGML_TYPE_ID[tk] if tk != "f16" else None,
                        type_v=_GGML_TYPE_ID[tv] if tv != "f16" else None,
                        flash_attn=flash, experts_in_ram=experts, weights=self.weights, gpu_names=self.names)

    def costs(self, ctx: int, batch: int, kv: Tuple[str, str], experts: Optional[int]) -> Optional[_Costs]:
        """Every unit's cost at this context, batch and cache type. Caches and compute buffers don't
        depend on where the experts are, so one measurement serves every expert placement."""
        key = (ctx, batch, kv)
        if key not in self._costs:
            self._costs[key] = self._measure_costs(ctx, batch, kv) if self.measure \
                else self._estimate_costs(ctx, batch, kv)
        got = self._costs[key]
        return got.with_experts(self.weights, experts) if got is not None else None

    def _measure_costs(self, ctx, batch, kv) -> Optional[_Costs]:
        if self.unreadable:
            return None
        fp = self._sim(ctx, batch, self.units, self._split_for(self.units), kv, None, None)
        if fp.unreadable:
            self.unreadable = fp.error
            return None
        if not fp.ok:
            self.notes.append(f"llama.cpp cannot build ctx={ctx} batch={batch} KV {kv[0] or 'f16'}: {fp.error}")
            return None
        return _Costs(_unit_weights(self.weights, None), [fp.layer_kv_mb.get(b, 0.0) for b in range(self.blocks)],
                      ctx, {d.index: fp.compute.get(d.name, 0.0) for d in self.devs}, fp.host_compute_mb,
                      fp.flash_attn)

    def _estimate_costs(self, ctx, batch, kv) -> _Costs:
        from eli.core import gguf_sizes
        from eli.core.hardware_profile import _CUDA_OVERHEAD_MB, _compute_graph_reserve_mb
        per_token = gguf_sizes.kv_bytes_per_layer(self.req.model_path, kv[0], kv[1]) or [0.0] * self.blocks
        compute = float(_compute_graph_reserve_mb(ctx, batch) + _CUDA_OVERHEAD_MB)
        return _Costs(_unit_weights(self.weights, None), [b * ctx / MIB for b in per_token], ctx,
                      {d.index: compute for d in self.devs}, 0.0, bool(kv[0]))

    def room(self, costs: _Costs, batch: int) -> List[float]:
        """MiB each card can give this load: free now, less its headroom (headroom_mb)."""
        return [max(0.0, self.free[d] - headroom_mb(dev, self.req.model_path, batch, costs.compute_mb.get(d, 0.0)))
                for d, dev in enumerate(self.devs)]

    def counts_for(self, costs: _Costs, ctx: int, layers: int, batch: int) -> Optional[List[int]]:
        room = self.room(costs, batch)
        if self.fixed:
            counts = self._split_for(layers, room)
            use = _predict(costs, ctx, layers, counts)
            return counts if all(use[d] <= room[d] for d in use) else None
        room = [max(0.0, room[d] - costs.compute_mb.get(d, 0.0)) for d in range(len(self.devs))]
        return balanced_counts(costs.unit_mb(ctx), layers, room, self.usable)

    def fits(self, ctx: int, batch: int, layers: int, kv: Tuple[str, str], experts: Optional[int]) -> Optional[dict]:
        """This configuration with its best share, as llama.cpp builds it, when it fits every device."""
        key = (ctx, batch, layers, kv, experts)
        if key in self._verified:
            return self._verified[key]
        out = None
        costs = self.costs(ctx, batch, kv, experts)
        counts = self.counts_for(costs, ctx, layers, batch) if costs is not None else None
        if counts is not None:
            if self.measure:
                fp = self._sim(ctx, batch, layers, counts, kv, experts, costs.flash_attn)
                use = {d.index: fp.per_device.get(d.name, 0.0) for d in self.devs if d.name in fp.per_device}
                room = self.room(costs, batch)
                ok = fp.ok and all(use[d] <= room[d] for d in use) \
                    and fp.host_kv_mb + fp.host_compute_mb <= self.ram_mb
                if ok:
                    out = dict(ctx=ctx, batch=batch, layers=layers, kv=kv, experts=experts, counts=counts,
                               flash=bool(fp.flash_attn if fp.flash_attn is not None else costs.flash_attn),
                               use=use, host=fp.host_mb)
            else:
                use = _predict(costs, ctx, layers, counts)
                out = dict(ctx=ctx, batch=batch, layers=layers, kv=kv, experts=experts, counts=counts,
                           flash=bool(costs.flash_attn), use=use, host=0.0)
        self._verified[key] = out
        return out

    def most_layers(self, ctx, batch, kv, experts, lo, hi) -> Optional[dict]:
        """The most GPU layers in [lo, hi] that fit: predicted, then confirmed."""
        costs = self.costs(ctx, batch, kv, experts)
        if costs is None or hi < lo:
            return None
        a, b, good = lo, hi, None
        while a <= b:
            mid = (a + b) // 2
            if self.counts_for(costs, ctx, mid, batch) is not None:
                good, a = mid, mid + 1
            else:
                b = mid - 1
        while good is not None and good >= lo:
            got = self.fits(ctx, batch, good, kv, experts)
            if got is not None:
                return got
            good -= 1
        return None

    def fewest_experts(self, ctx, batch, kv) -> Optional[dict]:
        """Every layer on the GPUs with the experts of as few leading layers as possible in RAM."""
        costs = self.costs(ctx, batch, kv, self.blocks)
        if costs is None or self.counts_for(costs, ctx, self.units, batch) is None:
            return None
        lo, hi, good = 1, self.blocks, self.blocks
        while lo <= hi:
            mid = (lo + hi) // 2
            if self.counts_for(costs.with_experts(self.weights, mid), ctx, self.units, batch) is not None:
                good, hi = mid, mid - 1
            else:
                lo = mid + 1
        for k in range(good, self.blocks + 1):
            got = self.fits(ctx, batch, self.units, kv, k)
            if got is not None:
                return got
        return None


def plan(req: Request) -> Optional[Plan]:
    """What to load this request with on this machine now, or None when the model file cannot be read
    (the caller then hands the request to llama.cpp as it is)."""
    from eli.core import gguf_sizes, moe_offload
    from eli.core.gguf_sizes import cache_setting
    from eli.core.hardware_profile import fit_priority as _priority_setting, normalize_fit_priority
    weights = gguf_sizes.weights(req.model_path)
    if weights is None:
        return None
    kv0 = (cache_setting(req.cache_type_k), cache_setting(req.cache_type_v or req.cache_type_k))
    threads = _threads(req.n_threads)
    devs = [] if req.cpu_only else devices()
    if not devs or (req.n_gpu_layers is not None and int(req.n_gpu_layers) == 0):
        return _cpu_plan(req, weights, kv0, threads, devs)
    s = _Search(req, devs, weights, measure=simulation_supported())
    if not any(s.usable):
        return _cpu_plan(req, weights, kv0, threads, devs)
    ctx = int(req.n_ctx or 0) or _auto_ctx(req.model_path, devs, s)
    batch = max(32, int(req.n_batch or 0) or _default_batch())
    # -1 (llama.cpp's "every layer"), or a count at or above the block count, means every layer:
    # llama.cpp counts the output head as one more, and 42 asked of a 42-block model would leave
    # block 0 on the processor
    asked_layers = None if req.n_gpu_layers is None else int(req.n_gpu_layers)
    ceiling = s.units if asked_layers is None or asked_layers < 0 or asked_layers >= s.blocks else asked_layers
    priority = normalize_fit_priority(req.fit_priority or _priority_setting())
    moe_mode = moe_offload.mode() if weights.experts_total > 0 else "off"
    experts_all = s.blocks if moe_mode != "off" else None
    batches = [b for b in (batch, batch // 2, batch // 4) if b >= 64] or [batch]
    kvs = [kv0] + ([("q8_0", "q8_0")] if not kv0[0] else [])   # quantize only when memory limits ctx
    floor = min(ceiling, int(math.ceil(s.units * 0.25)))

    def whole(c, b, kv):
        """Every asked-for layer on the GPUs: as asked, else with experts kept in RAM."""
        if moe_mode == "on":
            return s.fits(c, b, ceiling, kv, s.blocks)
        got = s.fits(c, b, ceiling, kv, None)
        if got is None and moe_mode == "auto" and ceiling >= s.units:
            got = s.fewest_experts(c, b, kv)
        return got

    steps: List[Callable[[], Optional[dict]]] = [lambda: whole(ctx, batch, kv0)]
    if priority == "max_gpu":
        steps += [lambda kv=kv, b=b: whole(ctx, b, kv) for kv in kvs for b in batches]
        steps += [lambda: _largest_ctx(lambda c, kv: whole(c, batches[-1], kv), ctx, kvs)]
        steps += [lambda: _largest_ctx(lambda c, kv: s.most_layers(c, batches[-1], kv, experts_all, 0, ceiling),
                                       ctx, kvs)]
    elif priority == "max_ctx":
        steps += [lambda kv=kv, b=b: s.most_layers(ctx, b, kv, experts_all, 0, ceiling) for kv in kvs for b in batches]
        steps += [lambda: _largest_ctx(lambda c, kv: s.most_layers(c, batches[-1], kv, experts_all, 0, ceiling),
                                       ctx, kvs)]
    else:
        steps += [lambda b=b: s.most_layers(ctx, b, kv0, experts_all, floor, ceiling) for b in batches]
        steps += [lambda kv=kv: whole(ctx, batches[-1], kv) for kv in kvs[1:]]
        steps += [lambda kv=kv: s.most_layers(ctx, batches[-1], kv, experts_all, 0, ceiling) for kv in kvs]
        steps += [lambda: _largest_ctx(lambda c, kv: s.most_layers(c, batches[-1], kv, experts_all, 0, ceiling),
                                       ctx, kvs)]
    chosen = None
    for step in steps:
        chosen = step()
        if chosen is not None or s.unreadable:
            break
    if s.unreadable:
        # the real load says why (model_load_diagnostics.explain_load_failure); no setting changes it
        p = as_asked(req)
        p.notes = [f"llama.cpp cannot open this model: {s.unreadable}"]
        return p
    if chosen is None:
        s.notes.append("no GPU placement fits the memory free now")
        return _cpu_plan(req, weights, kv0, threads, devs, notes=s.notes)
    counts = chosen["counts"]
    in_use = [d for d in range(len(devs)) if counts[d] > 0]
    p = Plan(model_path=req.model_path, n_ctx=int(chosen["ctx"]), n_gpu_layers=int(chosen["layers"]),
             n_batch=int(chosen["batch"]), n_threads=threads, cache_type_k=chosen["kv"][0],
             cache_type_v=chosen["kv"][1], flash_attn=bool(chosen["flash"]), split_mode=s.split_mode,
             main_gpu=in_use[0] if s.split_mode == _SPLIT_MODES["none"] and in_use else s.main_gpu,
             tensor_split=[float(c) for c in counts] if len(devs) > 1 else None,
             experts_in_ram=chosen["experts"], blocks=s.blocks, devices=devs,
             use_mb={int(k): float(v) for k, v in chosen["use"].items()}, host_mb=float(chosen["host"]),
             measured=s.measure, use_mmap=req.use_mmap, use_mlock=req.use_mlock, notes=s.notes)
    p.asked = {"n_ctx": ctx, "n_gpu_layers": ceiling, "n_batch": batch}
    asked = (ctx, ceiling, batch, kv0[0])
    if (p.n_ctx, p.n_gpu_layers, p.n_batch, p.cache_type_k) == asked and p.experts_in_ram is None:
        p.notes.append("your settings fit as asked")
    else:
        p.notes.append(f"asked ctx={ctx} gpu_layers={'all' if ceiling >= s.units else ceiling} "
                       f"batch={batch} KV {kv0[0] or 'f16'}; the most that fits now is shown above")
    p.notes.append(f"{s.tried} configurations {'simulated by llama.cpp' if s.measure else 'estimated from the file'}")
    return p


def _largest_ctx(try_ctx: Callable[[int, Tuple[str, str]], Optional[dict]], ctx: int,
                 kvs: Sequence[Tuple[str, str]], grain: int = 2048) -> Optional[dict]:
    """The largest context below `ctx`, on the grain, for which `try_ctx` finds a fit."""
    for kv in kvs:
        lo, hi, best = 1, max(1, (ctx - 1) // grain), None
        while lo <= hi:
            mid = (lo + hi) // 2
            got = try_ctx(mid * grain, kv)
            if got is not None:
                best, lo = got, mid + 1
            else:
                hi = mid - 1
        if best is not None:
            return best
    return None


def _auto_ctx(model_path: str, devs: List[Device], s: _Search) -> int:
    """hardware_profile.auto_ctx_target over the GPUs in use."""
    from eli.core.hardware_profile import auto_ctx_target, detect_hardware
    from eli.core.mem_units import file_size_gib
    free = int(sum(d.free_mb for d, ok in zip(devs, s.usable) if ok))
    hw = detect_hardware()
    return int(auto_ctx_target(model_path, file_size_gib(model_path), free_vram_mb=free,
                               available_ram_gb=float(hw.available_ram_gb), use_gpu=True))


def _measured_cpu_ctx(req: Request, weights, kv0, devs, target: int, batch: int,
                      ram_mb: float) -> Optional[int]:
    """The largest context up to `target` whose processor-side weights, cache and buffers fit `ram_mb`,
    from llama.cpp's simulation at the target and at half of it (the cache grows in step with the
    context), confirmed by one more. None when llama.cpp cannot simulate here or nothing fits."""
    if not simulation_supported() or target < 2:
        return None
    from eli.core.gguf_sizes import _GGML_TYPE_ID, effective_cache_type
    tk, tv = effective_cache_type(kv0[0]), effective_cache_type(kv0[1] or kv0[0])

    def host(ctx: int) -> Optional[float]:
        fp = simulate(req.model_path, n_ctx=ctx, n_batch=batch, n_gpu_layers=0, split_mode=_SPLIT_MODES["none"],
                      main_gpu=0 if devs else -1, tensor_split=None,
                      type_k=_GGML_TYPE_ID[tk] if tk != "f16" else None,
                      type_v=_GGML_TYPE_ID[tv] if tv != "f16" else None,
                      flash_attn=bool(kv0[0]), experts_in_ram=None, weights=weights,
                      gpu_names=[d.name for d in devs])
        return fp.host_mb if fp.ok else None

    half = target // 2
    hi, lo = host(target), host(half)
    if hi is None or lo is None:
        return None
    if hi <= ram_mb:
        return target
    per_token = (hi - lo) / (target - half)
    ctx = min(target, int(half + (ram_mb - lo) / per_token)) if per_token > 0 else 0
    for _ in range(3):                        # a cache that stops growing (sliding window) can bend the line
        if ctx < 1:
            return None
        used = host(ctx)
        if used is None:
            return None
        if used <= ram_mb:
            return ctx
        ctx = int(ctx * ram_mb / used)
    return None


def _cpu_plan(req: Request, weights, kv0, threads, devs, notes=None) -> Plan:
    from eli.core.hardware_profile import auto_ctx_target, cpu_ram_budget_mb, cpu_ram_fit_config, detect_hardware
    from eli.core.mem_units import file_size_gib
    hw = detect_hardware()
    size_gb = file_size_gib(req.model_path)
    target = int(req.n_ctx or 0) or int(auto_ctx_target(req.model_path, size_gb, free_vram_mb=0,
                                                         available_ram_gb=float(hw.available_ram_gb),
                                                         use_gpu=False))
    batch = int(req.n_batch or 0) or _default_batch()
    ctx = _measured_cpu_ctx(req, weights, kv0, devs, target, batch,
                            float(cpu_ram_budget_mb(float(hw.available_ram_gb))))
    measured = ctx is not None
    if not measured:
        ctx, batch = cpu_ram_fit_config(size_gb, float(hw.available_ram_gb), user_ctx=target, user_batch=batch,
                                        model_path=req.model_path, kv_quantized=bool(kv0[0]))
    p = Plan(model_path=req.model_path, n_ctx=int(ctx), n_gpu_layers=0, n_batch=int(batch), n_threads=threads,
             cache_type_k=kv0[0], cache_type_v=kv0[1], flash_attn=bool(kv0[0]),
             split_mode=_SPLIT_MODES["none"], main_gpu=0, tensor_split=None, experts_in_ram=None,
             blocks=int(weights.blocks), devices=list(devs), measured=measured, use_mmap=req.use_mmap,
             use_mlock=req.use_mlock, cpu_only=bool(req.cpu_only), notes=list(notes or []))
    p.asked = {"n_ctx": target, "n_gpu_layers": 0 if req.n_gpu_layers is None else int(req.n_gpu_layers),
               "n_batch": int(req.n_batch or 0) or _default_batch()}
    p.notes.append(f"on the processor: ctx={p.n_ctx} batch={p.n_batch} for "
                   f"{hw.available_ram_gb:.1f} GB of free RAM" + (" (measured by llama.cpp)" if measured else ""))
    return p


def on_processor(req: Request) -> Plan:
    """The request on the processor alone, sized to the RAM free now."""
    from eli.core import gguf_sizes
    from eli.core.gguf_sizes import cache_setting
    weights = gguf_sizes.weights(req.model_path)
    kv0 = (cache_setting(req.cache_type_k), cache_setting(req.cache_type_v or req.cache_type_k))
    if weights is None:
        p = as_asked(replace(req, n_gpu_layers=0))
        return p
    return _cpu_plan(req, weights, kv0, _threads(req.n_threads), [])


def _default_batch() -> int:
    """The batch setting's own default (runtime_settings.DEFAULTS), for a request that names none."""
    from eli.core.runtime_settings import DEFAULTS
    return int(DEFAULTS["batch_size"])


def as_asked(req: Request) -> Plan:
    """The request handed to llama.cpp as it is: for a file whose tensor table cannot be read."""
    layers = -1 if req.n_gpu_layers is None else int(req.n_gpu_layers)      # -1: every layer
    ctx = int(req.n_ctx or 0) or 2048
    p = Plan(model_path=req.model_path, n_ctx=ctx, n_gpu_layers=0 if req.cpu_only else layers,
             n_batch=int(req.n_batch or 0) or _default_batch(), n_threads=_threads(req.n_threads),
             cache_type_k=req.cache_type_k, cache_type_v=req.cache_type_v or req.cache_type_k,
             flash_attn=bool(req.cache_type_k), split_mode=_SPLIT_MODES["layer"], main_gpu=int(req.main_gpu or 0),
             tensor_split=_parse_list(req.tensor_split) or None, experts_in_ram=None, blocks=0,
             use_mmap=req.use_mmap, use_mlock=req.use_mlock, cpu_only=bool(req.cpu_only),
             notes=["the model file's tensor table could not be read: loading the settings as given"])
    p.asked = {"n_ctx": ctx, "n_gpu_layers": layers, "n_batch": p.n_batch}
    return p
