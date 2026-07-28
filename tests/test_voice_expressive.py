"""Expressive-voice upgrade: robotic-voice removal, Piper prosody, natural neural voice.

- Piper is given expressive prosody (sentence pauses so ?/!/. land) — the flat-Amy fix.
- espeak `sys:` and Piper low/x_low voices are hidden by default (kept as last resort).
- XTTS-v2 exposed as a general `natural:` backend (no clone), with graceful Piper fallback.
"""
from __future__ import annotations

import os

import pytest

from eli.perception import tts_router as tr
from eli.perception import tts_xtts as X
from eli.runtime import voice_assets as va


# ── Piper prosody ─────────────────────────────────────────────────────────────
def test_prosody_args_present_by_default():
    args = tr._piper_prosody_args()
    assert "--sentence_silence" in args  # the pause-at-full-stop that Amy was missing
    assert "--noise_scale" in args and "--length_scale" in args


def test_prosody_can_be_disabled(monkeypatch):
    monkeypatch.setenv("ELI_TTS_PROSODY", "0")
    assert tr._piper_prosody_args() == []


def test_env_overrides_prosody(monkeypatch):
    monkeypatch.setenv("ELI_TTS_SENTENCE_SILENCE", "0.9")
    args = tr._piper_prosody_args()
    i = args.index("--sentence_silence")
    assert args[i + 1] == "0.9"


# ── Robotic-voice removal ─────────────────────────────────────────────────────
def test_low_quality_detection():
    assert tr._is_low_quality_piper("en_US-foo-x_low")
    assert tr._is_low_quality_piper("en_US-foo-low")
    assert not tr._is_low_quality_piper("en_US-amy-medium")


def test_default_list_hides_robotic_and_low_quality():
    voices = tr.list_voices()
    assert not any(v.startswith("sys:") for v in voices), "espeak voices must be hidden"
    assert not any(tr._is_low_quality_piper(v) for v in voices), "low-qual voices must be hidden"
    # there should still be natural-sounding voices offered
    assert any(v.startswith("en_") and v.endswith(("-medium", "-high")) for v in voices)


def test_robotic_voices_restorable(monkeypatch):
    monkeypatch.setenv("ELI_TTS_ALLOW_ROBOTIC", "1")
    # only meaningful if the box has any system voices; assert the flag is read
    assert tr._allow_robotic_voices() is True


# ── Natural neural voice (XTTS-v2) ────────────────────────────────────────────
def test_natural_voice_metadata_is_static_and_cheap():
    # meta lookup must not require the TTS package or load the model
    assert X.natural_voice_meta("natural:james")["gender"] == "male"
    assert X.natural_voice_meta("natural:sophia")["gender"] == "female"


def test_list_natural_voices_empty_without_extra(monkeypatch):
    monkeypatch.setattr(X, "natural_available", lambda: False)
    assert X.list_natural_voices() == []


def test_list_natural_voices_when_available(monkeypatch):
    monkeypatch.setattr(X, "natural_available", lambda: True)
    ids = X.list_natural_voices()
    assert "natural:sophia" in ids and "natural:james" in ids


def test_natural_synth_falls_back_gracefully_without_extra(monkeypatch):
    monkeypatch.setattr(X, "natural_available", lambda: False)
    assert X.synthesize_natural_wav("hello", "natural:sophia") is None


def test_device_selection_is_forceable(monkeypatch):
    monkeypatch.setenv("ELI_XTTS_DEVICE", "cpu")
    assert X._select_device() == "cpu"
    monkeypatch.setenv("ELI_XTTS_DEVICE", "cuda")
    assert X._select_device() == "cuda"


# ── Routing / resolver for the natural voice ──────────────────────────────────
@pytest.mark.parametrize("text,expected", [
    ("use the natural voice", "natural:sophia"),
    ("switch to a human voice", "natural:sophia"),
    ("use a realistic male voice", "natural:james"),
    ("use a natural female voice", "natural:sophia"),
])
def test_natural_voice_resolves(text, expected):
    assert va.resolve_voice_query(text)["voice"] == expected


def test_set_voice_accepts_natural_without_it_being_installed():
    from eli.execution.executor_enhanced import execute
    prev = tr.get_active_voice()
    try:
        r = execute("SET_VOICE", {"query": "use the natural voice"})
        assert r.get("ok") and r.get("voice") == "natural:sophia"
    finally:
        tr.set_active_voice(prev)


def test_natural_voice_synth_falls_back_to_piper_end_to_end():
    """With XTTS absent, a natural: voice must still produce audio (via Piper)."""
    wav = tr.synthesize_wav("This is a test.", "natural:sophia")
    assert wav and len(wav) > 1000


# ── Voice creation engine (drop-in wav/mp4) ───────────────────────────────────
import subprocess as _sp
import shutil as _sh


def _make_audio(path, ext, freq=200):
    _sp.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", f"sine=frequency={freq}:duration=2", "-ac", "1", str(path)],
            check=True, timeout=30)


@pytest.mark.skipif(not _sh.which("ffmpeg"), reason="ffmpeg required to build a reference")
@pytest.mark.parametrize("ext", ["wav", "mp4", "mp3"])
def test_create_voice_from_dropped_in_file(ext, tmp_path, monkeypatch):
    from eli.execution.executor_enhanced import execute
    from eli.perception import tts_xtts, tts_router
    monkeypatch.setattr(tts_xtts, "_refs_dir", lambda: tmp_path)
    reg = tmp_path / "clones.json"
    monkeypatch.setattr(tts_xtts, "_registry_path", lambda: reg)
    src = tmp_path / f"sample.{ext}"
    _make_audio(src, ext)
    prev = tts_router.get_active_voice()
    try:
        r = execute("CREATE_VOICE", {"name": f"test_{ext}", "file": str(src)})
        assert r.get("ok"), r
        assert r.get("voice") == f"clone:test_{ext}"
        assert any(c["id"] == f"clone:test_{ext}" for c in tts_xtts.list_clones())
    finally:
        tts_router.set_active_voice(prev)


def test_create_voice_needs_a_file():
    from eli.execution.executor_enhanced import execute
    r = execute("CREATE_VOICE", {"name": "x"})
    assert r.get("ok") is False and "audio file" in r.get("content", "").lower()


def test_create_voice_missing_file_is_honest():
    from eli.execution.executor_enhanced import execute
    r = execute("CREATE_VOICE", {"name": "x", "file": "/no/such/clip.mp4"})
    assert r.get("ok") is False and "couldn't find" in r.get("content", "").lower()


@pytest.mark.parametrize("text", [
    "create a voice called Nova from /tmp/clip.mp4",
    "make an ELI voice from recording.wav",
    "clone this voice from my sample.mp3",
])
def test_create_voice_routes(text):
    from eli.execution.router_enhanced import route
    assert (route(text).get("action") or "").upper() == "CREATE_VOICE"


def test_create_voice_registered_capability():
    import json
    from pathlib import Path
    m = json.loads((Path(__file__).resolve().parents[1] / "capability_manifest.json").read_text())
    by = {c["action"]: c for c in m["capabilities"]}
    assert "CREATE_VOICE" in by and by["CREATE_VOICE"]["routable"]
