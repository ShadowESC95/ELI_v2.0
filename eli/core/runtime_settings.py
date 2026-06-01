from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

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
        pass

    # 4. Final fallback.
    return (PROJECT_ROOT / "config" / "settings.json").resolve()


SETTINGS_FILE = _settings_file()

# Single source of truth for the n_ctx default.
# config.py and engine.py reference this so changing it here is sufficient.
DEFAULT_N_CTX: int = 16384

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
    "n_ctx": DEFAULT_N_CTX,
    "max_tokens": 4096,
    "temperature": 0.7,
    "top_p": 0.95,
    "top_k": 40,
    "repeat_penalty": 1.1,
    "n_gpu_layers": 0,
    "n_threads": max(1, os.cpu_count() or 8),
    "batch_size": 512,
    "use_mmap": True,
    "use_mlock": False,
    "cache_type_k": "",
    "cache_type_v": "",
    "auto_speak": False,
    "tts_voice": "en_US-lessac-high",
    "mic_enabled": False,
    "auto_save": True,
    "log_to_file": False,
    "auto_load": True,
    "first_run_complete": False,
    "theme": "dark",
    "searxng_url": "",
    # --- Local vision (model-agnostic, via llama-cpp; hot-swaps with the text
    # model). Paths empty = auto-discover any projector-paired VL GGUF in the
    # models dir. No model name is hardcoded; override per-install via these
    # keys or ELI_VISION_MODEL / ELI_VISION_MMPROJ. The llama-cpp chat handler is
    # auto-detected from the filename; set vision_chat_handler to force it. ---
    "vision_enabled": True,
    "vision_model_path": "",
    "vision_mmproj_path": "",
    "vision_chat_handler": "",
    "vision_n_ctx": 4096,
    "vision_n_gpu_layers": 99,
    "vision_n_batch": 256,
    # GPU clip segfaults on some cards (RTX 2060 SUPER / compute 7.5); keep the
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
    "vision_fast_n_gpu_layers": 99,
    # Co-resident (no model swap) — big latency win; enable once 8GB VRAM fit
    # is confirmed with both models loaded.
    "vision_fast_no_swap": False,
    # Co-resident vision: load the fast (Moondream) model BEFORE the text model
    # and keep it resident, so glances need no swap (~3.5s). The text model is
    # capped to vision_coresident_text_ctx so both fit in 8GB (validated: 7B at
    # ctx 18432, gpu_layers unchanged, + Q4 Moondream). Default OFF — flip on to
    # enable; a bad fit can never strand boot because it degrades to full ctx.
    "vision_coresident": False,
    "vision_coresident_text_ctx": 18432,
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
    # Allow proactive habit rules to run shell commands. On by default (your own
    # habits); set false to block shell execution from an untrusted/imported habit DB.
    "habit_shell_enabled": True,
}

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
    "ELI_MAX_TOKENS": "max_tokens",
    "ELI_TEMPERATURE": "temperature",
    "ELI_TOP_P": "top_p",
    "ELI_TOP_K": "top_k",
    "ELI_REPEAT_PENALTY": "repeat_penalty",
    "ELI_N_GPU_LAYERS": "n_gpu_layers",
    "ELI_GPU_LAYERS": "n_gpu_layers",         # legacy env name; same canonical key
    "ELI_N_THREADS": "n_threads",
    "ELI_CPU_THREADS": "n_threads",           # legacy env name
    "ELI_BATCH_SIZE": "batch_size",
    "ELI_USE_MMAP": "use_mmap",
    "ELI_USE_MLOCK": "use_mlock",
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
             "image_use_chat_context", "image_use_proactive_context"}

_MIGRATION_LOGGED = False
_HEAL_LOGGED = False


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


def _load_settings_unsanitized() -> Dict[str, Any]:
    global _MIGRATION_LOGGED
    settings = dict(DEFAULTS)
    settings_file = _settings_file()

    raw: Dict[str, Any] = {}
    if settings_file.exists():
        try:
            parsed = json.loads(settings_file.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                raw = parsed
        except Exception:
            pass

    # Migrate legacy keys in-memory AND persist the cleaned file
    migrated_data, migrated_keys = _migrate_legacy_keys(raw)
    if migrated_keys:
        try:
            settings_file.parent.mkdir(parents=True, exist_ok=True)
            settings_file.write_text(
                json.dumps(migrated_data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
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
            pass

    for env_name, key in ENV_TO_KEY.items():
        val = os.environ.get(env_name)
        if val not in (None, ""):
            settings[key] = _coerce_value(key, val)

    # Canonical coercion (no more dual-key fallbacks)
    settings["n_threads"] = int(settings.get("n_threads", DEFAULTS["n_threads"]))
    settings["n_gpu_layers"] = int(settings.get("n_gpu_layers", DEFAULTS["n_gpu_layers"]))
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
            pass
    for key in _MODEL_PATH_KEYS:
        if key in settings:
            existing[key] = settings[key]
    existing = _portable_settings_for_storage(existing)
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


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
            pass

    # Migrate anything legacy in existing first
    existing, _ = _migrate_legacy_keys(existing)

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
            pass

    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


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


def apply_env(settings=None):
    s = dict(load_settings() if settings is None else settings)

    n_ctx = int(s.get("n_ctx", DEFAULTS["n_ctx"]) or DEFAULTS["n_ctx"])
    n_batch = int(s.get("batch_size", DEFAULTS["batch_size"]) or DEFAULTS["batch_size"])
    n_threads = int(s.get("n_threads", DEFAULTS["n_threads"]) or DEFAULTS["n_threads"])
    n_gpu_layers = int(s.get("n_gpu_layers", DEFAULTS["n_gpu_layers"]) or DEFAULTS["n_gpu_layers"])
    max_tokens = int(s.get("max_tokens", DEFAULTS["max_tokens"]) or DEFAULTS["max_tokens"])

    os.environ["ELI_GGUF_N_CTX"] = str(n_ctx)
    os.environ["ELI_GGUF_N_BATCH"] = str(n_batch)
    os.environ["ELI_GGUF_THREADS"] = str(n_threads)
    os.environ["ELI_GGUF_N_GPU_LAYERS"] = str(n_gpu_layers)
    os.environ["ELI_MAX_TOKENS"] = str(max_tokens)

    # legacy mirrors for older callers still reading the non-GGUF names
    os.environ["ELI_N_CTX"] = str(n_ctx)
    os.environ["ELI_BATCH_SIZE"] = str(n_batch)
    os.environ["ELI_N_THREADS"] = str(n_threads)
    os.environ["ELI_N_GPU_LAYERS"] = str(n_gpu_layers)

    os.environ["ELI_GGUF_USE_MMAP"] = "1" if bool(s.get("use_mmap", True)) else "0"
    os.environ["ELI_GGUF_USE_MLOCK"] = "1" if bool(s.get("use_mlock", False)) else "0"

    model_path = str(
        s.get("model_path", "")
        or s.get("custom_model_path", "")
        or s.get("bundled_model_path", "")
    ).strip()
    if model_path:
        os.environ["ELI_GGUF_MODEL_PATH"] = model_path

    return s

# --- ELI portability runtime path guard: BEGIN ---
def _eli_runtime_physical_project_root():
    """
    Resolve this install's project root from this file's physical location.

    This deliberately does not trust ELI_PROJECT_ROOT because copied installs
    can inherit stale environment variables from the source/developer machine.
    """
    from pathlib import Path
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
    project_tops = {
        "eli", "config", "artifacts", "bin", "scripts", "tests",
        "plugins", "ops", "outputs", "packaging", "docs",
        "models", "blueprints", "reports", "test_reports",
    }

    for i, part in enumerate(parts):
        if part in project_tops:
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
        if allow_external_models:
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


def _eli_runtime_clear_stale_env_paths():
    """
    Remove stale env path overrides that point outside the current physical install.
    External model paths remain allowed only when ELI_ALLOW_EXTERNAL_MODEL_PATHS=1.
    """
    import os
    from pathlib import Path

    root = _eli_runtime_physical_project_root()
    allow_external_models = _eli_runtime_truthy(os.getenv("ELI_ALLOW_EXTERNAL_MODEL_PATHS"))

    env_keys = (
        "ELI_PROJECT_ROOT",
        "ELI_ARTIFACTS_DIR",
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

    for env_key in env_keys:
        raw = str(os.getenv(env_key) or "").strip()
        if not raw:
            continue

        try:
            candidate = Path(raw).expanduser()
        except Exception:
            os.environ.pop(env_key, None)
            continue

        if not candidate.is_absolute():
            continue

        try:
            resolved = candidate.resolve(strict=False)
        except Exception:
            resolved = candidate

        if _eli_runtime_is_relative_to(resolved, root):
            continue

        if "MODEL" in env_key and allow_external_models:
            continue

        os.environ.pop(env_key, None)



# ---------------------------------------------------------------------
# Portability guard: model path validation
# ---------------------------------------------------------------------
def _eli_project_root_for_runtime_settings() -> Path:
    try:
        return Path(__file__).resolve().parents[2]
    except Exception:
        return Path.cwd().resolve()


def _eli_is_relative_portable_model_path(value: str) -> bool:
    if not value:
        return True

    try:
        q = Path(str(value))
    except Exception:
        return False

    if q.is_absolute():
        return False

    s = str(q).replace("\\", "/")
    if s.startswith("../") or "/../" in s or s == "..":
        return False

    return s.startswith("models/")


def _eli_validate_model_path_value(value):
    """
    Return a portable/safe model path value.

    Rules:
    - Empty is allowed.
    - Relative models/... paths are allowed for portable templates.
    - Absolute paths are accepted only if they exist and are inside this active
      project root.
    - Stale paths from another machine/user/install are rejected.
    """
    if value in (None, ""):
        return ""

    s = str(value).strip()
    if not s:
        return ""

    # Portable config/template path.
    if _eli_is_relative_portable_model_path(s):
        return s

    try:
        root = _eli_project_root_for_runtime_settings().resolve()
        q = Path(s).expanduser()
        if not q.is_absolute():
            return ""

        q = q.resolve(strict=False)

        # Reject nonexistent poisoned env paths such as .../BAD.gguf.
        if not q.exists():
            return ""

        # Reject stale absolute paths outside this active install.
        try:
            q.relative_to(root)
        except Exception:
            return ""

        return str(q)
    except Exception:
        return ""


def _eli_sanitize_model_path_keys(settings: dict) -> dict:
    if not isinstance(settings, dict):
        return settings

    model_keys = {
        "model_path",
        "custom_model_path",
        "bundled_model_path",
        "gguf_model_path",
        "image_model_path",
    }

    for key in model_keys:
        if key in settings:
            settings[key] = _eli_validate_model_path_value(settings.get(key))

    return settings

def _eli_portability_load_settings(*args, **kwargs):
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
        pass

    return settings
# --- ELI portability runtime path guard: END ---

# ---------------------------------------------------------------------
# FINAL portability wrapper.
# This block intentionally lives at EOF so no earlier load_settings()
# implementation or environment overlay can bypass it.
# ---------------------------------------------------------------------
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
    if value in (None, ""):
        return ""

    s = str(value).strip()
    if not s:
        return ""

    try:
        p = Path(s).expanduser()

        # Portable relative model paths are allowed.
        if not p.is_absolute():
            norm = str(p).replace("\\", "/")
            if norm.startswith("models/") and ".." not in Path(norm).parts:
                return norm
            return ""

        root = _eli_final_project_root().resolve()
        resolved = p.resolve(strict=False)

        # Absolute model paths must exist.
        if not resolved.exists():
            return ""

        # Absolute model paths must belong to this active install.
        try:
            resolved.relative_to(root)
        except Exception:
            return ""

        return str(resolved)
    except Exception:
        return ""


def _eli_final_sanitize_loaded_settings(settings):
    if not isinstance(settings, dict):
        return settings

    explicit_settings_file = bool(
        str(os.environ.get("ELI_SETTINGS_FILE") or os.environ.get("ELI_SETTINGS_PATH") or "").strip()
    )
    if not explicit_settings_file:
        # Remove stale absolute machine-specific paths from production model keys.
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
