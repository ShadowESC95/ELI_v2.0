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
    forced = os.environ.get("ELI_MODEL_TRAIN_CTX", "").strip()
    if forced:
        return int(forced)

    name = Path(model_path).name.lower()

    if "mistral-small-3.1" in name or "mistral-small" in name:
        return 131072
    if "qwen2.5" in name or "qwen2-5" in name:
        return 32768
    if "qwen3" in name:
        return 32768
    if "qwen2" in name:
        return 32768
    if "llama-3.1" in name or "llama-3.2" in name:
        return 131072
    if "llama-3" in name or "llama3" in name:
        return 8192
    if "mistral-7b" in name:
        return 32768
    if "tinyllama" in name:
        return 2048

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
    # q4 KV approximation. Conservative enough for launch planning.
    return (n_ctx * layers * 1024) / 1048576.0


def round_ctx(raw: int) -> int:
    allowed = [
        2048, 4096, 6144, 8192, 12288, 16384,
        20480, 22528, 24576, 32768, 49152, 65536, 98304, 131072
    ]
    return max(v for v in allowed if v <= max(2048, raw))


def ram_ctx_cap(ram_gb: float, model_gb: float) -> int:
    if ram_gb < 8:
        cap = 2048
    elif ram_gb < 16:
        cap = 4096
    elif ram_gb < 24:
        cap = 8192
    elif ram_gb < 28:
        cap = 16384
    elif ram_gb < 48:
        cap = 24576
    elif ram_gb < 64:
        cap = 32768
    elif ram_gb < 96:
        cap = 49152
    elif ram_gb < 128:
        cap = 65536
    else:
        cap = 131072

    if model_gb >= 30 and ram_gb < 96:
        cap = min(cap, 16384)
    elif model_gb >= 18 and ram_gb < 48:
        cap = min(cap, 16384)

    return cap


def max_tokens_from_ctx(n_ctx: int) -> int:
    if n_ctx >= 8192:
        return 4096
    if n_ctx >= 6144:
        return 3072
    if n_ctx >= 4096:
        return 2048
    return 1024


def mode_presets(n_ctx: int, max_tokens: int) -> Dict[str, Dict[str, Any]]:
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
            "samples": 3 if n_ctx >= 8192 else 2,
            "max_tokens_per_sample": min(max_tokens, 2048),
            "max_tokens_final": min(max_tokens, 3072),
        },
        "tree_of_thoughts": {
            "branches": 3 if n_ctx >= 8192 else 2,
            "depth": 3 if n_ctx >= 16384 else 2,
            "max_tokens_propose": min(1024, max_tokens),
            "max_tokens_develop": min(3072, max_tokens),
            "max_tokens_critique": min(1024, max_tokens),
            "max_tokens_revise": max_tokens,
        },
        "constitutional_ai": {
            "max_tokens_generate": min(3072, max_tokens),
            "max_tokens_critique": min(1024, max_tokens),
            "max_tokens_revise": max_tokens,
            "max_tokens": max_tokens,
        },
    }


def allocate(profile_model: str, model_gb: float, ram_gb: float, gpu: Optional[GPUInfo]) -> tuple[int, int, int, int, float, List[str]]:
    notes: List[str] = []

    train_ctx = train_ctx_for_model(profile_model)
    ctx_fraction = float(os.environ.get("ELI_CTX_FRACTION", "0.65"))
    target_batch = int(os.environ.get("ELI_TARGET_BATCH", "256"))

    forced_ctx = os.environ.get("ELI_FORCE_CTX", "").strip()
    forced_batch = os.environ.get("ELI_FORCE_BATCH", "").strip()
    forced_layers = os.environ.get("ELI_FORCE_GPU_LAYERS", "").strip()

    raw_ctx = int(train_ctx * ctx_fraction)
    rounded_requested_ctx = round_ctx(raw_ctx)
    cap_ctx = ram_ctx_cap(ram_gb, model_gb)
    n_ctx = int(forced_ctx) if forced_ctx else min(rounded_requested_ctx, cap_ctx)
    batch = int(forced_batch) if forced_batch else target_batch

    layers_total = estimate_layers(model_gb)
    per_layer = layer_mb(model_gb, layers_total)

    if gpu is None or gpu.total_mb <= 0:
        notes.append("CPU/no measurable GPU: model remains in RAM/CPU, gpu_layers=0.")
        return n_ctx, 0, min(batch, 128), max_tokens_from_ctx(n_ctx), ctx_fraction, notes

    usable_vram = max(0, gpu.free_mb - int(os.environ.get("ELI_VRAM_RESERVE_MB", "900")))
    target_vram = int(os.environ.get("ELI_VRAM_TARGET_MB", "0") or "0")
    if target_vram > 0:
        usable_vram = min(usable_vram, target_vram)

    runtime_reserve = int(os.environ.get("ELI_RUNTIME_VRAM_RESERVE_MB", "900"))
    kv = kv_cache_mb(n_ctx, layers_total)
    batch_reserve = max(384, int(batch * 3.0))

    remaining = usable_vram - runtime_reserve - kv - batch_reserve

    if forced_layers:
        gpu_layers = int(forced_layers)
    else:
        gpu_layers = max(0, min(layers_total, int(max(0, remaining) // max(per_layer, 1.0))))

    if gpu_layers >= layers_total:
        gpu_layers = 99

    notes.append(
        f"Universal ctx-first allocation: train_ctx={train_ctx}, target_fraction={ctx_fraction:.2f}, "
        f"requested_ctx≈{raw_ctx}, rounded_requested_ctx={rounded_requested_ctx}, "
        f"applied_ctx={n_ctx}, ram_model_cap={cap_ctx}, "
        f"batch={batch}, usable_vram≈{usable_vram}MB, model_gb={model_gb}, "
        f"layers_est={layers_total}, layer_mb≈{per_layer:.1f}."
    )
    notes.append(
        f"VRAM reservations: runtime≈{runtime_reserve}MB, KV≈{kv:.0f}MB, "
        f"batch≈{batch_reserve}MB, remaining_for_layers≈{remaining:.0f}MB, "
        f"gpu_layers={gpu_layers}. Non-offloaded layers use RAM/CPU."
    )

    return n_ctx, gpu_layers, batch, max_tokens_from_ctx(n_ctx), ctx_fraction, notes


def build_profile() -> HardwareProfile:
    settings = load_settings()
    model = find_model(settings)
    model_gb = size_gb(model)

    gpus = detect_gpus()
    gpu = select_gpu(gpus)

    ram = detect_ram_gb()
    cpu_threads = os.cpu_count() or 4
    n_threads = max(2, cpu_threads - 2)

    n_ctx, gpu_layers, batch, max_tokens, ctx_fraction, notes = allocate(model, model_gb, ram, gpu)

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
        reasoning=notes + [f"Generated max_tokens selected: {max_tokens}."],
    )


def apply_profile(profile: HardwareProfile) -> None:
    settings = load_settings()
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)

    settings["model_path"] = profile.model_path
    settings["n_ctx"] = profile.n_ctx
    settings["ctx"] = profile.n_ctx
    settings["n_gpu_layers"] = profile.n_gpu_layers
    settings["gpu_layers"] = profile.n_gpu_layers
    settings["batch_size"] = profile.batch_size
    settings["n_batch"] = profile.batch_size
    settings["n_threads"] = profile.n_threads
    settings["max_tokens"] = profile.max_tokens
    settings["mode_presets"] = profile.mode_presets
    settings["hardware_autotune_enabled"] = True
    settings["hardware_profile"] = asdict(profile)

    SETTINGS_PATH.write_text(json.dumps(settings, indent=2), encoding="utf-8")

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(asdict(profile), indent=2), encoding="utf-8")


def main() -> None:
    profile = build_profile()
    apply_profile(profile)
    print(json.dumps(asdict(profile), indent=2))


if __name__ == "__main__":
    main()
