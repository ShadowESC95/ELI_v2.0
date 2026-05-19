"""
ELI Launcher — hardware-aware model selector with auto-tuned parameters.
"""
from __future__ import annotations
import json
import multiprocessing
import os
import sys
from pathlib import Path

from eli.core.paths import config_dir, models_dir, project_root
from eli.core.runtime_settings import _settings_file, load_settings, save_settings

BASE_DIR = project_root()
MODELS_DIR = models_dir()
CFG_PATH = _settings_file()


# ── Hardware detection ────────────────────────────────────────────────────────

def _detect_hardware() -> dict:
    """
    Detect hardware using FREE VRAM (not total) so GPU layer counts
    are based on what's actually available after the display server loads.

    Runtime configuration delegates to eli.core.hardware_profile.
    when available so CLI, GUI startup, and the executor's HARDWARE_PROFILE
    action all converge on the same answer. Falls back to the inline
    implementation if the canonical helper is unavailable.
    """
    try:
        from eli.core.hardware_profile import detect_hardware as _canonical_detect
        hp = _canonical_detect()
        return {
            "cpu_cores":         hp.cpu_threads,
            "total_ram_gb":      hp.ram_gb,
            "available_ram_gb":  hp.available_ram_gb,
            "vram_mb":           hp.free_vram_mb,
            "vram_total_mb":     hp.total_vram_mb,
            "has_gpu":           hp.has_gpu,
            "gpu_name":          hp.gpu_name or ("CPU only" if not hp.has_gpu else ""),
        }
    except Exception:
        # Fall through to the legacy inline implementation below.
        pass
    hw = {
        "cpu_cores":       multiprocessing.cpu_count(),
        "total_ram_gb":    8.0,
        "available_ram_gb": 8.0,
        "vram_mb":         0,           # free VRAM in MB
        "vram_total_mb":   0,
        "has_gpu":         False,
        "gpu_name":        "CPU only",
    }
    try:
        import psutil
        vm = psutil.virtual_memory()
        hw["total_ram_gb"] = vm.total / 1e9
        hw["available_ram_gb"] = vm.available / 1e9
    except Exception:
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        hw["total_ram_gb"] = int(line.split()[1]) / 1_048_576
                    elif line.startswith("MemAvailable:"):
                        hw["available_ram_gb"] = int(line.split()[1]) / 1_048_576
        except Exception:
            pass

    # Query FREE VRAM — critical: display server consumes VRAM before ELI launches
    try:
        import subprocess
        out = subprocess.check_output(
            ["nvidia-smi",
             "--query-gpu=memory.free,memory.total,name",
             "--format=csv,noheader,nounits"],
            stderr=subprocess.DEVNULL, timeout=5
        ).decode().strip().splitlines()[0]
        parts = [p.strip() for p in out.split(",")]
        hw["vram_mb"]       = int(parts[0])   # FREE VRAM
        hw["vram_total_mb"] = int(parts[1])
        hw["gpu_name"]      = parts[2] if len(parts) > 2 else "NVIDIA GPU"
        hw["has_gpu"]       = True
    except Exception:
        pass
    return hw


def _model_size_category(size_bytes: int) -> str:
    gb = size_bytes / 1e9
    if gb < 1.5:  return "tiny"
    if gb < 3.0:  return "small"
    if gb < 6.0:  return "medium"
    return "large"


# KV-cache overhead constants (same as hardware_profile.py)
_KV_BYTES_PER_TOKEN_PER_LAYER = 6_000
_CUDA_OVERHEAD_MB = 350


def _kv_cache_mb(n_ctx: int, n_layers: int = 32, quant: bool = False) -> float:
    raw = n_ctx * n_layers * _KV_BYTES_PER_TOKEN_PER_LAYER / 1_048_576
    return raw / 4 if quant else raw


def _auto_tune(model_path: Path, hw: dict) -> dict:
    """
    Compute optimal runtime parameters based on FREE VRAM and available RAM.
    Uses KV-cache overhead estimation so GPU layer counts won't OOM.
    Sets max_tokens=-1 (unlimited — use all remaining context window).

    Runtime configuration delegates to eli.core.hardware_profile.recommend().
    when available so the GUI, the executor's HARDWARE_PROFILE action, and any
    other caller converge on the same recommendation. Falls back to the inline
    implementation if the canonical helper is unavailable.
    """
    try:
        from eli.core.hardware_profile import (
            HardwareProfile as _HP,
            recommend as _canonical_recommend,
        )
        canon_hw = _HP(
            cpu_threads=int(hw.get("cpu_cores", 1)),
            ram_gb=float(hw.get("total_ram_gb", 8.0)),
            available_ram_gb=float(hw.get("available_ram_gb", hw.get("total_ram_gb", 8.0))),
            has_gpu=bool(hw.get("has_gpu", False)),
            gpu_name=str(hw.get("gpu_name", "")),
            free_vram_mb=int(hw.get("vram_mb", 0)),
            total_vram_mb=int(hw.get("vram_total_mb", 0)),
            vram_gb=float(hw.get("vram_mb", 0)) / 1024.0,
        )
        rec = _canonical_recommend(
            hw=canon_hw,
            models=[{
                "name": model_path.name,
                "path": str(model_path),
                "size_bytes": model_path.stat().st_size,
                "size_gb": model_path.stat().st_size / 1e9,
            }],
        )
        return {
            "n_ctx":        rec.n_ctx,
            "n_gpu_layers": rec.n_gpu_layers,
            "n_threads":    rec.n_threads,
            "batch_size":   rec.batch_size,
            "max_tokens":   rec.max_tokens,
            "temperature":  rec.temperature,
            "use_mmap":     rec.use_mmap,
            "use_mlock":    rec.use_mlock,
            "cache_type_k": rec.cache_type_k,
            "cache_type_v": rec.cache_type_v,
        }
    except Exception:
        pass
    # Legacy fallback (used only if canonical helper unavailable):
    size_bytes     = model_path.stat().st_size
    size_gb        = size_bytes / 1e9
    free_vram_mb   = hw["vram_mb"]          # free VRAM at startup
    cpu_cores      = hw["cpu_cores"]
    avail_ram_gb   = hw.get("available_ram_gb", hw.get("total_ram_gb", 8.0))

    # Context window: scale with available RAM (not total)
    if avail_ram_gb >= 32:   n_ctx = 8192
    elif avail_ram_gb >= 16: n_ctx = 4096
    else:                    n_ctx = 2048

    # Total transformer layers heuristic
    if size_gb < 1.5:   total_layers = 22
    elif size_gb < 3.0: total_layers = 28
    elif size_gb < 6.0: total_layers = 32
    elif size_gb < 12:  total_layers = 40
    else:               total_layers = 48

    # GPU layers: compute from free VRAM minus KV-cache and CUDA overhead
    if free_vram_mb > 0:
        kv_mb = _kv_cache_mb(n_ctx, total_layers, quant=False)
        available_for_model = free_vram_mb - kv_mb - _CUDA_OVERHEAD_MB
        mb_per_layer = (size_gb * 1024) / (total_layers + 2)
        if available_for_model > 0 and mb_per_layer > 0:
            n_gpu_layers = int(available_for_model / mb_per_layer)
            if n_gpu_layers >= total_layers:
                n_gpu_layers = 9999   # all layers fit — let llama.cpp handle it
        else:
            n_gpu_layers = 0
    else:
        n_gpu_layers = 0

    # CPU threads: leave 2 cores for OS/GUI
    n_threads = max(1, cpu_cores - 2)

    # Batch size: scales with GPU offload
    if n_gpu_layers >= total_layers: n_batch = 512
    elif n_gpu_layers >= 16:         n_batch = 256
    else:                            n_batch = 128

    return {
        "n_ctx":        n_ctx,
        "n_gpu_layers": n_gpu_layers,
        "n_threads":    n_threads,
        "batch_size":   n_batch,
        "max_tokens":   -1,      # unlimited — use full remaining context
        "temperature":  0.7,
        "use_mmap":     True,
        "use_mlock":    avail_ram_gb >= 16,
    }


# ── UI helpers ────────────────────────────────────────────────────────────────

def _print_header():
    print("\n╔══════════════════════════════════════════════════════╗")
    print("║           ELI  ·  Model & Runtime Setup              ║")
    print("╚══════════════════════════════════════════════════════╝")


def _pick_model(models: list[Path]) -> Path:
    print("\n  Available Models")
    print("  " + "─" * 54)
    for i, m in enumerate(models):
        gb   = m.stat().st_size / 1e9
        cat  = _model_size_category(m.stat().st_size)
        print(f"  [{i+1}]  {m.name}")
        print(f"        {gb:.2f} GB  ·  {cat}")
    print("  " + "─" * 54)
    while True:
        try:
            raw = input("\n  Pick model number: ").strip()
            idx = int(raw) - 1
            if 0 <= idx < len(models):
                return models[idx]
        except (ValueError, KeyboardInterrupt):
            print("\nAborted.")
            sys.exit(0)
        print(f"  Please enter 1–{len(models)}")


def _confirm_params(model_path: Path, params: dict, hw: dict) -> dict:
    """Show auto-tuned params, let user edit any."""
    cat = _model_size_category(model_path.stat().st_size)
    gb  = model_path.stat().st_size / 1e9
    print(f"\n  Selected:  {model_path.name}")
    print(f"\n  Hardware:  {hw.get('gpu_name','CPU')}  ·  "
          f"VRAM {hw['vram_mb']} MB  ·  RAM {hw['total_ram_gb']:.1f} GB  ·  "
          f"{hw['cpu_cores']} cores")

    PARAM_KEYS = [
        ("n_ctx",        "Context window (tokens)"),
        ("n_gpu_layers", "GPU-layer load parameter (99=all-layer request)"),
        ("n_threads",    "CPU threads"),
        ("batch_size",   "Batch size"),
        ("max_tokens",   "Max tokens per response"),
        ("temperature",  "Temperature  (0=precise 2=creative)"),
    ]

    while True:
        print(f"\n  Parameters  (auto-tuned · {cat} · {gb:.2f} GB)")
        print("  " + "─" * 54)
        for i, (k, desc) in enumerate(PARAM_KEYS):
            print(f"  [{i+1}]  {k:<16}  {str(params[k]):<10}  {desc}")
        print("  " + "─" * 54)
        raw = input("\n  Enter to confirm  or  param number to edit: ").strip()
        if raw == "":
            break
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(PARAM_KEYS):
                key, desc = PARAM_KEYS[idx]
                new_val = input(f"  New value for {key} [{params[key]}]: ").strip()
                if new_val:
                    params[key] = type(params[key])(new_val)
        except (ValueError, KeyboardInterrupt):
            pass

    print("  ✓  Parameters confirmed.\n")
    return params


# ── Config I/O ────────────────────────────────────────────────────────────────

def _load_config() -> dict:
    try:
        return load_settings()
    except Exception:
        if CFG_PATH.exists():
            try:
                return json.loads(CFG_PATH.read_text())
            except Exception:
                pass
        return {}


def _save_config(cfg: dict):
    for legacy_key in ("gpu_layers", "cpu_threads", "n_batch", "context_size"):
        cfg.pop(legacy_key, None)
    save_settings(cfg)


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    # ── Load config first — determines whether setup UI is needed ────────────
    cfg         = _load_config()
    saved_model = cfg.get("model_path") or cfg.get("bundled_model_path") or ""
    first_run   = not cfg.get("first_run_complete", False)

    # If the GUI startup picker is enabled, skip the terminal pre-load entirely.
    # StartupModelSelectionDialog owns model selection, hw-tuning, and load.
    if cfg.get("show_startup_model_picker", True) and "--setup" not in sys.argv:
        import eli.gui.eli_pro_audio_gui_MKI as _gui_mod
        _gui_mod.main()
        return

    saved_path  = Path(saved_model) if saved_model else None
    force_setup = "--setup" in sys.argv
    silent      = (not first_run) and (not force_setup) and (saved_path is not None) and saved_path.exists()

    # Search recursively so models in models/gguf/base/ are found
    models = sorted(MODELS_DIR.rglob("*.gguf"))
    if not models:
        print(f"❌  No GGUF models found in {MODELS_DIR}")
        sys.exit(1)

    hw = _detect_hardware()

    # On silent (returning) launch: use the persisted config as the source of
    # truth. First install / --setup seeds these values dynamically; later GUI
    # edits update the same config file and must win on subsequent launches.
    if silent:
        model_path = saved_path
        params = _auto_tune(model_path, hw)
        for key in ("n_ctx", "n_gpu_layers", "n_threads", "batch_size",
                    "max_tokens", "temperature", "use_mmap", "use_mlock",
                    "cache_type_k", "cache_type_v"):
            if key in cfg:
                params[key] = cfg[key]
        if "n_batch" in cfg and "batch_size" not in cfg:
            params["batch_size"] = cfg["n_batch"]
        # No interactive prompts — just print a one-liner and continue
        print(f"⏳  ELI  ·  {model_path.name}  "
              f"(ctx={params['n_ctx']} gpu={params['n_gpu_layers']} "
              f"threads={params['n_threads']} batch={params['batch_size']})")
        print(f"    Settings: GUI ⚙ Settings → Runtime  |  "
              f"New model: run with --setup")
    else:
        # ── First run, or saved model file missing: show interactive setup ────
        _print_header()
        model_path = _pick_model(models)
        params     = _auto_tune(model_path, hw)
        params     = _confirm_params(model_path, params, hw)

    # Persist: update model paths + params, mark first run complete
    cfg.update(params)
    cfg["model_path"]          = str(model_path)
    cfg["bundled_model_path"]  = str(model_path)
    cfg["custom_model_path"]   = str(model_path)
    cfg["gguf_model_path"]     = str(model_path)
    cfg["first_run_complete"]  = True
    _save_config(cfg)

    # Load model — with free-VRAM-aware parameters and optional KV quantization
    kv_k = params.get("cache_type_k", "") or ""
    kv_v = params.get("cache_type_v", "") or ""
    kv_tag = f"  kv_k={kv_k}" if kv_k else ""
    print(f"⏳  Loading {model_path.name} ...")
    print(f"    ctx={params['n_ctx']}  gpu_layers={params['n_gpu_layers']}  "
          f"threads={params['n_threads']}  batch={params['batch_size']}"
          f"  max_tokens=auto/context-aware{kv_tag}\n")

    from llama_cpp import Llama
    _llama_kwargs: dict = dict(
        model_path    = str(model_path),
        n_ctx         = int(params["n_ctx"]),
        n_threads     = int(params["n_threads"]),
        n_gpu_layers  = int(params["n_gpu_layers"]),
        n_batch       = int(params["batch_size"]),
        use_mmap      = bool(params.get("use_mmap", True)),
        use_mlock     = bool(params.get("use_mlock", False)),
        verbose       = False,
    )
    if kv_k:
        _llama_kwargs["cache_type_k"] = kv_k
    if kv_v:
        _llama_kwargs["cache_type_v"] = kv_v

    try:
        # ELI_CTX_ENV_AND_FALLBACK_PATCH
        # Respect shell/runtime overrides and degrade safely if llama.cpp cannot allocate.
        import os as _eli_os

        def _eli_int_env(name, default=None):
            raw = _eli_os.environ.get(name)
            if raw is None or str(raw).strip() == "":
                return default
            try:
                return int(str(raw).strip())
            except Exception:
                print(f"⚠️  Ignoring invalid integer env {name}={raw!r}")
                return default

        _env_ctx = _eli_int_env("ELI_GGUF_N_CTX")
        _env_gpu = _eli_int_env("ELI_GGUF_N_GPU_LAYERS")
        _env_batch = _eli_int_env("ELI_GGUF_N_BATCH")

        if _env_ctx is not None:
            _llama_kwargs["n_ctx"] = _env_ctx
        if _env_gpu is not None:
            _llama_kwargs["n_gpu_layers"] = _env_gpu
        if _env_batch is not None:
            _llama_kwargs["n_batch"] = _env_batch

        _free_mb = None
        _total_mb = None

        # ELI_FORCE_CPU=1 — user override to skip GPU entirely. Useful when
        # VRAM is being held by another process or driver state is bad.
        if os.environ.get("ELI_FORCE_CPU", "").strip().lower() in {"1", "true", "yes", "on"}:
            print("ℹ️  ELI_FORCE_CPU=1 — skipping all GPU attempts.")
            _llama_kwargs["n_gpu_layers"] = 0
            _llama_kwargs["n_ctx"] = max(int(_llama_kwargs.get("n_ctx", 0) or 0), 4096)
            os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")
            os.environ.setdefault("GGML_CUDA_NO_DEVICE_INIT", "1")
            _free_mb = 0  # treat as VRAM-tight so the attempt list is CPU-only

        try:
            import subprocess as _eli_subprocess
            _out = _eli_subprocess.check_output(
                [
                    "nvidia-smi",
                    "--query-gpu=name,memory.total,memory.free",
                    "--format=csv,noheader,nounits",
                ],
                text=True,
                stderr=_eli_subprocess.DEVNULL,
            ).strip().splitlines()

            if _out:
                _parts = [x.strip() for x in _out[0].split(",")]
                _gpu_name = _parts[0]
                _total_mb = int(_parts[1])
                _free_mb = int(_parts[2])

                print(f"🧠  GPU detected: {_gpu_name} total={_total_mb}MiB free={_free_mb}MiB")

                # If VRAM is critically low, check for an orphaned previous
                # elix run holding the GPU. nvidia-smi pmon shows compute
                # processes; surface them so the user knows what to kill.
                if _free_mb is not None and _free_mb < 1500:
                    try:
                        _pmon = _eli_subprocess.check_output(
                            ["nvidia-smi",
                             "--query-compute-apps=pid,process_name,used_memory",
                             "--format=csv,noheader,nounits"],
                            text=True,
                            stderr=_eli_subprocess.DEVNULL,
                            timeout=3,
                        ).strip().splitlines()
                        if _pmon:
                            print("🛑 GPU compute processes currently holding VRAM:")
                            for _line in _pmon:
                                print(f"     {_line}")
                            print("   Kill the relevant PID(s) with `kill <PID>` to free GPU memory.")
                    except Exception:
                        pass

                # Critical-VRAM CPU fallback: only when the GPU literally
                # cannot host the model file at all. Threshold is now
                # MODEL-RELATIVE, not a static 1500 MiB number, because the
                # file size is what dictates "can the model even load".
                _model_size_mb = int(model_path.stat().st_size / (1024 * 1024))
                _critical_vram_mb = max(900, int(_model_size_mb * 0.30))
                if _free_mb is not None and _free_mb < _critical_vram_mb:
                    print(
                        f"⚠️  GPU free={_free_mb}MiB is below the model's "
                        f"minimum useful threshold ({_critical_vram_mb}MiB for "
                        f"{model_path.name}). Falling back to CPU."
                    )
                    _llama_kwargs["n_gpu_layers"] = 0
                    import os as _os_cuda
                    _os_cuda.environ.setdefault("CUDA_VISIBLE_DEVICES", "")
                    _os_cuda.environ.setdefault("GGML_CUDA_NO_DEVICE_INIT", "1")
                # Otherwise: trust _auto_tune's hardware_profile.recommend()
                # output. No static ceilings — they shipped over and clamped
                # legitimate hardware-aware tunes.

        except Exception as _e:
            print(f"⚠️  GPU diagnostic skipped: {_e}")

        print(
            "🧠  Effective llama.cpp runtime: "
            f"ctx={_llama_kwargs.get('n_ctx')} "
            f"gpu_layers={_llama_kwargs.get('n_gpu_layers')} "
            f"threads={_llama_kwargs.get('n_threads')} "
            f"batch={_llama_kwargs.get('n_batch')}"
        )

        _base = dict(_llama_kwargs)
        _base_gpu = int(_base.get("n_gpu_layers", 0) or 0)
        _base_ctx = int(_base.get("n_ctx", 4096) or 4096)
        _base_batch = int(_base.get("n_batch", 128) or 128)

        # Each fallback halves the GPU offload and shrinks the context,
        # ending in CPU-only. Values derive from the fresh hardware-aware
        # tune — no fixed ceilings.
        def _half(v: int, floor: int) -> int:
            return max(floor, v // 2)

        _force_cpu = os.environ.get("ELI_FORCE_CPU", "").strip().lower() in {"1", "true", "yes", "on"}
        if _force_cpu or _base_gpu <= 0:
            _load_attempts = [
                dict(_base, n_gpu_layers=0),
                dict(_base, n_gpu_layers=0,
                     n_ctx=max(2048, _base_ctx // 2),
                     n_batch=_half(_base_batch, 32)),
                dict(_base, n_gpu_layers=0, n_ctx=2048, n_batch=32, _force_no_cuda=True),
            ]
        else:
            _load_attempts = [dict(_base)]
            _load_attempts.append(dict(
                _base, n_gpu_layers=_half(_base_gpu, 0),
                n_batch=_half(_base_batch, 64),
            ))
            _load_attempts.append(dict(
                _base, n_gpu_layers=_half(_base_gpu, 0) // 2,
                n_ctx=max(2048, _base_ctx // 2),
                n_batch=_half(_base_batch, 32),
            ))
            _load_attempts.append(dict(
                _base, n_gpu_layers=0, n_ctx=_base_ctx,
                n_batch=_half(_base_batch, 64),
            ))
            _load_attempts.append(dict(
                _base, n_gpu_layers=0, n_ctx=2048, n_batch=32,
                _force_no_cuda=True,
            ))

        _last_error = None
        model = None

        for _i, _attempt in enumerate(_load_attempts, 1):
            try:
                _attempt_kwargs = dict(_attempt)
                _force_no_cuda = bool(_attempt_kwargs.pop("_force_no_cuda", False))
                if _force_no_cuda:
                    import os as _os_lc
                    _os_lc.environ["CUDA_VISIBLE_DEVICES"] = ""
                    _os_lc.environ["GGML_CUDA_NO_DEVICE_INIT"] = "1"
                    _os_lc.environ["GGML_CUDA_FORCE_DMMV"] = "0"
                    print(
                        "⏳  Final CPU attempt with CUDA disabled "
                        "(CUDA_VISIBLE_DEVICES='', GGML_CUDA_NO_DEVICE_INIT=1)"
                    )
                print(
                    f"⏳  Llama load attempt {_i}: "
                    f"ctx={_attempt_kwargs.get('n_ctx')} "
                    f"gpu_layers={_attempt_kwargs.get('n_gpu_layers')} "
                    f"batch={_attempt_kwargs.get('n_batch')}"
                )
                model = Llama(**_attempt_kwargs)
                _llama_kwargs = _attempt_kwargs
                print(
                    f"✅  Llama load OK: "
                    f"ctx={_attempt_kwargs.get('n_ctx')} "
                    f"gpu_layers={_attempt_kwargs.get('n_gpu_layers')} "
                    f"batch={_attempt_kwargs.get('n_batch')}"
                )
                break
            except Exception as _e:
                _last_error = _e
                print(f"⚠️  Llama load attempt {_i} failed: {_e}")

        if model is None:
            # Friendly diagnostic so the user knows what to do.
            _diag = [
                "All llama.cpp load attempts failed.",
                f"Last error: {_last_error}",
                "",
                "Common causes & fixes:",
                "  1. Another process is holding the GPU. Run:",
                "       nvidia-smi   # find the PID",
                "       kill <PID>",
                "     A previously crashed elix often leaves a llama.cpp",
                "     process holding most of the VRAM.",
                "  2. If this happens repeatedly, set ELI_FORCE_CPU=1 in",
                "     your shell to skip GPU attempts entirely:",
                "       export ELI_FORCE_CPU=1",
                "  3. The model file may be corrupted. Re-download:",
                f"       {model_path}",
            ]
            raise RuntimeError("\n".join(_diag))

    except TypeError:
        # Older llama_cpp versions don't accept cache_type_k/v — retry without
        _llama_kwargs.pop("cache_type_k", None)
        _llama_kwargs.pop("cache_type_v", None)
        model = Llama(**_llama_kwargs)

    print(f"✅  {model_path.name} loaded — launching GUI...\n")

    # Hand model to GUI module before it initialises.
    # Add eli/ to path so package-local imports resolve.
    _eli_dir = str(BASE_DIR / "eli")
    if _eli_dir not in sys.path:
        sys.path.insert(0, _eli_dir)

    # Set env vars so gguf_inference / cognitive engine can find the model
    # Effective parameters: what actually loaded (post-clamp / post-fallback).
    # `params` holds the requested tune; `_llama_kwargs` holds the kwargs of
    # the load attempt that actually SUCCEEDED. Downstream introspection must
    # see the effective values so ELI never claims "21 GPU layers" when it
    # actually fell back to CPU because Fallout 4 was holding the VRAM.
    _effective = {
        "model_path":   str(model_path),
        "n_ctx":        int(_llama_kwargs.get("n_ctx", params["n_ctx"])),
        "n_gpu_layers": int(_llama_kwargs.get("n_gpu_layers", params["n_gpu_layers"])),
        "n_threads":    int(_llama_kwargs.get("n_threads", params["n_threads"])),
        "n_batch":      int(_llama_kwargs.get("n_batch", params["batch_size"])),
    }
    _requested = {
        "n_ctx":        int(params["n_ctx"]),
        "n_gpu_layers": int(params["n_gpu_layers"]),
        "n_threads":    int(params["n_threads"]),
        "n_batch":      int(params["batch_size"]),
    }
    _on_gpu = _effective["n_gpu_layers"] > 0
    _load_mode = "GPU" if _on_gpu else "CPU"
    _clamped = (
        _effective["n_ctx"] != _requested["n_ctx"]
        or _effective["n_gpu_layers"] != _requested["n_gpu_layers"]
        or _effective["n_batch"] != _requested["n_batch"]
    )

    import os as _os
    _os.environ["ELI_GGUF_MODEL_PATH"] = str(model_path)
    # Env vars get the EFFECTIVE values so any downstream callers that
    # respect them won't claim runtime info that doesn't match reality.
    _os.environ["ELI_GGUF_N_CTX"]      = str(_effective["n_ctx"])
    _os.environ["ELI_GGUF_THREADS"]    = str(_effective["n_threads"])
    _os.environ["ELI_GGUF_N_GPU_LAYERS"] = str(_effective["n_gpu_layers"])
    _os.environ["ELI_GGUF_N_BATCH"]    = str(_effective["n_batch"])

    # Push the already-loaded model into gguf_inference singleton
    # so cognitive engine / broker use it without reloading.
    try:
        sys.path.insert(0, str(BASE_DIR / "eli"))
        from eli.cognition import gguf_inference as _gi
        _gi._llm = model
        # _last_params is what context_synthesiser reads — set it to the
        # effective values so reports match reality.
        _gi._last_params = dict(_effective)
        # _live_runtime_params is the public snapshot. Carry BOTH the
        # effective and requested values so truth_report / persona brief
        # can show the gap when one exists.
        _gi._live_runtime_params = {
            "provider":        "gguf",
            "model_path":      str(model_path),
            "model_name":      Path(str(model_path)).name,
            "loaded":          True,
            "load_mode":       _load_mode,            # "GPU" or "CPU"
            "on_gpu":          bool(_on_gpu),
            "clamped":         bool(_clamped),
            # Effective (what actually loaded into Llama)
            "n_ctx":           _effective["n_ctx"],
            "n_gpu_layers":    _effective["n_gpu_layers"],
            "n_threads":       _effective["n_threads"],
            "n_batch":         _effective["n_batch"],
            # Explicit requested-vs-effective split for downstream readers
            "requested":       dict(_requested),
            "effective":       dict(_effective),
            "pid":             _os.getpid(),
        }
        # Persist runtime_snapshot.json with the same shape so the
        # deterministic introspection module reads honest values.
        try:
            import json as _json2
            from eli.core.paths import get_paths as _gp2
            snap_path = Path(_gp2().artifacts_dir) / "runtime_snapshot.json"
            snap_path.write_text(
                _json2.dumps(_gi._live_runtime_params, indent=2),
                encoding="utf-8",
            )
        except Exception as _snap_err:
            print(f"⚠️  runtime_snapshot write: {_snap_err}")
        print(f"✅ gguf_inference._llm wired ({_load_mode}, "
              f"ctx={_effective['n_ctx']}, layers={_effective['n_gpu_layers']}"
              f"{', clamped from request' if _clamped else ''})")
        print("✅ gguf_inference singleton wired to preloaded model")
    except Exception as _e:
        print(f"⚠️  gguf_inference wiring: {_e}")

    # Pre-warm the nomic-embed model in a background thread so the first
    # user request doesn't pay the ~90s cold-load penalty.
    def _prewarm_embed():
        try:
            from eli.memory.vector_store import get_vector_store as _gvs
            _vs = _gvs()
            if _vs is not None:
                _emb = _vs._get_embedder()
                if _emb is not None:
                    _emb._get_llm()   # triggers lazy load
                    print("✅ nomic-embed model pre-warmed (background)")
        except Exception as _pe:
            print(f"⚠️  embed pre-warm: {_pe}")

    import threading as _thr
    _thr.Thread(target=_prewarm_embed, daemon=True, name="embed-prewarm").start()

    import eli.gui.eli_pro_audio_gui_MKI as _gui_mod
    _gui_mod._PRELOADED_MODEL      = model
    _gui_mod._PRELOADED_MODEL_PATH = str(model_path)
    # Pass the EFFECTIVE params (what actually loaded) — critical so the
    # GUI's runtime status / introspection / persona brief show reality
    # rather than the pre-clamp request. Requested values are still
    # available via _gi._live_runtime_params["requested"] for diagnostics.
    _gui_mod._PRELOADED_PARAMS     = dict(_effective, batch_size=_effective["n_batch"])
    _gui_mod._PRELOADED_LOAD_MODE  = _load_mode
    _gui_mod._PRELOADED_REQUESTED  = dict(_requested)

    # User-info background updater (inlined from former bottom-of-file
    # User-info startup refresh. Skipped under pytest so test
    # isolation isn't broken.
    if "PYTEST_CURRENT_TEST" not in os.environ:
        try:
            from eli.cognition.user_info_builder import (
                ensure_user_info_background_updater,
                register_user_info_exit_flush,
            )
            register_user_info_exit_flush()
            ensure_user_info_background_updater(1800)
        except Exception as _ui_e:
            print(f"[GUI] user-info background updater not started: {_ui_e}")

    _gui_mod.main()


if __name__ == "__main__":
    main()
