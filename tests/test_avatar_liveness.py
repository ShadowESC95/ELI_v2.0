"""Live avatar: expression_state flags, pitch-in-audio, and the face reacting to
speaking/thinking (lip-sync + a focused look while generating)."""
from __future__ import annotations

import io
import wave

import pytest


# ── expression_state ──────────────────────────────────────────────────────────
def test_speaking_flag_and_ttl(monkeypatch):
    from eli.cognition import expression_state as es
    es.set_speaking(False)
    assert not es.is_speaking()
    es.set_speaking(True)
    assert es.is_speaking()
    es.set_speaking(True, ttl=-1)   # already expired
    assert not es.is_speaking()
    es.set_speaking(False)


def test_thinking_flag():
    from eli.cognition import expression_state as es
    es.set_thinking(True); assert es.is_thinking()
    es.set_thinking(False); assert not es.is_thinking()


def test_amplitude_clamped():
    from eli.cognition import expression_state as es
    es.set_amplitude(2.0); assert es.amplitude() == 1.0
    es.set_amplitude(-1.0); assert es.amplitude() == 0.0
    es.set_amplitude(0.5); assert es.amplitude() == 0.5
    es.set_amplitude("bad"); assert es.amplitude() == 0.0


# ── pitch in audio ────────────────────────────────────────────────────────────
def _dur(w):
    with wave.open(io.BytesIO(w)) as x:
        return x.getnframes() / x.getframerate()


@pytest.mark.skipif(__import__("shutil").which("ffmpeg") is None, reason="ffmpeg needed for pitch")
def test_pitch_changes_audio_per_emotion():
    from eli.cognition import tone_adaptor as ta
    from eli.perception import tts_router as tr
    if tr.find_voice_model("en_US-amy-medium") is None:
        pytest.skip("no piper voice on this box")
    text = "This is a short test sentence."
    ta.clear_tone(); neutral = tr.synthesize_wav(text, "en_US-amy-medium")
    ta.set_tone("sad"); sad = tr.synthesize_wav(text, "en_US-amy-medium")
    ta.clear_tone()
    assert neutral and sad
    assert neutral != sad   # pitch (and pace) shift → distinct audio


def test_apply_tone_pitch_is_noop_at_neutral():
    from eli.cognition import tone_adaptor as ta
    from eli.perception import tts_router as tr
    ta.clear_tone()  # neutral → pitch 0 → bytes unchanged
    fake = b"RIFFxxxxWAVEfmt "  # not real audio; neutral must return it as-is
    assert tr._apply_tone_pitch(fake) is fake
    assert tr._apply_tone_pitch(None) is None


# ── face reacts to state (skipped under the harness Qt mock) ──────────────────
def _qt_mocked():
    from eli.gui.qt_compat import QWidget
    return "mock" in type(QWidget).__name__.lower() or type(QWidget).__module__.startswith("unittest")


def test_face_shows_thinking_and_lipsync():
    if _qt_mocked():
        pytest.skip("Qt mocked")
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from eli.gui.qt_compat import QApplication
    QApplication.instance() or QApplication([])
    from eli.gui.widgets.eli_face import EliFaceWidget
    from eli.cognition import expression_state as es
    f = EliFaceWidget(poll_tone=False, size=120)
    # thinking → reflective face after a poll
    es.set_thinking(True); f._poll_tone()
    assert f.current_expression() == "reflective"
    es.set_thinking(False)
    # speaking → mouth opens over a few ticks
    es.set_speaking(True)
    for _ in range(10):
        f._tick()
    assert f._mouth_lipsync > 0.05, "lip-sync mouth should open while speaking"
    es.set_speaking(False)
    for _ in range(12):
        f._tick()
    assert f._mouth_lipsync < 0.05, "mouth should close when speech ends"
