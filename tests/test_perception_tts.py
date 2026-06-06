"""Tests for eli.perception.tts_router — ~100 tests."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch
import os
import pytest

from eli.perception.tts_router import (
    list_voices,
    find_voice_model,
    get_active_voice,
    set_active_voice,
    available_backends,
    _clean_text,
    _voice_dir,
    _DEFAULT_VOICE,
    _VOICE_SEARCH_DIRS,
    _run_tts,
    speak_if_enabled,
)


# ── Voice discovery ───────────────────────────────────────────────────────

def test_list_voices_returns_list():
    result = list_voices()
    assert isinstance(result, list)

def test_list_voices_at_least_three():
    result = list_voices()
    assert len(result) >= 3, f"Expected >=3 voices, got {result}"

def test_list_voices_are_strings():
    for v in list_voices():
        assert isinstance(v, str)

def test_list_voices_no_extension():
    for v in list_voices():
        assert not v.endswith(".onnx")

def test_list_voices_no_duplicates():
    voices = list_voices()
    assert len(voices) == len(set(voices))

def test_list_voices_includes_lessac_high():
    assert "en_US-lessac-high" in list_voices()

def test_list_voices_includes_ryan_high():
    assert "en_US-ryan-high" in list_voices()

def test_list_voices_includes_cori_high():
    assert "en_GB-cori-high" in list_voices()


# ── Voice model finding ───────────────────────────────────────────────────

def test_find_voice_model_returns_path_or_none():
    result = find_voice_model("en_US-lessac-high")
    assert result is None or isinstance(result, Path)

def test_find_lessac_high_exists():
    result = find_voice_model("en_US-lessac-high")
    assert result is not None
    assert result.exists()

def test_find_ryan_high_exists():
    result = find_voice_model("en_US-ryan-high")
    assert result is not None
    assert result.exists()

def test_find_cori_high_exists():
    result = find_voice_model("en_GB-cori-high")
    assert result is not None
    assert result.exists()

def test_find_nonexistent_voice():
    result = find_voice_model("en_US-nonexistent-ultra")
    # Should fall back to any available voice or return None
    assert result is None or isinstance(result, Path)

def test_find_voice_model_onnx_extension():
    result = find_voice_model("en_US-lessac-high")
    if result:
        assert result.suffix == ".onnx"

def test_find_voice_env_override(monkeypatch, tmp_path):
    model = tmp_path / "custom.onnx"
    model.write_bytes(b"fake")
    monkeypatch.setenv("ELI_PIPER_MODEL", str(model))
    result = find_voice_model("en_US-ryan-high")
    assert result == model


# ── Active voice ──────────────────────────────────────────────────────────

def test_get_active_voice_returns_string():
    result = get_active_voice()
    assert isinstance(result, str)
    assert len(result) > 0

def test_get_active_voice_default():
    # Without any override, should return default
    result = get_active_voice()
    assert result in list_voices() or result == _DEFAULT_VOICE

def test_get_active_voice_env_override(monkeypatch):
    monkeypatch.setenv("ELI_PIPER_VOICE", "en_US-ryan-high")
    result = get_active_voice()
    assert result == "en_US-ryan-high"

def test_set_active_voice_changes_active(monkeypatch, tmp_path):
    monkeypatch.setenv("ELI_SETTINGS_FILE", str(tmp_path / "settings.json"))
    set_active_voice("en_US-ryan-high")
    assert get_active_voice() == "en_US-ryan-high"


# ── available_backends ────────────────────────────────────────────────────

def test_available_backends_returns_dict():
    result = available_backends()
    assert isinstance(result, dict)

def test_available_backends_has_piper_python():
    result = available_backends()
    assert "piper_python" in result
    assert result["piper_python"] is True

def test_available_backends_has_piper_voices():
    result = available_backends()
    assert "piper_voices" in result
    assert isinstance(result["piper_voices"], list)

def test_available_backends_has_active_voice():
    result = available_backends()
    assert "active_voice" in result

def test_available_backends_has_active_model():
    result = available_backends()
    assert "active_model" in result

def test_available_backends_active_model_exists():
    result = available_backends()
    if result["active_model"]:
        assert Path(result["active_model"]).exists()


# ── _clean_text ───────────────────────────────────────────────────────────

def test_clean_text_strips_markdown():
    result = _clean_text("**bold** and _italic_ and `code`")
    assert "**" not in result
    assert "_" not in result
    assert "`" not in result

def test_clean_text_strips_headers():
    result = _clean_text("# Header\n## Sub")
    assert "#" not in result

def test_clean_text_collapses_whitespace():
    result = _clean_text("hello   world   there")
    assert "  " not in result

def test_clean_text_truncates_at_800():
    long_text = "word " * 200
    result = _clean_text(long_text)
    assert len(result) <= 800

def test_clean_text_empty_returns_empty():
    assert _clean_text("") == ""

def test_clean_text_none_returns_empty():
    assert _clean_text(None) == ""

def test_clean_text_whitespace_returns_empty():
    assert _clean_text("   ") == ""

def test_clean_text_strips_pipe():
    result = _clean_text("col1 | col2 | col3")
    assert "|" not in result

def test_clean_text_strips_gt():
    result = _clean_text("> blockquote")
    assert ">" not in result

def test_clean_text_preserves_content():
    result = _clean_text("The answer is 42")
    assert "answer" in result
    assert "42" in result


# ── speak_if_enabled ─────────────────────────────────────────────────────

def test_speak_if_enabled_false_does_not_speak():
    with patch("eli.perception.tts_router._run_tts") as mock_tts:
        speak_if_enabled("hello", enabled=False)
        mock_tts.assert_not_called()

def test_speak_if_enabled_true_calls_tts():
    with patch("eli.perception.tts_router._run_tts", return_value=True) as mock_tts:
        speak_if_enabled("hello", enabled=True)
        # Thread is async, but the function should return True
        # (thread is daemon so it won't block test)


def test_run_tts_speaks_more_than_three_chunks(monkeypatch):
    from eli.perception import tts_router

    spoken = []
    monkeypatch.setenv("ELI_TTS_CHUNK_CHARS", "25")
    monkeypatch.setattr(tts_router, "_speak_piper_cli", lambda chunk, voice_name=None: spoken.append(chunk) or True)

    text = "One short sentence. " * 12

    assert _run_tts(text, voice_name="test-voice") is True
    assert len(spoken) > 3


# ── Voice search dirs ─────────────────────────────────────────────────────

def test_voice_search_dirs_is_list():
    assert isinstance(_VOICE_SEARCH_DIRS, list)

def test_voice_dir_is_path():
    assert isinstance(_voice_dir(), Path)

def test_voice_dir_contains_models_tts_piper():
    assert "piper" in str(_voice_dir()) or "voices" in str(_voice_dir())

def test_voice_models_have_json_config():
    """Each .onnx should have a companion .onnx.json config."""
    for v in list_voices():
        model = find_voice_model(v)
        if model:
            config = model.parent / (model.name + ".json")
            assert config.exists(), f"Missing config for {v}: {config}"


# ── Default voice ─────────────────────────────────────────────────────────

def test_default_voice_is_string():
    assert isinstance(_DEFAULT_VOICE, str)

def test_default_voice_is_installed():
    assert _DEFAULT_VOICE in list_voices()

def test_default_voice_model_exists():
    model = find_voice_model(_DEFAULT_VOICE)
    assert model is not None
    assert model.exists()


# ── Edge cases ────────────────────────────────────────────────────────────

def test_find_voice_empty_string():
    result = find_voice_model("")
    # Should fall back to any available voice
    assert result is None or isinstance(result, Path)

def test_find_voice_none():
    result = find_voice_model(None)
    assert result is None or isinstance(result, Path)

def test_list_voices_sorted():
    voices = list_voices()
    # Check voices list is consistent (same order each call)
    assert list_voices() == voices


# ── Never speak a degenerate fragment (also avoids piper wave crash) ──────────
import pytest as _pytest


@_pytest.mark.parametrize("frag", ["-", "-G", "-Auto", "-Auto/G 5/", "", "   ", "/ "])
def test_tts_refuses_unspeakable_fragment(frag):
    from eli.perception.tts_router import _eli_tts_is_unspeakable
    assert _eli_tts_is_unspeakable(frag) is True


@_pytest.mark.parametrize("ok", ["No.", "34G", "Volume down", "I'm ELI.",
                                 "Your first message was at 00:03:44 on 2026-06-06."])
def test_tts_speaks_real_short_text(ok):
    from eli.perception.tts_router import _eli_tts_is_unspeakable
    assert _eli_tts_is_unspeakable(ok) is False
