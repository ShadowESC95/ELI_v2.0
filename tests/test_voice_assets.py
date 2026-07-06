"""Voice asset readiness — catches false positives from OS/espeak voices."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from eli.runtime import voice_assets as va


def test_piper_voice_ready_ignores_system_voices_only(monkeypatch, tmp_path):
    """Linux hosts expose many sys: espeak voices; Piper must not count as present."""
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setattr(va, "_piper_dest", lambda: empty / "models" / "tts" / "piper")
    with patch("eli.perception.tts_router.find_voice_model", return_value=None):
        with patch("eli.perception.tts_router.list_voices", return_value=["sys:gmw/en-us", "sys:gmw/en"]):
            with patch("eli.core.paths.project_root", return_value=empty):
                assert va._piper_present() is False
                assert va.piper_voice_ready() is False


def test_piper_voice_ready_detects_onnx_on_disk(monkeypatch, tmp_path):
    dest = tmp_path / "models" / "tts" / "piper"
    dest.mkdir(parents=True)
    (dest / "en_US-amy-medium.onnx").write_bytes(b"x" * 64)
    (dest / "en_US-amy-medium.onnx.json").write_text("{}")
    monkeypatch.setattr(va, "_piper_dest", lambda: dest)
    with patch("eli.perception.tts_router.find_voice_model", return_value=None):
        assert va.piper_voice_ready() is True


def test_whisper_cache_ready_resolves_relative_to_project_root(monkeypatch, tmp_path):
    from eli.perception import local_whisper_stt as stt

    root = tmp_path / "ELI_v2-2.0.10-linux-portable"
    whisper = root / "models" / "whisper"
    snap = whisper / "models--Systran--faster-whisper-small.en" / "snapshots" / "abc"
    snap.mkdir(parents=True)
    (snap / "config.json").write_text("{}")
    monkeypatch.setenv("ELI_PROJECT_ROOT", str(root))
    monkeypatch.chdir(tmp_path)  # cwd != install root
    assert stt.whisper_cache_ready() is True
    model, model_dir, *_ = stt._model_settings()
    assert Path(model_dir).is_absolute()
    assert str(root) in model_dir
