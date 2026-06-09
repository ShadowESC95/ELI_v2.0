from __future__ import annotations

import json
import os
import platform
import re
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional


ROOT = Path(__file__).resolve().parents[2]
SETTINGS_PATH = ROOT / "config/settings.json"
REPORT_PATH = ROOT / "artifacts/runtime_hardware_profile.json"


@dataclass
class GPUInfo:
    index: int
    name: str
    vendor: str
    total_mb: int
    free_mb: int


@dataclass
class HardwareProfile:
    hostname: str
    os: str
    cpu: str
    cpu_threads: int
    ram_total_gb: float
    gpus: List[GPUInfo]
    selected_gpu: Optional[GPUInfo]
    model_path: str
    model_size_gb: float
    model_train_ctx: int
    ctx_fraction: float
    n_ctx: int
    n_gpu_layers: int
    batch_size: int
    n_threads: int
    max_tokens: int
    mode_presets: Dict[str, Dict[str, Any]]
    reasoning: List[str]


def run(cmd: List[str]) -> str:
    return subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL).strip()


def detect_ram_gb() -> float:
    try:
        txt = Path("/proc/meminfo").read_text()
        m = re.search(r"MemTotal:\s+(\d+)\s+kB", txt)
        if m:
            return round(int(m.group(1)) / 1024 / 1024, 2)
    except Exception:
        pass
    return 8.0


def detect_cpu_name() -> str:
    try:
        txt = Path("/proc/cpuinfo").read_text(errors="replace")
        m = re.search(r"model name\s*:\s*(.+)", txt)
        if m:
            return m.group(1).strip()
    except Exception:
        pass
    return platform.processor() or "unknown"


def detect_nvidia_gpus() -> List[GPUInfo]:
    out: List[GPUInfo] = []
    try:
        raw = run([
            "nvidia-smi",
            "--query-gpu=index,name,memory.total,memory.free",
            "--format=csv,noheader,nounits",
        ])
        for line in raw.splitlines():
            idx, name, total, free = [x.strip() for x in line.split(",")[:4]]
            out.append(GPUInfo(int(idx), name, "nvidia", int(total), int(free)))
    except Exception:
        pass
    return out


def detect_other_gpus() -> List[GPUInfo]:
    out: List[GPUInfo] = []
    try:
        raw = run(["lspci"])
        for i, line in enumerate(raw.splitlines()):
            low = line.lower()
            if "vga" in low or "3d controller" in low:
                if "nvidia" in low:
                    continue
                vendor = "amd" if ("amd" in low or "advanced micro" in low) else ("intel" if "intel" in low else "unknown")
                out.append(GPUInfo(i, line.strip(), vendor, 0, 0))
    except Exception:
        pass
    return out


def detect_gpus() -> List[GPUInfo]:
    nvidia = detect_nvidia_gpus()
    return nvidia if nvidia else detect_other_gpus()


def select_gpu(gpus: List[GPUInfo]) -> Optional[GPUInfo]:
    measurable = [g for g in gpus if g.total_mb > 0]
    if measurable:
        return sorted(measurable, key=lambda g: (g.free_mb, g.total_mb), reverse=True)[0]
    return gpus[0] if gpus else None


def load_settings() -> Dict[str, Any]:
    if SETTINGS_PATH.exists():
        try:
            return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def find_model(settings: Dict[str, Any]) -> str:
    env_model = os.environ.get("ELI_MODEL_PATH", "").strip()
    if env_model:
        p = Path(env_model).expanduser()
        if not p.is_absolute():
            p = ROOT / p
        if p.exists():
            return str(p)

    for key in ("model_path", "bundled_model_path", "gguf_model_path"):
        val = settings.get(key)
        if val:
            p = Path(str(val)).expanduser()
            if not p.is_absolute():
                p = ROOT / p
            if p.exists():
                return str(p)

    models = sorted((ROOT / "models").rglob("*.gguf"), key=lambda p: p.stat().st_size, reverse=True)
    return str(models[0]) if models else ""


def size_gb(path: str) -> float:
    try:
        return round(Path(path).stat().st_size / (1024 ** 3), 2)
    except Exception:
        return 0.0


def train_ctx_for_model(model_path: str) -> int:
    """Return the model's native training context length.

    Checked first via ELI_MODEL_TRAIN_CTX env override, then by filename
    pattern matching. When in doubt, err on the side of the larger value —
    llama.cpp will clamp at load time anyway.
    """
    forced = os.environ.get("ELI_MODEL_TRAIN_CTX", "").strip()
    if forced:
        return int(forced)

    name = Path(model_path).name.lower()

    # ---- 128 K class ----
    if "deepseek" in name:                                    return 131072
    if "mistral-small-3.1" in name or "mistral-small" in name: return 131072
    if "llama-3.1" in name or "llama-3.2" in name:           return 131072
    if "phi-3" in name or "phi-4" in name:                   return 131072
    if "gemma-2" in name or "gemma2" in name:                return 131072
    if "falcon3" in name or "falcon-3" in name:              return 131072

    # ---- 32 K class ----
    if "qwen2.5" in name or "qwen2-5" in name:               return 32768
    if "qwen3" in name:                                       return 32768
    if "qwen2" in name:                                       return 32768
    if "mistral-7b" in name:                                  return 32768

    # ---- smaller / older ----
    if "llama-3" in name or "llama3" in name:                return 8192
    if "phi-2" in name:                                       return 4096
    if "tinyllama" in name:                                   return 2048
    if "gemma" in name:                                       return 8192

    return 32768


def estimate_layers(model_gb: float) -> int:
    if model_gb <= 2.5:
        return 24
    if model_gb <= 9:
        return 32
    if model_gb <= 18:
        return 40
    if model_gb <= 35:
        return 60
    return 80


def layer_mb(model_gb: float, layers: int) -> float:
    return 999999.0 if layers <= 0 else (model_gb * 1024.0) / layers


def kv_cache_mb(n_ctx: int, layers: int) -> float:
    # q4 KV approximation.
    return (n_ctx * layers * 1024) / 1048576.0


def round_ctx(raw: int) -> int:
    """Round raw ctx down to the nearest multiple of 2048 (minimum 2048).

    Previously used a sparse fixed list which created large dead zones where
    many different fraction inputs produced the same ctx value.  A 2048-grain
    rounding gives proportional results across the full fraction range.
    """
    if raw <= 0:
        return 2048
    return max(2048, (raw // 2048) * 2048)


def ram_ctx_cap(ram_gb: float, model_gb: float) -> int:
    """Conservative RAM ctx cap for models with CPU-resident KV layers.

    Derived from available headroom: each GB of net RAM (total minus model
    footprint and a fixed 2 GB OS/runtime reserve) supports ~1024 ctx tokens.
    Clamped to [2048, 131072] and rounded to the nearest 2048-grain.
    """
    _os_reserve_gb = 2.0
    net_gb = max(0.0, ram_gb - model_gb - _os_reserve_gb)
    return round_ctx(max(2048, min(131072, int(net_gb * 1024))))


def max_tokens_from_ctx(n_ctx: int) -> int:
    """Max generation tokens as half the context window, capped at [1024, 8192]."""
    return max(1024, min(8192, n_ctx // 2))


def mode_presets(n_ctx: int, max_tokens: int) -> Dict[str, Dict[str, Any]]:
    # MODEL-AGNOSTIC capability scaling: a bigger/smarter model gets MORE samples, wider and
    # deeper search, and larger per-stage budgets instead of staying throttled at the small-
    # model defaults. tier_scale() is 1.0 for the current small model (fully behaviour-
    # preserving) and rises (medium 1.5 / large 2.5 / frontier 4.0) as a larger GGUF is loaded.
    try:
        from eli.core.model_tier import tier_scale as _ts
        _scale = float(_ts())
    except Exception:
        _scale = 1.0

    def _cnt(base: int, lo: int, hi: int) -> int:
        return max(lo, min(hi, int(round(base * _scale))))

    def _tok(base: int) -> int:
        return min(max_tokens, int(round(base * _scale)))

    # Tree depth is tier-mapped so the SMALL model stays single-level (depth 1 = current
    # behaviour) and only capable models deepen the tree: small 1, medium 2, large 3, frontier 4.
    _depth = 1 if _scale < 1.5 else (2 if _scale < 2.5 else (3 if _scale < 4.0 else 4))

    return {
        "quick": {
            "max_tokens": min(max_tokens, 1024),
            "passes": 1,
            "memory_depth": "minimal",
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
            "samples": _cnt(3 if n_ctx >= 8192 else 2, 2, 7),
            "max_tokens_per_sample": _tok(2048),
            "max_tokens_final": _tok(3072),
        },
        "tree_of_thoughts": {
            "branches": _cnt(3 if n_ctx >= 8192 else 2, 2, 6),
            "depth": _depth,
            "max_tokens_propose": _tok(1024),
            "max_tokens_develop": _tok(3072),
            "max_tokens_critique": _tok(1024),
            "max_tokens_revise": max_tokens,
        },
        "constitutional_ai": {
            "max_tokens_generate": _tok(3072),
            "max_tokens_critique": _tok(1024),
            "max_tokens_revise": max_tokens,
            "max_tokens": max_tokens,
        },
    }


def allocate(
    profile_model: str,
    model_gb: float,
    ram_gb: float,
    gpu: Optional[GPUInfo],
    settings: Optional[Dict[str, Any]] = None,
) -> tuple[int, int, int, int, float, List[str]]:
    """Compute optimal (n_ctx, gpu_layers, batch, max_tokens, ctx_fraction, notes).

    Priority chain for every parameter:
      1. ELI_FORCE_* environment variables  — absolute override
      2. settings.json user values          — user explicitly saved these
      3. Computed optimal from VRAM/RAM     — automatic fallback

    The fraction=0.65 cap has been removed.  ctx is now sized directly from
    available KV-cache headroom so small fully-offloadable models automatically
    receive their full training context on GPUs with enough VRAM.
    """
    settings = settings or {}
    notes: List[str] = []

    train_ctx    = train_ctx_for_model(profile_model)
    layers_total = estimate_layers(model_gb)
    per_layer    = layer_mb(model_gb, layers_total)

    # ---- Explicit overrides (highest priority) ----
    forced_ctx    = os.environ.get("ELI_FORCE_CTX",        "").strip()
    forced_batch  = os.environ.get("ELI_FORCE_BATCH",      "").strip()
    forced_layers = os.environ.get("ELI_FORCE_GPU_LAYERS", "").strip()

    # ---- User-pinned preferences (2nd priority) ----
    # Use ONLY the dedicated user_preferred_* keys, never the auto-tuned
    # n_ctx / batch_size / n_gpu_layers keys that apply_profile() writes.
    # Those are optimizer outputs and must not feed back in as inputs.
    # To pin a value manually, add "user_preferred_ctx": N to settings.json.
    user_ctx    = str(settings.get("user_preferred_ctx")        or "").strip()
    user_batch  = str(settings.get("user_preferred_batch")      or "").strip()
    user_layers = str(settings.get("user_preferred_gpu_layers") or "").strip()

    # ---- Dialog / env fallbacks (3rd priority) ----
    # ELI_CTX_FRACTION and ELI_TARGET_BATCH are set by the startup dialog
    # spinboxes and propagated as env vars — this is the normal user path.
    target_batch  = int(os.environ.get("ELI_TARGET_BATCH",  "512"))
    ctx_fraction  = float(os.environ.get("ELI_CTX_FRACTION", "0.9"))

    # ---- CPU-only path ----
    if gpu is None or gpu.total_mb <= 0:
        _raw = int(train_ctx * ctx_fraction)
        _cpu_ctx = int(forced_ctx or user_ctx or round_ctx(min(_raw, ram_ctx_cap(ram_gb, model_gb))))
        _cpu_batch = int(forced_batch or user_batch or 256)
        notes.append(f"CPU/no measurable GPU: gpu_layers=0. ctx={_cpu_ctx} batch={_cpu_batch}.")
        return _cpu_ctx, 0, _cpu_batch, max_tokens_from_ctx(_cpu_ctx), ctx_fraction, notes

    # ---- VRAM budget ----
    _low_frac = float(os.environ.get("ELI_VRAM_LOW_FRAC", "0.30"))
    if gpu.free_mb < gpu.total_mb * _low_frac:
        _bonus   = int(os.environ.get("ELI_VRAM_TRANSIENT_BONUS_MB",  "1500"))
        _cap_frac = float(os.environ.get("ELI_VRAM_TRANSIENT_CAP_FRAC", "0.95"))
        vram_basis = min(gpu.free_mb + _bonus, int(gpu.total_mb * _cap_frac))
        notes.append(
            f"Low VRAM snapshot ({gpu.free_mb}/{gpu.total_mb} MB): "
            f"transient bonus applied → basis={vram_basis} MB."
        )
    else:
        vram_basis = gpu.free_mb

    runtime_reserve  = int(os.environ.get("ELI_VRAM_RESERVE_MB",    "1500"))
    hard_cap_frac    = float(os.environ.get("ELI_VRAM_HARD_CAP_FRAC", "0.85"))
    usable_vram      = min(max(0, vram_basis - runtime_reserve), int(gpu.total_mb * hard_cap_frac))

    # ---- Batch compute-buffer reserve ----
    # Sized by model footprint × batch, NOT by n_ctx.
    # llama.cpp SDPA/Flash-Attention compute buffers are ctx-independent;
    # the old batch×ctx formula was only valid for non-flash attention paths.
    # ELI_BATCH_RES_FACTOR (default 0.35): multiply model_gb × batch to get MB.
    _brf = float(os.environ.get("ELI_BATCH_RES_FACTOR", "0.35"))

    def _batch_reserve(b: int) -> int:
        return max(256, int(model_gb * b * _brf))

    # ---- Determine batch ----
    if forced_batch:
        n_batch = int(forced_batch)
    elif user_batch:
        n_batch = int(user_batch)
    else:
        # Descend from target until batch fits within 40 % of VRAM budget.
        _floor = min(256, target_batch)
        n_batch = _floor
        _b = target_batch
        while _b >= _floor:
            if _batch_reserve(_b) <= usable_vram * 0.40:
                n_batch = _b
                break
            _b = _b // 2

    batch_res          = _batch_reserve(n_batch)
    budget_after_batch = max(0, usable_vram - batch_res)

    # ---- Determine ctx ----
    model_vram_mb = model_gb * 1024.0          # VRAM needed for full offload
    kv_per_token  = layers_total * 1024 / 1048576.0  # MB per ctx token (q4_0 KV)

    if forced_ctx:
        n_ctx = int(forced_ctx)
        ctx_source = "ELI_FORCE_CTX"
    elif user_ctx:
        n_ctx = int(user_ctx)
        ctx_source = "settings.json"
    elif model_vram_mb <= budget_after_batch:
        # Model fits fully on GPU → maximize ctx from KV headroom.
        kv_budget = max(0.0, budget_after_batch - model_vram_mb)
        max_ctx_vram = max(2048, int(kv_budget / max(kv_per_token, 1e-6)))
        # Honour the user's fraction cap from the startup dialog (ELI_CTX_FRACTION).
        fraction_cap = round_ctx(int(train_ctx * ctx_fraction))
        n_ctx = round_ctx(min(train_ctx, max_ctx_vram, fraction_cap))
        ctx_source = f"VRAM-optimal capped at fraction {ctx_fraction:.2f} (kv_budget={kv_budget:.0f}MB)"
    else:
        # Partial offload → use fraction-based ctx capped by RAM.
        raw_ctx = int(train_ctx * ctx_fraction)
        n_ctx = round_ctx(min(raw_ctx, ram_ctx_cap(ram_gb, model_gb)))
        ctx_source = f"fraction ({ctx_fraction:.2f} × train_ctx, RAM-capped)"

    kv = kv_cache_mb(n_ctx, layers_total)

    # ---- Determine gpu_layers ----
    if forced_layers:
        gpu_layers = int(forced_layers)
        layer_source = "ELI_FORCE_GPU_LAYERS"
    elif user_layers:
        gpu_layers = int(user_layers)
        layer_source = "settings.json"
    else:
        remaining   = budget_after_batch - kv
        layers_fit  = max(0, min(layers_total, int(max(0.0, remaining) / max(per_layer, 1.0))))
        gpu_layers  = 99 if layers_fit >= layers_total else layers_fit
        layer_source = "computed"

    max_tok = max_tokens_from_ctx(n_ctx)

    notes.append(
        f"train_ctx={train_ctx} model={model_gb:.2f}GB layers={layers_total} "
        f"usable_vram={usable_vram}MB model_vram={model_vram_mb:.0f}MB"
    )
    notes.append(
        f"batch={n_batch}(res={batch_res}MB, src='{('forced' if forced_batch else 'user' if user_batch else 'computed')}') "
        f"ctx={n_ctx}(src='{ctx_source}') "
        f"kv={kv:.0f}MB gpu_layers={gpu_layers}(src='{layer_source}') "
        f"max_tokens={max_tok}"
    )

    return n_ctx, gpu_layers, n_batch, max_tok, ctx_fraction, notes


def build_profile() -> HardwareProfile:
    settings = load_settings()
    model = find_model(settings)
    model_gb = size_gb(model)

    gpus = detect_gpus()
    gpu = select_gpu(gpus)

    ram = detect_ram_gb()
    cpu_threads = os.cpu_count() or 4
    n_threads = max(2, cpu_threads - 2)

    # Pass user settings so allocate() can honour them first.
    n_ctx, gpu_layers, batch, max_tokens, ctx_fraction, notes = allocate(
        model, model_gb, ram, gpu, settings=settings
    )

    return HardwareProfile(
        hostname=platform.node(),
        os=f"{platform.system()} {platform.release()}",
        cpu=detect_cpu_name(),
        cpu_threads=cpu_threads,
        ram_total_gb=ram,
        gpus=gpus,
        selected_gpu=gpu,
        model_path=str(Path(model).relative_to(ROOT)) if model and Path(model).is_absolute() and ROOT in Path(model).parents else model,
        model_size_gb=model_gb,
        model_train_ctx=train_ctx_for_model(model),
        ctx_fraction=ctx_fraction,
        n_ctx=n_ctx,
        n_gpu_layers=gpu_layers,
        batch_size=batch,
        n_threads=n_threads,
        max_tokens=max_tokens,
        mode_presets=mode_presets(n_ctx, max_tokens),
        reasoning=notes + [f"Generated max_tokens={max_tokens}."],
    )


def apply_profile(profile: HardwareProfile) -> None:
    """Write hardware profile to disk.

    Hardware-computed values (n_ctx, n_gpu_layers, batch_size) are stored
    under hw_profile_* keys and in runtime_hardware_profile.json.  They are
    NEVER written to the canonical n_ctx / n_gpu_layers / batch_size keys in
    settings.json — those belong to the user and must not be auto-overwritten.

    The GUI load_model() picks up hw_profile_* values as attempt 2 (fallback)
    after the user's explicit settings have been tried first.
    """
    settings = load_settings()
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)

    settings["model_path"] = profile.model_path

    # Hardware recommendation stored under isolated keys only.
    settings["hw_profile_n_ctx"] = profile.n_ctx
    settings["hw_profile_n_gpu_layers"] = profile.n_gpu_layers
    settings["hw_profile_batch_size"] = profile.batch_size

    # Thread count and generation caps are hardware-determined; safe to update.
    settings["n_threads"] = profile.n_threads
    settings["max_tokens"] = profile.max_tokens
    settings["mode_presets"] = profile.mode_presets
    settings["hardware_autotune_enabled"] = True
    settings["hardware_profile"] = asdict(profile)

    SETTINGS_PATH.write_text(json.dumps(settings, indent=2), encoding="utf-8")

    # runtime_hardware_profile.json is the artifact read by load_model()
    # for the hw-profile fallback attempt — keep writing it unchanged.
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(asdict(profile), indent=2), encoding="utf-8")


def main() -> None:
    profile = build_profile()
    apply_profile(profile)
    print(json.dumps(asdict(profile), indent=2))


if __name__ == "__main__":
    main()
