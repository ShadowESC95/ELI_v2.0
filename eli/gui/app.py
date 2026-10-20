"""
ELI Launcher — hardware-aware model selector with auto-tuned parameters.
"""
from __future__ import annotations
import json
import multiprocessing
import os
import sys
from pathlib import Path

from eli.core.paths import models_dir, project_root
from eli.core.runtime_settings import _settings_file, load_settings, save_settings
# KV-cache math and CUDA overhead are imported, not restated. This module used to
# carry its own copy of the constants and the formula, kept "in sync by hand" with a
# comment — the arrangement that let a third copy in startup_hardware_optimizer.py
# drift to a different constant without anything failing.


from eli.utils.log import get_logger
log = get_logger(__name__)

BASE_DIR = project_root()
MODELS_DIR = models_dir()
CFG_PATH = _settings_file()


# ── Tuning ────────────────────────────────────────────────────────────────────

def _auto_tune(model_path: Path) -> dict:
    """What this model loads with on this machine now: the plan gguf_inference.load_model uses
    (eli/core/load_plan.py), as the values the setup screen shows and saves."""
    from eli.cognition.gguf_inference import load_request
    from eli.core import load_plan
    from eli.core.hardware_profile import detect_hardware, mlock_holds
    from eli.core.mem_units import file_size_gib
    plan = load_plan.plan(load_request(model_path)) or load_plan.as_asked(load_request(model_path))
    hw = detect_hardware()
    return {
        "n_ctx":        plan.n_ctx,
        "n_gpu_layers": plan.n_gpu_layers,
        "n_threads":    plan.n_threads,
        "batch_size":   plan.n_batch,
        "max_tokens":   -1,      # a ceiling only: each reply is sized from the window
        "temperature":  0.7,
        "use_mmap":     True,
        "use_mlock":    mlock_holds(file_size_gib(model_path), float(hw.available_ram_gb)),
        "cache_type_k": plan.cache_type_k,
        "cache_type_v": plan.cache_type_v,
    }


# ── UI helpers ────────────────────────────────────────────────────────────────

def _print_header():
    print("\n╔══════════════════════════════════════════════════════╗")
    print("║           ELI  ·  Model & Runtime Setup              ║")
    print("╚══════════════════════════════════════════════════════╝")


def _pick_model(models: list[Path]) -> Path:
    print("\n  Available Models")
    print("  " + "─" * 54)
    from eli.core.mem_units import bytes_to_gib
    for i, m in enumerate(models):
        print(f"  [{i+1}]  {m.name}")
        print(f"        {bytes_to_gib(m.stat().st_size):.2f} GB")
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


def _confirm_params(model_path: Path, params: dict) -> dict:
    """Show auto-tuned params, let user edit any."""
    from eli.core.hardware_profile import detect_hardware
    from eli.core.mem_units import bytes_to_gib
    hw = detect_hardware()
    gb = bytes_to_gib(model_path.stat().st_size)
    print(f"\n  Selected:  {model_path.name}")
    print(f"\n  Hardware:  {hw.gpu_name or 'CPU'}  ·  "
          f"VRAM {hw.free_vram_mb} MB free  ·  RAM {hw.ram_gb:.1f} GB  ·  "
          f"{hw.cpu_cores or hw.cpu_threads} cores")

    PARAM_KEYS = [
        ("n_ctx",        "Context window (tokens)"),
        ("n_gpu_layers", "GPU-layer load parameter (-1 = every layer)"),
        ("n_threads",    "CPU threads"),
        ("batch_size",   "Batch size"),
        ("max_tokens",   "Max tokens per response"),
        ("temperature",  "Temperature  (0=precise 2=creative)"),
    ]

    while True:
        print(f"\n  Parameters  (auto-tuned · {gb:.2f} GB)")
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
            log.debug("suppressed exception", exc_info=True)

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
                log.debug("suppressed exception", exc_info=True)
        return {}


def _save_config(cfg: dict):
    for legacy_key in ("gpu_layers", "cpu_threads", "n_batch", "context_size"):
        cfg.pop(legacy_key, None)
    save_settings(cfg)


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    # An extension that drops references to None cannot abort the window (eli/core/singleton_refs.py).
    try:
        from eli.core.singleton_refs import pin_singletons
        pin_singletons()
    except Exception:
        log.debug("suppressed exception", exc_info=True)
    # Pin THIS install's root for the `eli`/`eli-gui` console scripts. They enter here
    # directly (not via RUN_ELI.sh, which already exports ELI_PROJECT_ROOT), so without
    # this the runtime paths resolve via _find_project_root() and can leak into ANOTHER
    # ELI checkout on the same machine — observed: a fresh portable install writing its
    # DB into a dev tree, so it wasn't a blank slate and onboarding was skipped. Derive
    # the root from the venv running us (…/<root>/.venv/bin/python → <root>) and pin it.
    try:
        import os as _os, sys as _sys
        from pathlib import Path as _P
        # NOT .resolve() — the venv's bin/python is a symlink to the system
        # python; resolving it walks OUT of the checkout (root became "/", so
        # the pin silently no-op'd and a stale env leaked through).
        _root = _P(_sys.executable).parents[2]  # bin/python → .venv → root
        if (_root / "eli" / "gui").is_dir() and _os.environ.get("ELI_PROJECT_ROOT", "") != str(_root):
            # The venv you launched owns the root; overwrite any stale/foreign
            # value so this checkout never writes into another checkout's folders.
            _os.environ["ELI_PROJECT_ROOT"] = str(_root)
            _os.environ["ELI_DATA_DIR"] = str(_root / "artifacts")
            _os.environ["ELI_CONFIG_DIR"] = str(_root / "config")
            _os.environ["ELI_MODELS_DIR"] = str(_root / "models")
    except Exception:
        log.debug("suppressed exception", exc_info=True)
    # ── First-run/boot DB + machine-inventory bootstrap (idempotent) ─────────
    # The `eli`/`eli-gui` console scripts enter here directly (bypassing
    # eli.__main__), so ensure the full schema + app index exist even when ELI
    # was not launched via install.sh. Process-once guarded; never fatal.
    try:
        from eli.core.init_data import bootstrap_once
        bootstrap_once()
    except Exception:
        import logging
        logging.getLogger("eli.boot").debug("GUI boot bootstrap skipped", exc_info=True)

    # A database folder this user cannot write to is fatal, but it is also
    # entirely self-inflicted-by-sudo and trivially fixable — so say so plainly.
    # Without this the first symptom is a raw sqlite3 traceback thrown during a
    # GUI module import, which reads like a crash rather than a permissions
    # problem the user can solve in one command.
    try:
        from eli.core.init_data import store_blocker
        _blocker = store_blocker()
    except Exception:
        _blocker = None
    if _blocker:
        print(f"\n{_blocker}\n", file=sys.stderr)
        try:  # windowed launches (AppImage, desktop icon) have no visible stderr
            from PySide6.QtWidgets import QApplication, QMessageBox
            _app = QApplication.instance() or QApplication(sys.argv)
            QMessageBox.critical(None, "ELI — cannot write to its data folder", _blocker)
        except Exception:
            log.debug("could not show data-folder blocker dialog", exc_info=True)
        return 1

    # ── Load config first — determines whether setup UI is needed ────────────
    cfg         = _load_config()
    saved_model = cfg.get("model_path") or cfg.get("bundled_model_path") or ""
    first_run   = not cfg.get("first_run_complete", False)

    # Activate GPU pack before any code imports bundled llama_cpp (AppImage/portable).
    try:
        from eli.core.gpu_pack_runtime import try_activate_gpu_pack
        try_activate_gpu_pack(verify=True)
    except Exception:
        log.debug("GPU pack early activation skipped", exc_info=True)

    # If the GUI startup picker is enabled, skip the terminal pre-load entirely.
    # StartupModelSelectionDialog owns model selection, hw-tuning, and load.
    if cfg.get("show_startup_model_picker", True) and "--setup" not in sys.argv:
        import eli.gui.eli_pro_audio_gui_v2_0 as _gui_mod
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

    # On silent (returning) launch: use the persisted config as the source of
    # truth. First install / --setup seeds these values dynamically; later GUI
    # edits update the same config file and must win on subsequent launches.
    if silent:
        model_path = saved_path
        params = _auto_tune(model_path)
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
        params     = _auto_tune(model_path)
        params     = _confirm_params(model_path, params)

    # Persist: update model paths + params, mark first run complete
    cfg.update(params)
    cfg["model_path"]          = str(model_path)
    cfg["bundled_model_path"]  = str(model_path)
    cfg["custom_model_path"]   = str(model_path)
    cfg["gguf_model_path"]     = str(model_path)
    cfg["first_run_complete"]  = True
    _save_config(cfg)

    # The same load the window and the server make: the plan for this machine now, the saved
    # values as the request (gguf_inference.load_model writes what loaded to runtime_snapshot.json).
    from eli.cognition import gguf_inference as _gi
    print(f"⏳  Loading {model_path.name} ...")
    request = _gi.load_request(
        model_path,
        n_ctx=int(params.get("n_ctx") or 0),
        n_gpu_layers=int(params["n_gpu_layers"]) if params.get("n_gpu_layers") is not None else None,
        n_batch=int(params.get("batch_size") or 512),
        n_threads=int(params.get("n_threads") or 0),
        cache_type_k=str(params.get("cache_type_k") or ""),
        cache_type_v=str(params.get("cache_type_v") or ""),
        use_mmap=bool(params.get("use_mmap", True)),
        use_mlock=bool(params.get("use_mlock", False)),
    )
    _gi.load_model(force_reload=True, request=request)
    _report = _gi.get_effective_runtime_report()
    print(f"✅  {model_path.name} loaded: {(_report.get('load_plan') or {}).get('text', '')}\n")

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

    import eli.gui.eli_pro_audio_gui_v2_0 as _gui_mod

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
            log.debug(f"[GUI] user-info background updater not started: {_ui_e}")

    _gui_mod.main()


if __name__ == "__main__":
    main()
