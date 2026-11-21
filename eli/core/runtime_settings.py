from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, Optional

try:
    from eli.core.portable_paths import PROJECT_ROOT, make_portable_path_value, resolve_path_value
except Exception:
    PROJECT_ROOT = Path(__file__).resolve().parents[2]

    def resolve_path_value(value: Any, root: str | Path | None = None) -> Any:
        if not isinstance(value, str) or not value.strip() or "://" in value:
            return value
        expanded = os.path.expandvars(os.path.expanduser(value.strip()))
        p = Path(expanded)
        if p.is_absolute():
            return str(p)
        return str((Path(root or PROJECT_ROOT).resolve() / p).resolve())

    def make_portable_path_value(value: Any, root: str | Path | None = None) -> Any:
        if not isinstance(value, str) or not value.strip() or "://" in value:
            return value
        root_path = Path(root or PROJECT_ROOT).resolve()
        try:
            return str(Path(value).expanduser().resolve().relative_to(root_path)).replace("\\", "/")
        except Exception:
            return value

from eli.core.paths import get_paths


from eli.utils.log import get_logger
log = get_logger(__name__)

# Keys in settings.json that store filesystem paths to model files/dirs.
_MODEL_PATH_KEYS = {
    "model_path", "bundled_model_path", "custom_model_path",
    "gguf_model_path", "image_model_path",
}


def _settings_file() -> Path:
    # 1. Explicit file overrides (dev, tests, portable installs).
    # ELI_SETTINGS_FILE is canonical; ELI_SETTINGS_PATH is a compatibility alias.
    env = os.environ.get("ELI_SETTINGS_FILE") or os.environ.get("ELI_SETTINGS_PATH")
    if env:
        return Path(env).expanduser().resolve()

    # 2. Explicit config-directory override.
    config_dir = os.environ.get("ELI_CONFIG_DIR")
    if config_dir:
        return (Path(config_dir).expanduser().resolve() / "settings.json").resolve()

    # 3. Canonical: project-relative in dev mode, platformdirs user_config otherwise.
    # This is resolved once by core.paths; do not second-guess it here.
    try:
        return (get_paths().config_dir / "settings.json").resolve()
    except Exception:
        log.debug("suppressed exception", exc_info=True)

    # 4. Final fallback.
    return (PROJECT_ROOT / "config" / "settings.json").resolve()


SETTINGS_FILE = _settings_file()

# n_ctx 0 is "auto": sized for the model in use on this machine when it is read
# (config.get_gguf_n_ctx). A fixed number here was every new user's "setting".
AUTO_N_CTX: int = 0

# Canonical keys. Legacy duplicates (`gpu_layers`, `cpu_threads`) are migrated
# into these on first load and then removed from the file.
DEFAULTS: Dict[str, Any] = {
    "provider": "custom_gguf",
    "model_path": "",
    "bundled_model_path": "",
    "custom_model_path": "",
    "ollama_host": "http://localhost:11434",
    "ollama_model": "",
    "persona_file": "",
    "user_name": "",
    "user_text_color": "#4DA3FF",
    "image_style_profile": "auto",
    "image_palette_profile": "auto",
    "image_profile_notes": "",
    "image_backend": "auto",
    "image_model_path": "",
    "image_device": "auto",
    "image_quality_preset": "ultra",
    "image_steps": 36,
    "image_guidance": 7.2,
    "image_negative_prompt": "",
    "image_default_project_path": "",
    "image_default_count": 1,
    "image_default_width": 1400,
    "image_default_height": 900,
    "image_auto_personalize": True,
    "image_auto_open": True,
    "image_use_chat_context": True,
    "image_use_proactive_context": True,
    "n_ctx": AUTO_N_CTX,
    "max_tokens": 4096,
    "temperature": 0.7,
    "top_p": 0.95,
    "top_k": 40,
    "repeat_penalty": 1.1,
    "n_gpu_layers": 0,
    # auto | gpu | cpu — operator choice from the startup dialog. CPU forces
    # zero GPU layers; GPU tries offload when a backend is present.
    "compute_mode": "auto",
    "moe_expert_offload": "auto",
    # Which model the pinned n_gpu_layers was chosen for. A layer count is absolute: 7 layers is a
    # sensible slice of a 15.66GB model on 8GB and crippling for a 4GB model whose 32 layers all fit.
    # Empty means unknown provenance, treated as not pinned for this model.
    "n_gpu_layers_model": "",
    "n_gpu_layers_source": "",
    # 0 = auto (recommend_cpu_threads)
    "n_threads": 0,
    "batch_size": 512,
    # Fraction of available RAM for model weights + KV (startup dialog, 10–75%).
    "ram_budget_percent": 60,
    # Hardware fit priority: balanced | max_gpu | max_ctx (startup dialog).
    "fit_priority": "balanced",
    "use_mmap": True,
    "use_mlock": False,
    # Multi-GPU split (optional; empty = single GPU). tensor_split is a comma list of per-GPU
    # weights ("0.5,0.5"), split_mode is none|layer|row, main_gpu is the primary device index. From
    # here or config/gpu_profiles.json; used only when set and more than one GPU is present.
    "tensor_split": "",
    "main_gpu": 0,
    "split_mode": "",
    # GPUs the model may use, by llama.cpp device index ("0,1"); "" = every GPU (start-up window).
    "gpu_devices": "",
    "gpu_profiles_file": "",
    # Deep thinking on the answer call for models whose chat template has a reasoning channel
    # (detected from metadata, not names). On is higher quality and slower. Utility calls (routing,
    # JSON, summary) never think. No effect on non-reasoning models. GUI-toggleable.
    "model_thinking": True,
    "cache_type_k": "",
    "cache_type_v": "",
    "auto_speak": False,
    "tts_voice": "en_US-amy-medium",
    "tts_engine": "piper",
    # Smart-home hub identity on Bluetooth pairing screens (TVs, speakers). Empty
    # bluetooth_display_name → "Eli · {hub_zone}". Override for a fixed label.
    "hub_zone": "Home",
    "bluetooth_display_name": "",
    # User labels for speakers/outputs — voice: "play to kitchen speaker", "device 1".
    "audio_output_aliases": {},
    # Stable custom names for voice control — keys: dev:{id}, sink:{MAC}, bt:{MAC}.
    "device_custom_names": {},
    "mic_enabled": False,
    "auto_save": True,
    "log_to_file": False,
    "auto_load": True,
    "first_run_complete": False,
    "theme": "dark",
    "searxng_url": "",
    # Gaze dwell-click (accessibility): rest your gaze on a target and it clicks, a hands-free and
    # voice-free path. Off by default (auto-click is intrusive); turn on in Settings or by voice
    # ("enable gaze clicking"). Needs gaze calibrated and running.
    "gaze_dwell_click": False,
    "gaze_dwell_seconds": 1.0,      # hold your gaze this long before it clicks
    "gaze_dwell_radius": 60,        # px the gaze may wander and still count as "held"
    "gaze_dwell_min_confidence": 0.35,
    # Local vision (model-agnostic, llama-cpp, hot-swaps with the text model). Empty paths
    # auto-discover any projector-paired VL GGUF in the models dir. Override with these keys or
    # ELI_VISION_MODEL / ELI_VISION_MMPROJ. The chat handler comes from the filename or
    # vision_chat_handler.
    "vision_enabled": True,
    "vision_model_path": "",
    "vision_mmproj_path": "",
    "vision_chat_handler": "",
    "vision_n_ctx": 4096,
    "vision_n_gpu_layers": -1,
    "vision_n_batch": 256,
    # GPU clip segfaults on some CUDA cards (e.g. compute capability 7.5); keep the
    # vision encoder on CPU. The language decoder still uses the GPU.
    "vision_clip_on_gpu": False,
    "vision_max_image_px": 1280,
    "vision_max_tokens": 512,
    "vision_temperature": 0.2,
    "vision_repeat_penalty": 1.3,
    # Fast glance model — local GGUF, no API. Used for ambient glances + quick
    # "what's on my screen"; falls back to the primary model. Empty = auto-discover
    # the smallest projector-paired VL GGUF. Model-agnostic (no name hardcoded).
    "vision_fast_enabled": True,
    "vision_fast_model_path": "",
    "vision_fast_mmproj_path": "",
    "vision_fast_chat_handler": "",
    "vision_fast_n_ctx": 2048,
    "vision_fast_n_gpu_layers": -1,
    # Co-resident (no model swap) — big latency win; enable once 8GB VRAM fit
    # is confirmed with both models loaded.
    "vision_fast_no_swap": False,
    # Co-resident vision: load the fast (Moondream) model before the text model and keep it
    # resident so glances need no swap (~3.5s). The text model is then sized to the VRAM left
    # (smart_fit_config: layers -> batch -> ctx). Default off, a bad fit degrades, never strands.
    "vision_coresident": False,
    # Fuse OCR (exact text) + Moondream (visual gist) with the text model into an
    # accurate, grounded screen description — compensates for Moondream's
    # inability to read dense UI text. Evidence-only; never invents.
    "vision_fuse_with_text_model": True,
    "vision_default_prompt": "",
    # Ambient vision: periodic screen glances for rolling awareness. OFF by
    # default — with the hot-swap model each glance briefly unloads the text
    # model, so keep the interval generous (seconds).
    "ambient_vision_enabled": False,
    "ambient_vision_interval": 300,

    # Optional UI grounding — 100% local GGUF (Phi-Ground/OS-Atlas/UGround/UI-TARS).
    "ui_ground_backend": "none",
    "ui_ground_model_path": "",
    "computer_use_backend": "none",
    "computer_use_model_path": "",
    "allow_remote_grounding": False,
    "screen_locate_backends": ["atspi", "vl_ground", "ocr"],
    # Screen analysis depth + context fusion (all local).
    "screen_analysis_depth": "standard",
    "screen_analysis_use_memory": True,
    "screen_analysis_use_research": True,
    "screen_analysis_always_memory": False,
    # Allow proactive habit rules to run shell commands. On by default (your own
    # habits); set false to block shell execution from an untrusted/imported habit DB.
    "habit_shell_enabled": True,
}

# every layer, as llama.cpp counts it; older settings files wrote 99
ALL_GPU_LAYERS = -1
_LEGACY_ALL_GPU_LAYERS = 99


def pinned_gpu_layers_for_model(model_path, settings=None, current_ctx=None):
    """The user's pinned n_gpu_layers -- but only if it applies to THIS model
    AT THIS CONTEXT WINDOW.

    n_gpu_layers is an ABSOLUTE count, so a number chosen for one model means
    something entirely different on the next: 7 layers is a reasonable slice of a
    15.66GB 27B on 8GB of VRAM, and a crippling one for a 4GB model whose 32
    layers all fit in VRAM. Nothing recorded which model a pin came from, so it
    followed the user across model swaps and silently stranded them on the CPU
    while the tuner -- which had measured the right answer -- stood down.

    The same is true across ctx changes on the SAME model, and it is not
    hypothetical: n_gpu_layers is only ever a valid ceiling as a measurement
    of "what fits", and KV cache for every layer lives on GPU regardless of
    offload, so it scales with ctx directly -- a count measured at ctx=2048
    can mean "7 layers fit with room to spare" and, unchanged, become "only 2
    layers actually fit" the moment ctx grows to 12200, because the KV cache
    for the OTHER 46 layers is now eating VRAM the small-ctx measurement never
    had to account for. Before n_gpu_layers was enforced as a ceiling this was
    harmless (the loader silently recomputed a fresh number regardless of what
    was "requested"); once it IS enforced (see hardware_profile.smart_fit_config's
    user_gpu_layers), blindly reusing a small-ctx pin at a much larger ctx
    forces batch and ctx itself to be crushed far harder than necessary to
    squeeze under a ceiling that was never actually calibrated for the ctx
    now in play. So the pin is invalidated -- exactly like a model mismatch --
    whenever the ctx it was measured at is on record and differs from the
    ctx about to be used; the tuner then measures fresh, for THIS ctx, same as
    a model swap already does.

    Returns None when the pin does not apply, meaning "let the tuner measure".

    "All layers" (ALL_GPU_LAYERS, llama.cpp's -1) is
    deliberately exempt: it is a POLICY rather than a measurement, it is correct
    on every model and every ctx, and the loader already reduces it to fit.
    Treating it as stale would quietly downgrade "try them all, then fall
    back" into "use the fallback", which is a different and worse behaviour
    on capable hardware.

    Lives here, not in the GUI, because the desktop app is not the only loader:
    the server/API path (and the mobile client riding the same /v1) resolves the
    same setting and needs the same answer.

    A count the operator exported (ELI_GGUF_N_GPU_LAYERS, ELI_N_GPU_LAYERS,
    ELI_GPU_LAYERS) comes first and applies to every model, as the other exported
    load variables do, until the user sets a count in the app (exported_gpu_layers).
    """
    exported = exported_gpu_layers()
    if exported is not None:
        return exported
    s = settings if settings is not None else (load_settings() or {})
    try:
        pin = int(s.get("n_gpu_layers") or 0)
    except Exception:
        return None
    if not pin:
        return None
    if pin < 0:
        return ALL_GPU_LAYERS
    # A count the tuner wrote is a measurement, not the operator's choice. Treating it as a pin
    # made one low reading (RAM briefly short) cap every later launch. Older files carry no
    # source, so a pin identical to the tuner's mirror is taken to be the tuner's.
    source = str(s.get("n_gpu_layers_source") or "").strip().lower()
    if source == "tuner":
        return None
    if not source:
        try:
            if int(s.get("hw_profile_n_gpu_layers") or 0) == pin:
                return None
        except Exception:
            pass
    recorded = model_identity_key(s.get("n_gpu_layers_model"))
    current = model_identity_key(model_path)
    if not (recorded and current and recorded == current):
        return None
    if current_ctx is not None:
        try:
            recorded_ctx = int(s.get("n_gpu_layers_ctx") or 0)
        except Exception:
            recorded_ctx = 0
        if recorded_ctx and int(current_ctx) != recorded_ctx:
            return None
    return pin


def model_identity_key(model_path) -> str:
    """Comparable identity for a model file, portable across the three OSes.

    os.path.basename alone was wrong twice over for a redistributed app:

      * It splits on the HOST separator, so a Windows path that reached a POSIX
        reader (a synced settings file, a config written elsewhere) came back
        whole and never matched. Both separators are handled here regardless of
        the running OS.
      * It is case-SENSITIVE, while NTFS and the default macOS filesystem are
        not. "Phi3.gguf" and "phi3.gguf" are the same file to those users, and
        comparing them exactly silently discarded a pin the user had just set --
        on every single load.
    """
    raw = str(model_path or "").strip().replace("\\", "/")
    return raw.rsplit("/", 1)[-1].strip().casefold()


# Every variable of a setting, in the order load_settings applies them: a later one wins, so the name
# the loader reads first (the ELI_GGUF_ one) is listed last. Which value governs, the variable's or
# the saved one, is set out above apply_env.
ENV_TO_KEY = {
    "ELI_PROVIDER": "provider",
    "ELI_MODEL_PATH": "model_path",
    "ELI_GGUF_MODEL_PATH": "model_path",
    "ELI_BUNDLED_MODEL_PATH": "bundled_model_path",
    "ELI_CUSTOM_MODEL_PATH": "custom_model_path",
    "ELI_OLLAMA_HOST": "ollama_host",
    "ELI_OLLAMA_MODEL": "ollama_model",
    "ELI_PERSONA_FILE": "persona_file",
    "ELI_USER_NAME": "user_name",
    "ELI_USER_TEXT_COLOR": "user_text_color",
    "ELI_N_CTX": "n_ctx",
    "ELI_GGUF_N_CTX": "n_ctx",
    "ELI_MAX_TOKENS": "max_tokens",
    "ELI_TEMPERATURE": "temperature",
    "ELI_TOP_P": "top_p",
    "ELI_TOP_K": "top_k",
    "ELI_REPEAT_PENALTY": "repeat_penalty",
    "ELI_N_GPU_LAYERS": "n_gpu_layers",
    "ELI_GPU_LAYERS": "n_gpu_layers",         # legacy env name; same canonical key
    "ELI_GGUF_N_GPU_LAYERS": "n_gpu_layers",
    "ELI_N_THREADS": "n_threads",
    "ELI_CPU_THREADS": "n_threads",           # legacy env name
    "ELI_GGUF_THREADS": "n_threads",
    "ELI_BATCH_SIZE": "batch_size",
    "ELI_GGUF_N_BATCH": "batch_size",
    "ELI_USE_MMAP": "use_mmap",
    "ELI_GGUF_USE_MMAP": "use_mmap",
    "ELI_USE_MLOCK": "use_mlock",
    "ELI_GGUF_USE_MLOCK": "use_mlock",
    "ELI_TENSOR_SPLIT": "tensor_split",
    "ELI_GGUF_TENSOR_SPLIT": "tensor_split",
    "ELI_MAIN_GPU": "main_gpu",
    "ELI_GGUF_MAIN_GPU": "main_gpu",
    "ELI_SPLIT_MODE": "split_mode",
    "ELI_GGUF_SPLIT_MODE": "split_mode",
    "ELI_GPU_DEVICES": "gpu_devices",
    "ELI_RAM_BUDGET_PERCENT": "ram_budget_percent",
    "ELI_FIT_PRIORITY": "fit_priority",
    "ELI_GPU_PROFILES_FILE": "gpu_profiles_file",
    "ELI_MODEL_THINK": "model_thinking",
    "ELI_AUTO_SPEAK": "auto_speak",
    "ELI_MIC_ENABLED": "mic_enabled",
    "ELI_AUTO_SAVE": "auto_save",
    "ELI_LOG_TO_FILE": "log_to_file",
    "ELI_AUTO_LOAD": "auto_load",
    "ELI_THEME": "theme",
}

# Legacy keys to migrate and then remove from the file.
LEGACY_KEY_MIGRATIONS = {
    "gpu_layers": "n_gpu_layers",
    "cpu_threads": "n_threads",
}

INT_KEYS = {
    "n_ctx", "max_tokens", "top_k", "n_gpu_layers", "n_threads", "batch_size",
    "image_default_count", "image_default_width", "image_default_height",
    "image_steps",
}
FLOAT_KEYS = {"temperature", "top_p", "repeat_penalty", "image_guidance"}
BOOL_KEYS = {"use_mmap", "use_mlock", "auto_speak", "mic_enabled",
             "auto_save", "log_to_file", "auto_load", "first_run_complete",
             "image_auto_personalize", "image_auto_open",
             "image_use_chat_context", "image_use_proactive_context",
             "model_thinking"}

_MIGRATION_LOGGED = False
_HEAL_LOGGED = False
# True when the last load found the settings file but couldn't parse it, so defaults were used
# silently. Different from a first run with no file. Anything that shows settings should check
# settings_file_was_corrupt_on_last_load() instead of presenting defaults as read from disk.
_LAST_LOAD_SETTINGS_FILE_CORRUPT = False


def settings_file_was_corrupt_on_last_load() -> bool:
    return _LAST_LOAD_SETTINGS_FILE_CORRUPT


def _coerce_value(key: str, value: Any) -> Any:
    if key in BOOL_KEYS:
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}
    if key in INT_KEYS:
        try:
            return int(value)
        except Exception:
            return DEFAULTS.get(key)
    if key in FLOAT_KEYS:
        try:
            return float(value)
        except Exception:
            return DEFAULTS.get(key)
    return value


def _tuner_threads_to_auto(out: Dict[str, Any]) -> None:
    """Until 2.5.18 the tuner saved its own thread count (logical threads less one or two); 0 now
    means the physical cores, and a count the tuner wrote goes back to that. On a 6-core, 12-thread
    processor the saved 10 measured no faster than 6 and kept every core busy while ELI answered."""
    logical = os.cpu_count() or 0
    try:
        n = int(out.get("n_threads") or 0)
    except (TypeError, ValueError):
        return
    if n and n in (logical - 1, logical - 2):
        out["n_threads"] = 0


# One-time changes to a saved file, in order; the file records how many it has had, so a value the
# user sets afterwards is left alone.
_REVISIONS = (_tuner_threads_to_auto,)


def _migrate_legacy_keys(data: Dict[str, Any]) -> tuple[Dict[str, Any], list[str]]:
    """Fold legacy keys into canonical ones. Returns (migrated_data, list_of_migrated_keys)."""
    migrated: list[str] = []
    out = dict(data)
    for old_key, new_key in LEGACY_KEY_MIGRATIONS.items():
        if old_key in out:
            # Only copy the legacy value if the canonical key is absent OR matches default.
            # Prefer the canonical value if both exist (user edited GUI -> n_gpu_layers).
            if new_key not in out:
                out[new_key] = out[old_key]
            del out[old_key]
            migrated.append(old_key)
    return out, migrated


def _bring_up_to_date(data: Dict[str, Any]) -> tuple[Dict[str, Any], list[str]]:
    """Legacy keys folded in, then the one-time revisions the file has not had yet."""
    out, migrated = _migrate_legacy_keys(data)
    try:
        done = int(out.get("settings_revision") or 0)
    except (TypeError, ValueError):
        done = 0
    for step in _REVISIONS[done:]:
        step(out)
    if done < len(_REVISIONS):
        out["settings_revision"] = len(_REVISIONS)
        migrated.append("settings_revision")
    return out, migrated


def _resolve_relative_model_paths(settings: Dict[str, Any]) -> Dict[str, Any]:
    """Convert portable model path values to absolute paths for this machine."""
    out = dict(settings)
    for key in _MODEL_PATH_KEYS:
        val = out.get(key, "")
        if not val or not isinstance(val, str):
            continue
        out[key] = resolve_path_value(val, PROJECT_ROOT)
    return out


def _portable_settings_for_storage(settings: Dict[str, Any]) -> Dict[str, Any]:
    """Store project-owned paths as relative values so settings move machines."""
    out = dict(settings)
    for key in _MODEL_PATH_KEYS:
        if key in out:
            out[key] = make_portable_path_value(out[key], PROJECT_ROOT)
    return out


def _heal_model_paths(settings: Dict[str, Any]) -> tuple[Dict[str, Any], bool]:
    """
    Detect stale absolute paths (e.g. from a different machine) and relocate
    them by searching for the same filename under the current project root.
    Returns (healed_settings, changed).
    """
    global _HEAL_LOGGED
    gguf_search = [
        PROJECT_ROOT / "models" / "gguf" / "base",
        PROJECT_ROOT / "models" / "gguf",
        PROJECT_ROOT / "models",
    ]
    image_search = [
        PROJECT_ROOT / "models" / "image",
        PROJECT_ROOT / "models",
    ]

    changed = False
    out = dict(settings)

    for key in _MODEL_PATH_KEYS:
        val = out.get(key, "")
        if not val or not isinstance(val, str):
            continue
        p = Path(val)
        if not p.is_absolute() or p.exists():
            continue  # relative (already resolved) or already valid

        filename = p.name
        if not filename:
            continue

        dirs = image_search if key == "image_model_path" else gguf_search
        found: str | None = None

        for d in dirs:
            # exact filename match (file or directory for image models)
            candidate = d / filename
            if candidate.exists():
                found = str(candidate)
                break
            # for image models, also search subdirs by name
            if key == "image_model_path" and d.exists():
                for item in d.iterdir():
                    if item.name == filename and item.is_dir():
                        found = str(item)
                        break
            if found:
                break

        if found:
            if not _HEAL_LOGGED:
                log.debug(f"[SETTINGS] Healed stale path '{key}': {val} → {found}")
            out[key] = found
            changed = True

    # Re-sync model_path if it's now stale but a sibling key was healed
    mp = out.get("model_path", "")
    if not mp or (mp and not Path(mp).exists()):
        for fallback in ("custom_model_path", "bundled_model_path", "gguf_model_path"):
            fb_val = out.get(fallback, "")
            if fb_val and Path(fb_val).exists():
                out["model_path"] = fb_val
                changed = True
                break

    if changed and not _HEAL_LOGGED:
        _HEAL_LOGGED = True

    return out, changed


def _load_settings_unsanitized(*, apply_env_overlay: bool = True) -> Dict[str, Any]:
    global _MIGRATION_LOGGED, _LAST_LOAD_SETTINGS_FILE_CORRUPT
    settings = dict(DEFAULTS)
    settings_file = _settings_file()

    raw: Dict[str, Any] = {}
    _LAST_LOAD_SETTINGS_FILE_CORRUPT = False
    if settings_file.exists():
        try:
            parsed = json.loads(settings_file.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                raw = parsed
            else:
                _LAST_LOAD_SETTINGS_FILE_CORRUPT = True
        except Exception as exc:
            _LAST_LOAD_SETTINGS_FILE_CORRUPT = True
            log.warning(
                "[SETTINGS] %s exists but could not be parsed (%s) — falling back "
                "to built-in defaults, NOT your saved configuration",
                settings_file, exc,
            )

    # Migrate legacy keys in-memory AND persist the cleaned file
    migrated_data, migrated_keys = _bring_up_to_date(raw)
    if migrated_keys:
        try:
            settings_file.parent.mkdir(parents=True, exist_ok=True)
            from eli.core.secure_io import secure_write_text as _secure_write
            _secure_write(settings_file, json.dumps(migrated_data, indent=2, ensure_ascii=False), mode=0o600)
            if not _MIGRATION_LOGGED:
                log.debug(f"[SETTINGS] Migrated {len(migrated_keys)} legacy keys: {migrated_keys}")
                _MIGRATION_LOGGED = True
        except Exception as e:
            log.debug(f"[SETTINGS] Migration save failed (non-fatal): {e}")

    settings.update(migrated_data)

    # Resolve relative model paths → absolute (supports portable/redistributable installs)
    settings = _resolve_relative_model_paths(settings)

    # Heal stale absolute paths (e.g. from a different machine or user home dir)
    settings, healed = _heal_model_paths(settings)
    if healed:
        try:
            # Persist healed paths back so next launch is instant
            _persist_healed_paths(settings, settings_file)
        except Exception:
            log.debug("suppressed exception", exc_info=True)

    if apply_env_overlay:
        # What the operator exported, over the file; apply_env's own copies of saved values are not
        # an export (the order above apply_env).
        published = _published()
        for env_name, key in ENV_TO_KEY.items():
            val = _operator_value(env_name, published)
            if val is not None:
                settings[key] = _coerce_value(key, val)

    # Canonical coercion (no more dual-key fallbacks)
    settings["n_threads"] = int(settings.get("n_threads", DEFAULTS["n_threads"]))
    settings["n_gpu_layers"] = int(settings.get("n_gpu_layers", DEFAULTS["n_gpu_layers"]))
    for _key in ("n_gpu_layers", "vision_n_gpu_layers", "vision_fast_n_gpu_layers"):
        try:
            if int(settings.get(_key) or 0) == _LEGACY_ALL_GPU_LAYERS:
                settings[_key] = ALL_GPU_LAYERS
        except (TypeError, ValueError):
            log.debug("unreadable %s", _key, exc_info=True)
    settings["gpu_layers"] = settings["n_gpu_layers"]

    if not settings.get("model_path"):
        settings["model_path"] = (
            settings.get("custom_model_path")
            or settings.get("bundled_model_path")
            or ""
        )

    return settings


def _persist_healed_paths(settings: Dict[str, Any], settings_file: Path) -> None:
    """Write healed model paths back into the settings file."""
    existing: Dict[str, Any] = {}
    if settings_file.exists():
        try:
            parsed = json.loads(settings_file.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                existing = parsed
        except Exception:
            log.debug("suppressed exception", exc_info=True)
    for key in _MODEL_PATH_KEYS:
        if key in settings:
            existing[key] = settings[key]
    existing = _portable_settings_for_storage(existing)
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    # settings may hold secrets (broker passwords, tokens) — born-0600 atomic
    # write, never world-readable for any instant. See eli.core.secure_io.
    from eli.core.secure_io import secure_write_text as _secure_write
    _secure_write(settings_file, json.dumps(existing, indent=2, ensure_ascii=False), mode=0o600)


def _harden_perms(path) -> None:
    """Restrict a settings file to its owner (0600) — it can hold secrets (broker
    passwords, tokens). Best-effort: effective on POSIX, a no-op on Windows."""
    try:
        os.chmod(path, 0o600)
    except OSError:
        log.debug("suppressed exception", exc_info=True)


def save_settings(settings: Dict[str, Any]) -> None:
    """Merge-save: read current file, apply updates, strip legacy keys, write back."""
    settings_file = _settings_file()

    # Start from whatever is on disk (NOT defaults — so we don't reintroduce defaults
    # into the file if the user has never touched them).
    existing: Dict[str, Any] = {}
    if settings_file.exists():
        try:
            parsed = json.loads(settings_file.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                existing = parsed
        except Exception:
            log.debug("suppressed exception", exc_info=True)

    # Migrate anything legacy in existing first
    existing, _ = _bring_up_to_date(existing)
    before = dict(existing)

    # Apply caller updates
    for k, v in settings.items():
        if k in LEGACY_KEY_MIGRATIONS:
            # If caller passed a legacy key, fold it silently
            existing[LEGACY_KEY_MIGRATIONS[k]] = v
        else:
            existing[k] = v

    existing = _portable_settings_for_storage(existing)

    # Final coercion on canonical keys
    if "n_threads" in existing:
        try: existing["n_threads"] = int(existing["n_threads"])
        except Exception: pass
    if "n_gpu_layers" in existing:
        try:
            existing["n_gpu_layers"] = int(existing["n_gpu_layers"])
        except Exception:
            log.debug("suppressed exception", exc_info=True)

    settings_file.parent.mkdir(parents=True, exist_ok=True)
    # settings may hold secrets (broker passwords, tokens) — born-0600 atomic
    # write, never world-readable for any instant. See eli.core.secure_io.
    from eli.core.secure_io import secure_write_text as _secure_write
    _secure_write(settings_file, json.dumps(existing, indent=2, ensure_ascii=False), mode=0o600)

    # Keep the process environment in step with what was saved, by the order above apply_env. Without
    # it get_model_path() kept returning the previous GGUF through ELI_GGUF_MODEL_PATH and a model
    # swap in the settings did nothing; done without the order, every save removed or overwrote the
    # context, batch and model the operator had exported.
    try:
        apply_env(dict(existing), changed=_changed_by(settings, before, existing))
    except Exception:
        log.debug("[SETTINGS] apply_env after save failed", exc_info=True)


def load_settings_from_disk() -> Dict[str, Any]:
    """Load settings.json without letting process model-path env vars win.

    Use this when the caller needs the *saved* selection (e.g. reload after a
    settings swap). Normal load_settings() still honours ELI_GGUF_MODEL_PATH for
    explicit shell/CLI overrides.
    """
    return load_settings(apply_env_overlay=False)


def update_settings(**kwargs: Any) -> Dict[str, Any]:
    """Convenience: save specific keys, return the full new state."""
    save_settings(kwargs)
    return load_settings()


# Keys that take effect per-inference call (no Llama rebuild required).
# These pass through to the generation call directly.
LIVE_KEYS: set = {
    "max_tokens", "temperature", "top_p", "top_k", "repeat_penalty",
    "stop_sequences",
}

# Keys that require a Llama rebuild to take effect.
RELOAD_KEYS: set = {
    "provider", "model_path", "custom_model_path", "bundled_model_path",
    "gguf_model_path", "ollama_host", "ollama_model",
    "n_ctx", "n_threads", "n_gpu_layers", "batch_size",
    "cache_type_k", "cache_type_v",
    "use_mmap", "use_mlock",
}


def apply_runtime_settings(delta: Dict[str, Any], *, do_reload: bool = True) -> Dict[str, Any]:
    """Apply a settings delta and classify what action it requires.

    Saves the delta to settings.json (merged with existing). Returns:
      {
        "applied_live": [keys that take effect on next inference call],
        "requires_reload": [keys that require a Llama rebuild],
        "reload_triggered": bool,
        "reload_result": dict | None,
      }

    When `do_reload=True` and any RELOAD_KEYS changed, this triggers
    `gguf_inference.reload_model()` synchronously. Set `do_reload=False`
    to defer reload (e.g. when batching multiple calls).
    """
    existing = load_settings() or {}
    save_settings(delta)

    applied_live: list = []
    requires_reload: list = []
    for k, v in delta.items():
        if k in LIVE_KEYS:
            applied_live.append(k)
        elif k in RELOAD_KEYS and existing.get(k) != v:
            requires_reload.append(k)

    out: Dict[str, Any] = {
        "applied_live": applied_live,
        "requires_reload": requires_reload,
        "reload_triggered": False,
        "reload_result": None,
    }

    if do_reload and requires_reload:
        try:
            from eli.cognition import gguf_inference as _gi
            out["reload_result"] = _gi.reload_model(await_completion=True)
            out["reload_triggered"] = True
        except Exception as exc:
            out["reload_result"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    return out


def load_runtime_settings() -> Dict[str, Any]:
    return load_settings()


def save_runtime_settings(settings: Dict[str, Any]) -> None:
    save_settings(settings)


def _resolve_gpu_split(s):
    """Resolve (tensor_split, main_gpu, split_mode) for multi-GPU.

    Precedence: explicit settings/env values win; otherwise the active profile from
    config/gpu_profiles.json (or ELI_GPU_PROFILES_FILE). Returns ("", None, "") when no
    split is configured. Mirrors the model-catalog override pattern; fully local.
    """
    ts = str(s.get("tensor_split", "") or "").strip()
    main_gpu = s.get("main_gpu")
    sm = str(s.get("split_mode", "") or "").strip()
    if ts:
        return ts, main_gpu, sm
    # No explicit split — look for an enabled profile in the gpu_profiles file.
    try:
        candidates = []
        envp = (os.environ.get("ELI_GPU_PROFILES_FILE") or str(s.get("gpu_profiles_file", "") or "")).strip()
        if envp:
            candidates.append(Path(envp).expanduser())
        candidates.append(_eli_runtime_physical_project_root() / "config" / "gpu_profiles.json")
        for p in candidates:
            if p.is_file():
                data = json.loads(p.read_text(encoding="utf-8"))
                profs = data.get("profiles", data) if isinstance(data, dict) else data
                for prof in (profs or []):
                    if isinstance(prof, dict) and prof.get("enabled") and prof.get("tensor_split"):
                        _ts = prof["tensor_split"]
                        _ts = ",".join(str(x) for x in _ts) if isinstance(_ts, (list, tuple)) else str(_ts)
                        return _ts.strip(), prof.get("main_gpu", main_gpu), str(prof.get("split_mode", sm) or "").strip()
                break
    except Exception:
        log.debug("suppressed exception", exc_info=True)
    return ts, main_gpu, sm


# ── The environment and the saved settings: which value governs ──────────────────────────────────
# A load setting reaches the loader through the environment as well as settings.json: the loader
# (gguf_inference.load_request, get_model_path) and config.get_gguf_* read the ELI_ variable first.
# apply_env writes the saved settings into those variables, after every save and before a reload.
# One order for every variable it writes:
#   1. The user changed the setting in the app: a save gives it a value other than the one in force.
#      The new value governs from then on, over an export: every variable of the setting carries it,
#      or is removed when the setting is auto.
#   2. Otherwise a value the operator exported governs: a variable of the setting holding a value
#      apply_env did not write (the shell, a launcher, a script, other code that set it on purpose).
#      It is never overwritten or removed, and the setting's other variables are given its value.
#   3. Otherwise the saved value: the variables carry it, or are removed when the setting is auto.
# A setting's variables are its names in ENV_TO_KEY. What apply_env wrote is recorded in
# ELI_SETTINGS_PUBLISHED, so a variable holding exactly that is a copy of a saved setting, not an
# export, here and in the processes this one starts. load_settings follows rule 2 as well: the
# operator's variables over the file, never apply_env's copies.
# n_gpu_layers has no variable apply_env writes: the loader takes the saved count per model
# (pinned_gpu_layers_for_model). An exported count governs every load (rule 2) until the user sets
# a count in the app, which removes the exported variables (rule 1); a count the tuner measured
# (n_gpu_layers_source "tuner") is not the user's.
_PUBLISHED_VAR = "ELI_SETTINGS_PUBLISHED"
_ENV_LOCK = threading.RLock()

# The variables apply_env writes (_env_values), and the settings they carry.
_PUBLISHED_VARS = (
    "ELI_GGUF_N_CTX", "ELI_N_CTX", "ELI_GGUF_N_BATCH", "ELI_BATCH_SIZE",
    "ELI_GGUF_THREADS", "ELI_N_THREADS", "ELI_MAX_TOKENS",
    "ELI_GGUF_USE_MMAP", "ELI_GGUF_USE_MLOCK", "ELI_MODEL_THINK",
    "ELI_GGUF_TENSOR_SPLIT", "ELI_GGUF_MAIN_GPU", "ELI_GGUF_SPLIT_MODE", "ELI_GGUF_MODEL_PATH",
)
_PUBLISHED_KEYS = frozenset(ENV_TO_KEY[name] for name in _PUBLISHED_VARS)
# the settings a model choice is saved under; the loader takes the first one set
_MODEL_CHOICE_KEYS = ("model_path", "custom_model_path", "bundled_model_path")


def _published() -> Dict[str, Optional[str]]:
    """The variables apply_env wrote, with what it wrote (None: it removed the variable)."""
    try:
        data = json.loads(os.environ.get(_PUBLISHED_VAR) or "{}")
    except ValueError:
        log.debug("[SETTINGS] unreadable %s", _PUBLISHED_VAR, exc_info=True)
        return {}
    return data if isinstance(data, dict) else {}


def _operator_value(name: str, published: Optional[Dict[str, Optional[str]]] = None) -> Optional[str]:
    """Variable `name` as the operator set it: None when it is unset, empty, or apply_env's copy."""
    val = os.environ.get(name)
    if val in (None, ""):
        return None
    published = _published() if published is None else published
    if name in published and published[name] == val:
        return None
    return val


def _setting_vars(key: str) -> list:
    """The variables of setting `key`, the one that governs first (ENV_TO_KEY lists it last)."""
    return [name for name, k in reversed(list(ENV_TO_KEY.items())) if k == key]


def _operator_setting(key: str, published: Optional[Dict[str, Optional[str]]] = None) -> Optional[str]:
    """The value the operator exported for setting `key` (rule 2), None when there is none."""
    published = _published() if published is None else published
    for name in _setting_vars(key):
        val = _operator_value(name, published)
        if val is not None:
            return val
    return None


def exported_gpu_layers() -> Optional[int]:
    """The GPU-layer count the operator exported (ELI_GGUF_N_GPU_LAYERS, ELI_N_GPU_LAYERS or the
    older ELI_GPU_LAYERS), for whatever model loads, as every other exported load variable is; None
    when there is none or the user has since set a count in the app (the order above apply_env)."""
    raw = _operator_setting("n_gpu_layers")
    if raw is None:
        return None
    try:
        layers = int(str(raw).strip())
    except ValueError:
        log.warning("[SETTINGS] ignoring an exported GPU-layer count that is not a number: %r", raw)
        return None
    return ALL_GPU_LAYERS if layers == _LEGACY_ALL_GPU_LAYERS else layers


def _env_values(s: Dict[str, Any]) -> Dict[str, Optional[str]]:
    """Each variable apply_env writes, with the value settings `s` give it (None: removed)."""
    def _int(key: str, default: int = 0) -> int:
        try:
            return int(s.get(key) or default)
        except (TypeError, ValueError):
            return int(default)

    def _flag(key: str, default: bool) -> str:
        return "1" if _coerce_value(key, s.get(key, default)) else "0"

    n_ctx, n_threads = _int("n_ctx"), _int("n_threads")           # 0 is auto: nothing pinned
    n_batch = _int("batch_size", DEFAULTS["batch_size"])
    max_tokens = _int("max_tokens", DEFAULTS["max_tokens"])
    out: Dict[str, Optional[str]] = {
        "ELI_GGUF_N_CTX": str(n_ctx) if n_ctx > 0 else None,
        "ELI_N_CTX": str(n_ctx) if n_ctx > 0 else None,            # the name older readers use
        "ELI_GGUF_N_BATCH": str(n_batch),
        "ELI_BATCH_SIZE": str(n_batch),
        "ELI_GGUF_THREADS": str(n_threads) if n_threads > 0 else None,
        "ELI_N_THREADS": str(n_threads) if n_threads > 0 else None,
        "ELI_MAX_TOKENS": str(max_tokens),
        "ELI_GGUF_USE_MMAP": _flag("use_mmap", True),
        "ELI_GGUF_USE_MLOCK": _flag("use_mlock", False),
        # deep thinking on reasoning models, read per call (gguf_inference._thinking_wanted)
        "ELI_MODEL_THINK": _flag("model_thinking", True),
    }
    # Multi-GPU split (single-GPU users: all empty, nothing written), from the settings or
    # config/gpu_profiles.json, for the loader's tensor_split.
    ts, main_gpu, sm = _resolve_gpu_split(s)
    out["ELI_GGUF_TENSOR_SPLIT"] = str(ts) if ts else None
    out["ELI_GGUF_MAIN_GPU"] = str(main_gpu) if ts and main_gpu not in (None, "") else None
    out["ELI_GGUF_SPLIT_MODE"] = str(sm) if ts and sm else None
    model = str(next((s.get(k) for k in _MODEL_CHOICE_KEYS if s.get(k)), "") or "").strip()
    if model:                       # an empty choice leaves the variable as it is
        out["ELI_GGUF_MODEL_PATH"] = model
    return out


def _same_env_value(name: str, a: Optional[str], b: Optional[str]) -> bool:
    if name == "ELI_GGUF_MODEL_PATH" and a and b:
        return resolve_path_value(a, PROJECT_ROOT) == resolve_path_value(b, PROJECT_ROOT)
    return a == b


def _changed_by(delta: Dict[str, Any], before: Dict[str, Any], after: Dict[str, Any]) -> set:
    """The load settings a save changes (rule 1): the caller gives one a value other than the one in
    force, the operator's export or else the saved value."""
    given = {LEGACY_KEY_MIGRATIONS.get(k, k) for k in (delta or {})}
    if given & set(_MODEL_CHOICE_KEYS):
        given.add("model_path")
    published = _published()
    in_force = dict(DEFAULTS)
    in_force.update(before)
    for key in _PUBLISHED_KEYS | {"n_gpu_layers"}:
        op = _operator_setting(key, published)
        if op is not None:
            in_force[key] = _coerce_value(key, op)
    saved = dict(DEFAULTS)
    saved.update(after)
    was, now = _env_values(in_force), _env_values(saved)
    changed = {ENV_TO_KEY[name] for name in set(was) | set(now)
               if ENV_TO_KEY[name] in given and not _same_env_value(name, was.get(name), now.get(name))}
    if ("n_gpu_layers" in given
            and str(saved.get("n_gpu_layers_source") or "").strip().lower() != "tuner"
            and _coerce_value("n_gpu_layers", in_force.get("n_gpu_layers"))
            != _coerce_value("n_gpu_layers", saved.get("n_gpu_layers"))):
        changed.add("n_gpu_layers")
    return changed


def apply_env(settings=None, changed=()):
    """Write the load settings into the variables the loader reads, by the order above. `changed`:
    the settings the user has just changed in the app (save_settings works them out)."""
    s = dict(load_settings() if settings is None else settings)
    changed = set(changed or ())
    with _ENV_LOCK:
        published = _published()
        live = dict(s)                                  # the settings in force
        for key in _PUBLISHED_KEYS - changed:
            op = _operator_setting(key, published)
            if op is not None:
                live[key] = _coerce_value(key, op)

        def _write(name: str, value: Optional[str]) -> None:
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
            published[name] = value

        for name, value in _env_values(live).items():
            key = ENV_TO_KEY[name]
            if key in changed:
                for target in _setting_vars(key):       # rule 1: every variable of it, exports too
                    _write(target, value)
            elif _operator_value(name, published) is None:
                _write(name, value)                     # rules 2 and 3; the operator's own is left alone
        if "n_gpu_layers" in changed:
            for target in _setting_vars("n_gpu_layers"):
                _write(target, None)
        os.environ[_PUBLISHED_VAR] = json.dumps(published, sort_keys=True)
    return s

# --- ELI portability runtime path guard: BEGIN ---
def _eli_runtime_physical_project_root():
    """
    Resolve this install's project root from this file's physical location.

    This deliberately does not trust ELI_PROJECT_ROOT because copied installs
    can inherit stale environment variables from the source/developer machine.

    Frozen builds are the one exception: there the physical location is the
    read-only PyInstaller bundle (_internal / AppImage mount) and
    ELI_PROJECT_ROOT is pinned in-process by the bundle's own runtime hook
    (not inherited from a shell), pointing at the per-user ELI_v2 root.
    Anchoring on the bundle made this guard strip the correct root and sent
    every PROJECT_ROOT-relative write to the read-only mount.
    """
    import os
    import sys
    from pathlib import Path
    if getattr(sys, "frozen", False):
        env = str(os.environ.get("ELI_PROJECT_ROOT") or "").strip()
        if env:
            return Path(env).expanduser().resolve()
    return Path(__file__).resolve().parents[2]


def _eli_runtime_is_relative_to(child, parent) -> bool:
    try:
        child.resolve(strict=False).relative_to(parent.resolve(strict=False))
        return True
    except Exception:
        return False


def _eli_runtime_truthy(value) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _eli_runtime_key_is_pathlike(key: str) -> bool:
    k = str(key or "").lower()
    markers = (
        "path", "dir", "folder", "file", "root",
        "db", "database", "sqlite", "faiss", "pkl",
        "artifact", "runtime", "config", "state",
        "persona", "profile", "model", "output",
        "log", "cache", "index",
    )
    return any(m in k for m in markers)


# The folders an ELI install keeps at its top: its code and the state eli.core.paths puts there.
_PROJECT_TOPS = frozenset({
    "eli", "config", "artifacts", "cache", "bin", "scripts", "tests",
    "plugins", "ops", "outputs", "packaging", "docs", "voices", "training",
    "models", "blueprints", "reports", "test_reports",
})


def _eli_runtime_external_path_to_current_install(candidate, root):
    """
    Map stale absolute project paths into the current install when the suffix is
    recognisably project-local.

    Example:
      /opt/example-eli/artifacts/db/user.sqlite3
      -> <current-root>/artifacts/db/user.sqlite3
    """
    from pathlib import Path

    parts = list(candidate.parts)

    for i, part in enumerate(parts):
        if part in _PROJECT_TOPS:
            try:
                return root / Path(*parts[i:])
            except Exception:
                return None

    return None


def _eli_runtime_sanitize_path_string(key: str, value: str):
    import os
    from pathlib import Path

    root = _eli_runtime_physical_project_root()
    key_s = str(key or "")
    key_l = key_s.lower()
    raw = str(value or "").strip()

    if not raw:
        return value

    if not _eli_runtime_key_is_pathlike(key_s):
        # Runtime settings should not contain prose, but avoid rewriting ordinary strings.
        return value

    try:
        candidate = Path(raw).expanduser()
    except Exception:
        return ""

    if not candidate.is_absolute():
        return value

    try:
        resolved = candidate.resolve(strict=False)
    except Exception:
        resolved = candidate

    if _eli_runtime_is_relative_to(resolved, root):
        return str(resolved)

    allow_external_models = _eli_runtime_truthy(os.getenv("ELI_ALLOW_EXTERNAL_MODEL_PATHS"))
    model_key = "model" in key_l

    if model_key:
        # A model the user chose outside ELI's folder (a download, another drive) is theirs to keep:
        # only a path that no longer exists here is stale. Clearing every outside path wiped a
        # browsed-to model from the settings at the next load.
        if allow_external_models or resolved.is_file() or resolved.is_dir():
            return str(resolved)

        mapped = _eli_runtime_external_path_to_current_install(resolved, root)
        if mapped is not None and mapped.exists():
            return str(mapped.resolve(strict=False))

        # Clean install with no local model selected yet.
        return ""

    # Explicit project-root style keys must point to this install.
    if key_l in {"project_root", "root", "base_dir", "base_path"}:
        return str(root)

    mapped = _eli_runtime_external_path_to_current_install(resolved, root)
    if mapped is not None:
        return str(mapped.resolve(strict=False))

    # External non-model path with no safe mapping. Clear it.
    return ""


def _eli_runtime_sanitize_obj(obj, key_hint=""):
    if isinstance(obj, dict):
        return {
            k: _eli_runtime_sanitize_obj(v, str(k))
            for k, v in obj.items()
        }

    if isinstance(obj, list):
        return [_eli_runtime_sanitize_obj(v, key_hint) for v in obj]

    if isinstance(obj, tuple):
        return tuple(_eli_runtime_sanitize_obj(v, key_hint) for v in obj)

    if isinstance(obj, str):
        return _eli_runtime_sanitize_path_string(key_hint, obj)

    return obj


def inherited_from_another_install(value, root=None) -> Optional[Path]:
    """The root of the ELI install a folder or file path belongs to, when that install is not this
    one; None for a path of this install or of no ELI install, which is the user's own choice.

    An ELI install is a tree holding the eli package (eli.core.paths._is_eli_root): a checkout, a
    version's own folder, the place a copied install came from. A path is the install's when it is
    the install itself or lies in one of the folders an install keeps (_PROJECT_TOPS: config,
    artifacts, models, ...); every ELI product keeps its own, so such a path came from that
    install. A folder of the user's that merely sits inside a checkout (a temp folder) is not one.
    The path need not exist yet: the nearest ELI install above it decides."""
    from eli.core.paths import _is_eli_root
    root = Path(root) if root is not None else _eli_runtime_physical_project_root()
    try:
        path = Path(str(value)).expanduser()
        if not path.is_absolute():
            return None
        path = path.resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        return None
    if _eli_runtime_is_relative_to(path, root):
        return None
    for folder in (path, *path.parents):
        if _is_eli_root(folder):
            inside = path.relative_to(folder).parts
            return folder if not inside or inside[0] in _PROJECT_TOPS else None
    return None


def _eli_runtime_clear_stale_env_paths():
    """
    Drop the folder and file variables another ELI install left in this process's environment.

    A config, data or database path outside this install is dropped only when it belongs to another
    ELI install (inherited_from_another_install): every ELI product keeps its own folders. One the
    user set elsewhere stays, whether or not it exists yet. A model path outside the install stays
    while the file is there (with ELI_ALLOW_EXTERNAL_MODEL_PATHS=1, always); ELI_PROJECT_ROOT is
    where this install is, or it goes. Each variable dropped is logged. Every path outside the
    install used to be dropped without a word, and ELI then read its own config/settings.json in
    place of the one the user had pointed it at.
    """
    import os
    from pathlib import Path

    root = _eli_runtime_physical_project_root()
    allow_external_models = _eli_runtime_truthy(os.getenv("ELI_ALLOW_EXTERNAL_MODEL_PATHS"))

    env_keys = (
        "ELI_PROJECT_ROOT",
        "ELI_ARTIFACTS_DIR",
        "ELI_DATA_DIR",
        "ELI_DB_DIR",
        "ELI_CACHE_DIR",
        "ELI_CONFIG_DIR",
        "ELI_RUNTIME_DIR",
        "ELI_STATE_DIR",
        "ELI_USER_DB",
        "ELI_AGENT_DB",
        "ELI_MEMORY_DB",
        "ELI_VECTOR_DIR",
        "ELI_FAISS_INDEX",
        "ELI_FAISS_META",
        "ELI_GGUF_MODEL",
        "ELI_GGUF_MODEL_PATH",
        "ELI_MODEL_PATH",
        "ELI_MODEL",
        "ELI_CUSTOM_MODEL_PATH",
        "ELI_BUNDLED_MODEL_PATH",
    )

    dropped = False
    for env_key in env_keys:
        raw = str(os.getenv(env_key) or "").strip()
        if not raw:
            continue

        try:
            candidate = Path(raw).expanduser()
        except Exception:
            os.environ.pop(env_key, None)
            log.warning("[SETTINGS] %s=%s is not a path ELI can read, so it is not used", env_key, raw)
            dropped = True
            continue

        if not candidate.is_absolute():
            continue

        try:
            resolved = candidate.resolve(strict=False)
        except Exception:
            resolved = candidate

        if _eli_runtime_is_relative_to(resolved, root):
            continue

        if env_key == "ELI_PROJECT_ROOT":
            why = f"this install is {root}"          # the root is where this ELI is, nowhere else
        elif "MODEL" in env_key:
            if allow_external_models or resolved.exists():
                continue
            why = "that model file does not exist"
        else:
            other = inherited_from_another_install(resolved, root)
            if other is None:
                continue
            why = f"it is inside another ELI install ({other}), and this one ({root}) keeps its own folders"
        os.environ.pop(env_key, None)
        log.warning("[SETTINGS] %s=%s is not used: %s", env_key, raw, why)
        dropped = True

    if dropped:
        # the path resolvers may have read a dropped variable already
        from eli.core import paths as _paths
        for _fn in (_paths.data_dir, _paths.config_dir, _paths.cache_dir):
            _fn.cache_clear()



_STALE_ENV_CHECKED = False


def _eli_portability_load_settings(*args, **kwargs):
    global _STALE_ENV_CHECKED
    if not _STALE_ENV_CHECKED:
        # What a copied install inherits is there when the process starts. A path set since, by ELI
        # or by a test, was set on purpose: removed by whichever thread read the settings next, it
        # sent a test's config writes into the project's own config folder.
        _STALE_ENV_CHECKED = True
        _eli_runtime_clear_stale_env_paths()
    settings = _load_settings_unsanitized(*args, **kwargs)
    explicit_settings_file = bool(
        str(os.environ.get("ELI_SETTINGS_FILE") or os.environ.get("ELI_SETTINGS_PATH") or "").strip()
    )
    if not explicit_settings_file:
        settings = _eli_runtime_sanitize_obj(settings)

    # Final authoritative install-local path correction for common root keys.
    try:
        root = _eli_runtime_physical_project_root()
        if isinstance(settings, dict):
            for k in ("project_root", "root", "base_dir", "base_path"):
                if k in settings:
                    settings[k] = str(root)
    except Exception:
        log.debug("suppressed exception", exc_info=True)

    return settings
# --- ELI portability runtime path guard: END ---

# Final portability wrapper. It lives at EOF so no earlier load_settings() implementation or env
# overlay can bypass it.
try:
    _eli_load_settings_before_final_portability_wrapper = _eli_portability_load_settings
except NameError:
    _eli_load_settings_before_final_portability_wrapper = None


def _eli_final_project_root() -> Path:
    try:
        return Path(__file__).resolve().parents[2]
    except Exception:
        return Path.cwd().resolve()


def _eli_final_clean_path_value(value):
    """A model path must lead to a model: a relative one stays under models/, a full one must exist,
    wherever the user chose it. This pass also required it inside the install folder, which wiped
    every model chosen outside it, and it ignored ELI_ALLOW_EXTERNAL_MODEL_PATHS."""
    s = str(value or "").strip()
    if not s:
        return ""
    p = Path(s).expanduser()
    if p.is_absolute():
        return s if p.exists() or _eli_runtime_truthy(os.getenv("ELI_ALLOW_EXTERNAL_MODEL_PATHS")) else ""
    norm = s.replace("\\", "/")
    return norm if norm.startswith("models/") and ".." not in Path(norm).parts else ""


def _eli_final_sanitize_loaded_settings(settings):
    if not isinstance(settings, dict):
        return settings

    explicit_settings_file = bool(
        str(os.environ.get("ELI_SETTINGS_FILE") or os.environ.get("ELI_SETTINGS_PATH") or "").strip()
    )
    if not explicit_settings_file:
        for key in (
            "model_path",
            "custom_model_path",
            "bundled_model_path",
            "gguf_model_path",
            "image_model_path",
        ):
            if key in settings:
                settings[key] = _eli_final_clean_path_value(settings.get(key))

    # Remove stale project-local path authority keys if they point outside this install.
    root = _eli_final_project_root().resolve()
    for key in (
        "project_root",
        "artifacts_dir",
        "config_dir",
        "runtime_snapshot",
        "state",
        "user_profile",
        "world_model",
        "last_trace",
        "user_db",
        "agent_db",
        "memory_db",
        "models_dir",
    ):
        if key not in settings:
            continue

        val = settings.get(key)
        if val in (None, ""):
            continue

        try:
            p = Path(str(val)).expanduser()
            if not p.is_absolute():
                continue
            resolved = p.resolve(strict=False)
            try:
                resolved.relative_to(root)
            except Exception:
                settings[key] = None
        except Exception:
            settings[key] = None

    return settings


def load_settings(*args, **kwargs):
    if _eli_load_settings_before_final_portability_wrapper is None:
        return _eli_final_sanitize_loaded_settings({})
    return _eli_final_sanitize_loaded_settings(
        _eli_load_settings_before_final_portability_wrapper(*args, **kwargs)
    )
