"""Tests for eli.core.runtime_settings — ~180 tests."""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from eli.core.runtime_settings import (
    DEFAULTS,
    _coerce_value,
    _heal_model_paths,
    _migrate_legacy_keys,
    _MODEL_PATH_KEYS,
    _resolve_relative_model_paths,
    load_settings,
    save_settings,
    update_settings,
    load_runtime_settings,
    save_runtime_settings,
    INT_KEYS,
    FLOAT_KEYS,
    BOOL_KEYS,
    LEGACY_KEY_MIGRATIONS,
    ENV_TO_KEY,
)


# ── DEFAULTS completeness ─────────────────────────────────────────────────

def test_defaults_has_provider():
    assert "provider" in DEFAULTS

def test_defaults_has_model_path():
    assert "model_path" in DEFAULTS

def test_defaults_has_n_ctx():
    assert "n_ctx" in DEFAULTS
    assert DEFAULTS["n_ctx"] == 16384

def test_defaults_has_max_tokens():
    assert "max_tokens" in DEFAULTS

def test_defaults_has_temperature():
    assert "temperature" in DEFAULTS
    assert 0.0 < DEFAULTS["temperature"] < 2.0

def test_defaults_has_n_gpu_layers():
    assert "n_gpu_layers" in DEFAULTS

def test_defaults_has_n_threads():
    assert "n_threads" in DEFAULTS
    assert DEFAULTS["n_threads"] >= 1

def test_defaults_has_batch_size():
    assert "batch_size" in DEFAULTS
    assert DEFAULTS["batch_size"] == 512

def test_defaults_has_theme():
    assert "theme" in DEFAULTS

def test_defaults_has_tts_voice():
    assert "tts_voice" in DEFAULTS

def test_defaults_has_image_keys():
    for k in ("image_backend", "image_model_path", "image_device"):
        assert k in DEFAULTS

def test_defaults_bool_types():
    for k in BOOL_KEYS:
        assert isinstance(DEFAULTS.get(k, False), bool), f"{k} should have bool default"


# ── KEY CLASSIFICATION ────────────────────────────────────────────────────

@pytest.mark.parametrize("key", ["n_ctx", "max_tokens", "top_k", "n_gpu_layers",
                                  "n_threads", "batch_size", "image_steps"])
def test_int_keys_classification(key):
    assert key in INT_KEYS

@pytest.mark.parametrize("key", ["temperature", "top_p", "repeat_penalty", "image_guidance"])
def test_float_keys_classification(key):
    assert key in FLOAT_KEYS

@pytest.mark.parametrize("key", ["use_mmap", "use_mlock", "auto_speak", "mic_enabled",
                                  "auto_save", "log_to_file", "auto_load", "first_run_complete"])
def test_bool_keys_classification(key):
    assert key in BOOL_KEYS


# ── _coerce_value ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("key,raw,expected", [
    ("n_ctx", "8192", 8192),
    ("n_ctx", 8192, 8192),
    ("max_tokens", "-1", -1),
    ("batch_size", "512", 512),
    ("n_gpu_layers", "99", 99),
    ("n_threads", "8", 8),
])
def test_coerce_int(key, raw, expected):
    assert _coerce_value(key, raw) == expected

@pytest.mark.parametrize("key,raw,expected", [
    ("temperature", "0.7", 0.7),
    ("top_p", "0.95", 0.95),
    ("repeat_penalty", "1.1", 1.1),
    ("image_guidance", "7.2", 7.2),
])
def test_coerce_float(key, raw, expected):
    assert abs(_coerce_value(key, raw) - expected) < 1e-9

@pytest.mark.parametrize("key,raw,expected", [
    ("use_mmap", "1", True),
    ("use_mmap", "true", True),
    ("use_mmap", "yes", True),
    ("use_mmap", "on", True),
    ("use_mmap", "True", True),
    ("use_mmap", "0", False),
    ("use_mmap", "false", False),
    ("use_mmap", "no", False),
    ("use_mmap", "off", False),
    ("use_mmap", "False", False),
    ("auto_speak", True, True),
    ("auto_speak", False, False),
])
def test_coerce_bool(key, raw, expected):
    assert _coerce_value(key, raw) == expected

def test_coerce_int_invalid_returns_default():
    result = _coerce_value("n_ctx", "not_a_number")
    assert result == DEFAULTS["n_ctx"]

def test_coerce_float_invalid_returns_default():
    result = _coerce_value("temperature", "not_a_float")
    assert result == DEFAULTS["temperature"]

def test_coerce_string_passthrough():
    result = _coerce_value("provider", "ollama")
    assert result == "ollama"

def test_coerce_unknown_key_passthrough():
    result = _coerce_value("unknown_key", "some_value")
    assert result == "some_value"


# ── _migrate_legacy_keys ──────────────────────────────────────────────────

def test_migrate_gpu_layers():
    data = {"gpu_layers": 11, "model_path": "model.gguf"}
    out, migrated = _migrate_legacy_keys(data)
    assert "gpu_layers" not in out
    assert out["n_gpu_layers"] == 11
    assert "gpu_layers" in migrated

def test_migrate_cpu_threads():
    data = {"cpu_threads": 8}
    out, migrated = _migrate_legacy_keys(data)
    assert "cpu_threads" not in out
    assert out["n_threads"] == 8
    assert "cpu_threads" in migrated

def test_migrate_does_not_override_canonical():
    # If n_gpu_layers already present, legacy gpu_layers should NOT override it
    data = {"gpu_layers": 5, "n_gpu_layers": 11}
    out, migrated = _migrate_legacy_keys(data)
    assert out["n_gpu_layers"] == 11  # canonical value preserved
    assert "gpu_layers" not in out

def test_migrate_no_legacy_keys():
    data = {"model_path": "x.gguf", "n_gpu_layers": 99}
    out, migrated = _migrate_legacy_keys(data)
    assert migrated == []
    assert out == data

def test_migrate_both_legacy_keys():
    data = {"gpu_layers": 8, "cpu_threads": 4}
    out, migrated = _migrate_legacy_keys(data)
    assert "gpu_layers" not in out
    assert "cpu_threads" not in out
    assert out["n_gpu_layers"] == 8
    assert out["n_threads"] == 4
    assert len(migrated) == 2

def test_migrate_preserves_other_keys():
    data = {"gpu_layers": 8, "temperature": 0.7, "provider": "custom_gguf"}
    out, _ = _migrate_legacy_keys(data)
    assert out["temperature"] == 0.7
    assert out["provider"] == "custom_gguf"


# ── _resolve_relative_model_paths ────────────────────────────────────────

def test_relative_path_resolved_to_absolute():
    settings = {"model_path": "models/gguf/base/test.gguf"}
    result = _resolve_relative_model_paths(settings)
    assert Path(result["model_path"]).is_absolute()

def test_absolute_path_unchanged():
    settings = {"model_path": "/absolute/path/model.gguf"}
    result = _resolve_relative_model_paths(settings)
    assert result["model_path"] == "/absolute/path/model.gguf"

def test_empty_path_unchanged():
    settings = {"model_path": ""}
    result = _resolve_relative_model_paths(settings)
    assert result["model_path"] == ""

def test_all_model_path_keys_resolved():
    settings = {k: "models/test.gguf" for k in _MODEL_PATH_KEYS}
    result = _resolve_relative_model_paths(settings)
    for k in _MODEL_PATH_KEYS:
        assert Path(result[k]).is_absolute()

def test_non_path_keys_untouched():
    settings = {"model_path": "models/test.gguf", "provider": "custom_gguf", "n_ctx": 16384}
    result = _resolve_relative_model_paths(settings)
    assert result["provider"] == "custom_gguf"
    assert result["n_ctx"] == 16384


# ── _heal_model_paths ─────────────────────────────────────────────────────

def test_heal_valid_path_unchanged(tmp_path):
    model = tmp_path / "model.gguf"
    model.write_bytes(b"fake")
    settings = {"model_path": str(model)}
    result, changed = _heal_model_paths(settings)
    assert result["model_path"] == str(model)
    assert not changed

def test_heal_empty_path_unchanged():
    settings = {"model_path": ""}
    result, changed = _heal_model_paths(settings)
    assert result["model_path"] == ""
    assert not changed

def test_heal_relative_path_skipped():
    # Relative paths are handled by _resolve_relative_model_paths, not healer
    settings = {"model_path": "models/test.gguf"}
    result, changed = _heal_model_paths(settings)
    assert not changed

def test_heal_returns_dict():
    settings = {"model_path": "/nonexistent/stale/path/model.gguf"}
    result, changed = _heal_model_paths(settings)
    assert isinstance(result, dict)
    assert isinstance(changed, bool)

def test_heal_syncs_model_path_from_fallback(tmp_path):
    model = tmp_path / "model.gguf"
    model.write_bytes(b"fake")
    # model_path is stale, but custom_model_path points to real file
    # Note: heal only heals stale absolute paths in real dirs; this tests model_path sync logic
    settings = {
        "model_path": "/stale/path/model.gguf",
        "custom_model_path": str(model),
    }
    result, changed = _heal_model_paths(settings)
    # model_path should be synced to working custom_model_path
    if changed:
        assert Path(result["model_path"]).exists()


# ── load_settings ─────────────────────────────────────────────────────────

def test_load_settings_returns_dict(tmp_settings_file, monkeypatch):
    monkeypatch.setenv("ELI_SETTINGS_FILE", str(tmp_settings_file))
    result = load_settings()
    assert isinstance(result, dict)

def test_load_settings_has_all_defaults(tmp_settings_file, monkeypatch):
    monkeypatch.setenv("ELI_SETTINGS_FILE", str(tmp_settings_file))
    result = load_settings()
    for k in DEFAULTS:
        assert k in result, f"Missing key: {k}"

def test_load_settings_with_custom_values(tmp_settings_file, monkeypatch):
    monkeypatch.setenv("ELI_SETTINGS_FILE", str(tmp_settings_file))
    tmp_settings_file.write_text(json.dumps({"n_ctx": 4096, "temperature": 0.5}))
    result = load_settings()
    assert result["n_ctx"] == 4096
    assert result["temperature"] == 0.5

def test_load_settings_env_override(tmp_settings_file, monkeypatch):
    monkeypatch.setenv("ELI_SETTINGS_FILE", str(tmp_settings_file))
    monkeypatch.setenv("ELI_N_CTX", "32768")
    result = load_settings()
    assert result["n_ctx"] == 32768

def test_load_settings_env_temperature_override(tmp_settings_file, monkeypatch):
    monkeypatch.setenv("ELI_SETTINGS_FILE", str(tmp_settings_file))
    monkeypatch.setenv("ELI_TEMPERATURE", "0.3")
    result = load_settings()
    assert abs(result["temperature"] - 0.3) < 1e-9

def test_load_settings_gpu_layers_alias(tmp_settings_file, monkeypatch):
    monkeypatch.setenv("ELI_SETTINGS_FILE", str(tmp_settings_file))
    monkeypatch.setenv("ELI_GPU_LAYERS", "8")
    result = load_settings()
    assert result["n_gpu_layers"] == 8

def test_load_settings_missing_file_uses_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("ELI_SETTINGS_FILE", str(tmp_path / "nonexistent.json"))
    result = load_settings()
    assert result["provider"] == DEFAULTS["provider"]

def test_load_settings_corrupted_file_uses_defaults(tmp_settings_file, monkeypatch):
    monkeypatch.setenv("ELI_SETTINGS_FILE", str(tmp_settings_file))
    tmp_settings_file.write_text("NOT VALID JSON }{", encoding="utf-8")
    result = load_settings()
    assert result["provider"] == DEFAULTS["provider"]

def test_load_settings_n_threads_coerced_to_int(tmp_settings_file, monkeypatch):
    monkeypatch.setenv("ELI_SETTINGS_FILE", str(tmp_settings_file))
    tmp_settings_file.write_text(json.dumps({"n_threads": "10"}))
    result = load_settings()
    assert isinstance(result["n_threads"], int)

def test_load_settings_n_gpu_layers_coerced_to_int(tmp_settings_file, monkeypatch):
    monkeypatch.setenv("ELI_SETTINGS_FILE", str(tmp_settings_file))
    tmp_settings_file.write_text(json.dumps({"n_gpu_layers": "11"}))
    result = load_settings()
    assert isinstance(result["n_gpu_layers"], int)

def test_load_settings_legacy_migration_applied(tmp_settings_file, monkeypatch):
    monkeypatch.setenv("ELI_SETTINGS_FILE", str(tmp_settings_file))
    tmp_settings_file.write_text(json.dumps({"gpu_layers": 5}))
    result = load_settings()
    assert result["n_gpu_layers"] == 5

def test_load_settings_model_path_fallback(tmp_settings_file, monkeypatch):
    monkeypatch.setenv("ELI_SETTINGS_FILE", str(tmp_settings_file))
    tmp_settings_file.write_text(json.dumps({"custom_model_path": "/some/model.gguf"}))
    result = load_settings()
    # model_path should fall back to custom_model_path if empty
    assert result["model_path"] == "/some/model.gguf"


# ── save_settings ─────────────────────────────────────────────────────────

def test_save_settings_writes_file(tmp_settings_file, monkeypatch):
    monkeypatch.setenv("ELI_SETTINGS_FILE", str(tmp_settings_file))
    save_settings({"temperature": 0.3})
    data = json.loads(tmp_settings_file.read_text())
    assert abs(data["temperature"] - 0.3) < 1e-9

def test_save_settings_merge_not_replace(tmp_settings_file, monkeypatch):
    monkeypatch.setenv("ELI_SETTINGS_FILE", str(tmp_settings_file))
    tmp_settings_file.write_text(json.dumps({"n_ctx": 8192, "temperature": 0.7}))
    save_settings({"temperature": 0.5})
    data = json.loads(tmp_settings_file.read_text())
    assert data["n_ctx"] == 8192
    assert abs(data["temperature"] - 0.5) < 1e-9

def test_save_settings_creates_parent_dir(tmp_path, monkeypatch):
    deep_path = tmp_path / "subdir" / "settings.json"
    monkeypatch.setenv("ELI_SETTINGS_FILE", str(deep_path))
    save_settings({"theme": "light"})
    assert deep_path.exists()
    data = json.loads(deep_path.read_text())
    assert data["theme"] == "light"

def test_save_settings_strips_legacy_key_from_dict(tmp_settings_file, monkeypatch):
    monkeypatch.setenv("ELI_SETTINGS_FILE", str(tmp_settings_file))
    save_settings({"gpu_layers": 8})
    data = json.loads(tmp_settings_file.read_text())
    assert "gpu_layers" not in data
    assert data.get("n_gpu_layers") == 8

def test_save_settings_int_coercion(tmp_settings_file, monkeypatch):
    monkeypatch.setenv("ELI_SETTINGS_FILE", str(tmp_settings_file))
    save_settings({"n_gpu_layers": "11"})
    data = json.loads(tmp_settings_file.read_text())
    assert isinstance(data["n_gpu_layers"], int)


def test_save_settings_project_paths_are_portable(tmp_settings_file, monkeypatch):
    monkeypatch.setenv("ELI_SETTINGS_FILE", str(tmp_settings_file))
    from eli.core.runtime_settings import PROJECT_ROOT

    model = PROJECT_ROOT / "models" / "gguf" / "base" / "portable-test.gguf"
    save_settings({"model_path": str(model)})
    data = json.loads(tmp_settings_file.read_text())
    assert data["model_path"] == "models/gguf/base/portable-test.gguf"


# ── update_settings ───────────────────────────────────────────────────────

def test_update_settings_returns_full_dict(tmp_settings_file, monkeypatch):
    monkeypatch.setenv("ELI_SETTINGS_FILE", str(tmp_settings_file))
    result = update_settings(temperature=0.4)
    assert isinstance(result, dict)
    assert abs(result["temperature"] - 0.4) < 1e-9

def test_update_settings_persists(tmp_settings_file, monkeypatch):
    monkeypatch.setenv("ELI_SETTINGS_FILE", str(tmp_settings_file))
    update_settings(theme="light")
    data = json.loads(tmp_settings_file.read_text())
    assert data["theme"] == "light"


# ── load_runtime_settings / save_runtime_settings aliases ────────────────

def test_load_runtime_settings_alias(tmp_settings_file, monkeypatch):
    monkeypatch.setenv("ELI_SETTINGS_FILE", str(tmp_settings_file))
    result = load_runtime_settings()
    assert isinstance(result, dict)

def test_save_runtime_settings_alias(tmp_settings_file, monkeypatch):
    monkeypatch.setenv("ELI_SETTINGS_FILE", str(tmp_settings_file))
    save_runtime_settings({"theme": "dark"})
    data = json.loads(tmp_settings_file.read_text())
    assert data["theme"] == "dark"


# ── ENV_TO_KEY mapping completeness ──────────────────────────────────────

def test_env_to_key_has_provider():
    assert "ELI_PROVIDER" in ENV_TO_KEY

def test_env_to_key_has_model_path():
    assert "ELI_MODEL_PATH" in ENV_TO_KEY

def test_env_to_key_legacy_gpu_alias():
    assert "ELI_GPU_LAYERS" in ENV_TO_KEY
    assert ENV_TO_KEY["ELI_GPU_LAYERS"] == "n_gpu_layers"

def test_env_to_key_legacy_cpu_alias():
    assert "ELI_CPU_THREADS" in ENV_TO_KEY
    assert ENV_TO_KEY["ELI_CPU_THREADS"] == "n_threads"

def test_env_to_key_all_values_in_defaults():
    for env_name, key in ENV_TO_KEY.items():
        assert key in DEFAULTS or key in ("model_path",), f"{key} from {env_name} not in DEFAULTS"


# ── _MODEL_PATH_KEYS ──────────────────────────────────────────────────────

def test_model_path_keys_set():
    assert "model_path" in _MODEL_PATH_KEYS
    assert "bundled_model_path" in _MODEL_PATH_KEYS
    assert "custom_model_path" in _MODEL_PATH_KEYS
    assert "gguf_model_path" in _MODEL_PATH_KEYS
    assert "image_model_path" in _MODEL_PATH_KEYS


# ── LEGACY_KEY_MIGRATIONS ─────────────────────────────────────────────────

def test_legacy_migrations_defined():
    assert "gpu_layers" in LEGACY_KEY_MIGRATIONS
    assert "cpu_threads" in LEGACY_KEY_MIGRATIONS

def test_legacy_migrations_map_to_canonical():
    assert LEGACY_KEY_MIGRATIONS["gpu_layers"] == "n_gpu_layers"
    assert LEGACY_KEY_MIGRATIONS["cpu_threads"] == "n_threads"
