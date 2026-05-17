"""
Configuration manager for ELI - thin shim over runtime_settings.

All reads/writes go through eli.core.runtime_settings which reads and writes
a single canonical settings.json. Legacy key names are mapped on the fly so
old callers keep working, but the on-disk file uses canonical names only.

Canonical key mapping (legacy -> canonical):
  gguf_n_ctx       -> n_ctx
  gguf_n_gpu_layers-> n_gpu_layers
  gguf_n_batch     -> batch_size
  num_predict      -> max_tokens
  gguf_model_path  -> model_path
  n_batch          -> batch_size
"""

from typing import Optional, Dict, Any, List
import os
import sys
import json
from pathlib import Path

from eli.core.runtime_settings import (
    load_settings as _rs_load,
    save_settings as _rs_save,
    _settings_file as _rs_file,
)
from eli.core.paths import config_dir, gguf_models_dir, project_root


def _running_under_pytest() -> bool:
    if os.getenv("PYTEST_CURRENT_TEST"):
        return True
    return "pytest" in sys.modules


# Exposed for back-compat with any caller that reads the path directly.
CONFIG_PATH = _rs_file()


# Legacy -> canonical key translation for get/set.
_KEY_ALIASES = {
    "gguf_n_ctx": "n_ctx",
    "gguf_n_gpu_layers": "n_gpu_layers",
    "gguf_n_batch": "batch_size",
    "n_batch": "batch_size",
    "num_predict": "max_tokens",
    "gguf_model_path": "model_path",
}


def _canonical(key: str) -> str:
    return _KEY_ALIASES.get(key, key)


def get(key: str, default=None):
    """Read a config value. Legacy key names transparently mapped to canonical."""
    try:
        s = _rs_load()
        return s.get(_canonical(key), default)
    except Exception:
        return default


def set(key: str, value):
    """Write a config value. Legacy key names transparently mapped to canonical."""
    try:
        _rs_save({_canonical(key): value})
        return True
    except Exception:
        return False


def delete(key: str):
    """Delete a config key from settings.json."""
    try:
        settings_file = _rs_file()
        if not settings_file.exists():
            return False
        data = json.loads(settings_file.read_text(encoding="utf-8"))
        ck = _canonical(key)
        if ck in data:
            del data[ck]
            settings_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            return True
    except Exception:
        pass
    return False


def list_keys():
    """List all top-level keys in settings.json."""
    try:
        return list(_rs_load().keys())
    except Exception:
        return []


# ---------- Web automation ----------

def set_web_headless(headless: bool):
    set("web_headless", bool(headless))


def get_web_headless() -> bool:
    return bool(get("web_headless", True))


# ---------- Model discovery ----------

ROOT = project_root()
MODEL_DIR = gguf_models_dir()


def get_model_dir():
    return Path(os.getenv("ELI_MODELS_DIR", MODEL_DIR)).expanduser()


def get_available_gguf_models():
    d = get_model_dir()
    if not d.exists():
        return []
    return sorted(d.rglob("*.gguf"))


def get_default_gguf_model():
    env = os.getenv("ELI_GGUF_MODEL_PATH")
    if env and Path(env).exists():
        return env
    name = os.getenv("ELI_GGUF_MODEL")
    if name:
        p = get_model_dir() / name
        if p.exists():
            return str(p)
    models = get_available_gguf_models()
    if models:
        return str(models[0])
    return None


# ---------- GGUF parameters (canonical + legacy getter/setter names) ----------

def set_gguf_model_path(path: str):
    set("model_path", path)


def get_gguf_model_path() -> Optional[str]:
    env = os.getenv("ELI_GGUF_MODEL_PATH")
    if env:
        p = Path(env).expanduser()
        if p.exists():
            return str(p)
    models_dir = os.getenv("ELI_MODELS_DIR")
    model_name = os.getenv("ELI_GGUF_MODEL")
    if models_dir and model_name:
        return str((Path(models_dir).expanduser().resolve() / model_name))
    v = get("model_path")
    if v:
        return v
    try:
        from eli.core.paths import PATHS
        return str(PATHS.model)
    except Exception:
        return None


def set_gguf_n_gpu_layers(layers: int):
    set("n_gpu_layers", int(layers))


def get_gguf_n_gpu_layers() -> int:
    env = os.getenv("ELI_GGUF_N_GPU_LAYERS") or os.getenv("ELI_N_GPU_LAYERS")
    if env is not None:
        try:
            return int(env)
        except Exception:
            pass
    return int(get("n_gpu_layers", 99))


def set_gguf_n_ctx(ctx: int):
    set("n_ctx", int(ctx))


def get_gguf_n_ctx() -> int:
    env = os.getenv("ELI_GGUF_N_CTX") or os.getenv("ELI_N_CTX")
    if env:
        try:
            return int(env)
        except Exception:
            pass
    try:
        return int(get("n_ctx", 16384))
    except Exception:
        return 16384


def set_gguf_n_batch(batch: int):
    set("batch_size", int(batch))


def get_gguf_n_batch() -> int:
    env = os.getenv("ELI_GGUF_N_BATCH") or os.getenv("ELI_BATCH_SIZE")
    if env is not None:
        try:
            return int(env)
        except Exception:
            pass
    return int(get("batch_size", 512))


# ---------- Persona (delegates to canonical persona authority) ----------

def set_persona(text: str):
    try:
        from eli.cognition.persona import write_base_persona
        write_base_persona(text)
        return
    except Exception:
        pass
    set("eli_persona", text)


def get_persona() -> str:
    try:
        from eli.cognition.persona import get_persona as _get_persona
        val = (_get_persona() or "").strip()
        if val:
            return val
    except Exception:
        pass
    default = (
        "You are ELI, a local reasoning and automation assistant. "
        "Be direct, accurate, grounded, privacy-preserving, and useful."
    )
    return get("eli_persona", default)


def get_eli_persona() -> str:
    return get_persona()


# ---------- Generation parameters ----------

def set_temperature(value: float):
    set("temperature", float(value))


def get_temperature() -> float:
    cur = get("temperature", None)
    if cur is not None:
        try:
            return float(cur)
        except Exception:
            pass
    env = os.getenv("ELI_TEMP") or os.getenv("ELI_TEMPERATURE")
    if env:
        try:
            return float(env)
        except Exception:
            pass
    return 0.55


def set_top_p(value: float):
    set("top_p", float(value))


def get_top_p() -> float:
    return float(get("top_p", 0.9))


def set_top_k(value: int):
    set("top_k", int(value))


def get_top_k() -> int:
    return int(get("top_k", 40))


def set_repeat_penalty(value: float):
    set("repeat_penalty", float(value))


def get_repeat_penalty() -> float:
    return float(get("repeat_penalty", 1.15))


def set_num_predict(value: int):
    set("max_tokens", int(value))


def get_num_predict() -> int:
    cur = get("max_tokens", None)
    if cur is not None:
        try:
            return int(cur)
        except Exception:
            pass
    env = os.getenv("ELI_NUM_PREDICT") or os.getenv("ELI_MAX_TOKENS")
    if env:
        try:
            return int(env)
        except Exception:
            pass
    return 2048


# ---------- Threads ----------

def get_n_threads() -> int:
    env = os.getenv("ELI_GGUF_THREADS") or os.getenv("ELI_N_THREADS") or os.getenv("ELI_CPU_THREADS")
    if env:
        try:
            return int(env)
        except Exception:
            pass
    cur = get("n_threads", None)
    if cur is not None:
        try:
            return int(cur)
        except Exception:
            pass
    return max(1, (os.cpu_count() or 8) - 1)


def set_n_threads(n: int) -> None:
    set("n_threads", int(n))
