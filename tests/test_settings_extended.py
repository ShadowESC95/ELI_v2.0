"""Extended settings tests — ~100 parametrized cases."""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from eli.core.runtime_settings import (
    load_settings, save_settings, _coerce_value,
    DEFAULTS, INT_KEYS, FLOAT_KEYS, BOOL_KEYS, ENV_TO_KEY,
)


# ── All defaults have correct types ──────────────────────────────────────

@pytest.mark.parametrize("key", list(INT_KEYS))
def test_default_int_key_is_int(key):
    val = DEFAULTS.get(key)
    if val is not None:
        assert isinstance(val, int), f"Default for {key} should be int, got {type(val)}"

@pytest.mark.parametrize("key", list(FLOAT_KEYS))
def test_default_float_key_is_float(key):
    val = DEFAULTS.get(key)
    if val is not None:
        assert isinstance(val, (int, float)), f"Default for {key} should be numeric"

@pytest.mark.parametrize("key", list(BOOL_KEYS))
def test_default_bool_key_is_bool(key):
    val = DEFAULTS.get(key)
    if val is not None:
        assert isinstance(val, bool), f"Default for {key} should be bool"


# ── Coercion — all int keys ───────────────────────────────────────────────

@pytest.mark.parametrize("key", list(INT_KEYS))
def test_coerce_int_key_from_string(key):
    default = DEFAULTS.get(key, 100)
    result = _coerce_value(key, str(default))
    assert isinstance(result, int)
    assert result == int(default)

@pytest.mark.parametrize("key", list(INT_KEYS))
def test_coerce_int_key_invalid(key):
    result = _coerce_value(key, "not_a_number")
    # Should return default or None
    assert result is None or isinstance(result, int)


# ── Coercion — all float keys ─────────────────────────────────────────────

@pytest.mark.parametrize("key", list(FLOAT_KEYS))
def test_coerce_float_key_from_string(key):
    default = DEFAULTS.get(key, 0.5)
    result = _coerce_value(key, str(default))
    assert isinstance(result, float)
    assert abs(result - float(default)) < 1e-6


# ── Coercion — all bool keys ──────────────────────────────────────────────

BOOL_TRUE_VALUES = ["1", "true", "True", "TRUE", "yes", "Yes", "YES", "on", "On", "ON"]
BOOL_FALSE_VALUES = ["0", "false", "False", "FALSE", "no", "No", "NO", "off", "Off", "OFF"]

@pytest.mark.parametrize("val", BOOL_TRUE_VALUES)
def test_coerce_bool_true_values(val):
    result = _coerce_value("auto_speak", val)
    assert result is True

@pytest.mark.parametrize("val", BOOL_FALSE_VALUES)
def test_coerce_bool_false_values(val):
    result = _coerce_value("auto_speak", val)
    assert result is False


# ── ENV overrides for all ENV_TO_KEY entries ──────────────────────────────

@pytest.mark.parametrize("env_name,key", list(ENV_TO_KEY.items())[:20])
def test_env_override_applied(env_name, key, tmp_settings_file, monkeypatch):
    monkeypatch.setenv("ELI_SETTINGS_FILE", str(tmp_settings_file))
    if key in INT_KEYS:
        monkeypatch.setenv(env_name, "42")
        s = load_settings()
        assert s[key] == 42
    elif key in FLOAT_KEYS:
        monkeypatch.setenv(env_name, "0.3")
        s = load_settings()
        assert abs(s[key] - 0.3) < 1e-9
    elif key in BOOL_KEYS:
        monkeypatch.setenv(env_name, "true")
        s = load_settings()
        assert s[key] is True
    else:
        monkeypatch.setenv(env_name, "test_value")
        s = load_settings()
        assert s[key] == "test_value"


# ── Save then load roundtrip for all canonical keys ───────────────────────

ROUNDTRIP_VALUES = {
    "provider": "ollama",
    "ollama_model": "llama3",
    "user_name": "TestUser",
    "user_text_color": "#FF0000",
    "theme": "light",
    "image_backend": "stable_diffusion",
    "image_device": "cpu",
    "image_quality_preset": "fast",
    "tts_voice": "en_US-ryan-high",
}

@pytest.mark.parametrize("key,value", list(ROUNDTRIP_VALUES.items()))
def test_save_load_roundtrip_string(key, value, tmp_settings_file, monkeypatch):
    monkeypatch.setenv("ELI_SETTINGS_FILE", str(tmp_settings_file))
    save_settings({key: value})
    s = load_settings()
    assert s[key] == value

ROUNDTRIP_INTS = {
    "n_ctx": 8192,
    "max_tokens": 1024,
    "n_gpu_layers": 8,
    "n_threads": 6,
    "batch_size": 256,
    "image_steps": 20,
    "image_default_count": 2,
}

@pytest.mark.parametrize("key,value", list(ROUNDTRIP_INTS.items()))
def test_save_load_roundtrip_int(key, value, tmp_settings_file, monkeypatch):
    monkeypatch.setenv("ELI_SETTINGS_FILE", str(tmp_settings_file))
    save_settings({key: value})
    s = load_settings()
    assert s[key] == value
    assert isinstance(s[key], int)

ROUNDTRIP_FLOATS = {
    "temperature": 0.3,
    "top_p": 0.8,
    "repeat_penalty": 1.05,
    "image_guidance": 5.0,
}

@pytest.mark.parametrize("key,value", list(ROUNDTRIP_FLOATS.items()))
def test_save_load_roundtrip_float(key, value, tmp_settings_file, monkeypatch):
    monkeypatch.setenv("ELI_SETTINGS_FILE", str(tmp_settings_file))
    save_settings({key: value})
    s = load_settings()
    assert abs(s[key] - value) < 1e-6

ROUNDTRIP_BOOLS = {
    "auto_speak": True,
    "auto_speak": False,
    "use_mmap": True,
    "use_mlock": False,
    "auto_save": True,
    "log_to_file": False,
    "auto_load": True,
    "mic_enabled": True,
    "first_run_complete": True,
}

@pytest.mark.parametrize("key,value", list(ROUNDTRIP_BOOLS.items()))
def test_save_load_roundtrip_bool(key, value, tmp_settings_file, monkeypatch):
    monkeypatch.setenv("ELI_SETTINGS_FILE", str(tmp_settings_file))
    save_settings({key: value})
    s = load_settings()
    assert s[key] is value
    assert isinstance(s[key], bool)


# ── Multiple saves accumulate ─────────────────────────────────────────────

def test_multiple_saves_accumulate(tmp_settings_file, monkeypatch):
    monkeypatch.setenv("ELI_SETTINGS_FILE", str(tmp_settings_file))
    save_settings({"n_ctx": 8192})
    save_settings({"temperature": 0.5})
    save_settings({"theme": "light"})
    s = load_settings()
    assert s["n_ctx"] == 8192
    assert abs(s["temperature"] - 0.5) < 1e-9
    assert s["theme"] == "light"


# ── Settings file is valid JSON ───────────────────────────────────────────

def test_saved_settings_is_valid_json(tmp_settings_file, monkeypatch):
    monkeypatch.setenv("ELI_SETTINGS_FILE", str(tmp_settings_file))
    save_settings({"temperature": 0.7, "n_ctx": 16384, "theme": "dark"})
    text = tmp_settings_file.read_text()
    data = json.loads(text)  # should not raise
    assert isinstance(data, dict)
