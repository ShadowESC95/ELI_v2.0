"""Locks for the STT noise self-heal.

The failure being guarded: when the room's noise floor sits ABOVE
`energy_threshold`, the phrase detector can never observe the silence it needs to END
a phrase. Every cycle runs to the phrase cap, captures seconds of noise, transcribes
to nothing, and repeats — the microphone is functionally dead and nothing anywhere
says so. Measured on a real machine: speaker bleed from music lifted the mic from
456 RMS to 7924, putting 85% of frames over the 1200 threshold.

Before this, there was no way out of that state: the only recalibration path required
`_silent_streak >= 60`, which cannot accumulate while noise keeps producing captures,
AND was gated on ELI_STT_CALIBRATE, which defaults to "0".
"""
import types

import pytest

from eli.perception import audio_stt


class _Recognizer:
    def __init__(self, threshold):
        self.energy_threshold = float(threshold)


def _stt(threshold=1200.0, base=1200.0):
    """A stand-in carrying only what the adaptation methods touch — no microphone."""
    obj = types.SimpleNamespace()
    obj.recognizer = _Recognizer(threshold)
    obj._threshold_base = base
    obj._noise_stuck_streak = 0
    obj._adapt_threshold_to_noise = types.MethodType(
        audio_stt.ELIAudioSTT._adapt_threshold_to_noise, obj)
    obj._decay_threshold_toward_base = types.MethodType(
        audio_stt.ELIAudioSTT._decay_threshold_toward_base, obj)
    return obj


# ── lifting the gate out of the noise ───────────────────────────────────────
def test_threshold_lifts_above_measured_noise():
    """The real numbers from the incident: 1200 threshold, 7924 RMS of bleed."""
    s = _stt(threshold=1200.0)

    assert s._adapt_threshold_to_noise(7924) is True
    # Must clear the noise, or the phrase still never ends.
    assert s.recognizer.energy_threshold > 7924


def test_lift_is_bounded_by_the_adaptive_cap(monkeypatch):
    monkeypatch.setattr(audio_stt, "_STT_ADAPTIVE_CAP", 12000.0)
    s = _stt(threshold=1200.0)

    s._adapt_threshold_to_noise(500000)

    assert s.recognizer.energy_threshold == 12000.0


def test_marginal_noise_does_not_ratchet_the_gate():
    """Without this, a noise reading barely above the gate would creep it upward on
    every cycle until nothing could ever be heard."""
    s = _stt(threshold=1200.0)

    assert s._adapt_threshold_to_noise(1005) is False
    assert s.recognizer.energy_threshold == 1200.0


def test_lift_is_a_noop_when_adaptation_is_disabled(monkeypatch):
    monkeypatch.setattr(audio_stt, "_STT_ADAPTIVE", False)
    s = _stt(threshold=1200.0)

    assert s._adapt_threshold_to_noise(7924) is False
    assert s.recognizer.energy_threshold == 1200.0


@pytest.mark.parametrize("bad_rms", [0, -1])
def test_nonsense_noise_reading_is_ignored(bad_rms):
    s = _stt(threshold=1200.0)

    assert s._adapt_threshold_to_noise(bad_rms) is False
    assert s.recognizer.energy_threshold == 1200.0


# ── and coming back down again ──────────────────────────────────────────────
def test_threshold_decays_back_toward_base():
    """A self-heal that only ever tightens is just a slower way to go deaf."""
    s = _stt(threshold=9600.0, base=1200.0)

    assert s._decay_threshold_toward_base() is True
    assert s.recognizer.energy_threshold < 9600.0


def test_decay_never_goes_below_base():
    s = _stt(threshold=1300.0, base=1200.0)

    for _ in range(50):
        s._decay_threshold_toward_base()

    assert s.recognizer.energy_threshold == pytest.approx(1200.0)


def test_decay_is_a_noop_once_already_at_base():
    s = _stt(threshold=1200.0, base=1200.0)

    assert s._decay_threshold_toward_base() is False


def test_repeated_decay_fully_recovers_from_a_noise_episode():
    """End to end: drowned by music, then the music stops — sensitivity must return."""
    s = _stt(threshold=1200.0, base=1200.0)
    s._adapt_threshold_to_noise(7924)
    assert s.recognizer.energy_threshold > 7924

    for _ in range(50):
        s._decay_threshold_toward_base()

    assert s.recognizer.energy_threshold == pytest.approx(1200.0)


# ── wiring ──────────────────────────────────────────────────────────────────
def test_adaptation_is_on_by_default_and_decoupled_from_startup_calibration():
    """ELI_STT_CALIBRATE means 'measure ambient at startup' and is off by default.
    Gating runtime adaptation on it meant the configuration that most needs to adapt
    was the one that could not."""
    assert audio_stt._STT_ADAPTIVE is True
    assert audio_stt._STT_ADAPTIVE_CAP > 2000, (
        "the startup cap of 2000 cannot gate out ~8000 RMS speaker bleed"
    )
    assert audio_stt._STT_NOISE_STUCK_CYCLES >= 2, "one loud bang must not retune the mic"


def test_the_speaking_lock_holds_for_as_long_as_the_voice_speaks(tmp_path):
    """Taken as stale after 30 seconds, a minute-long reply was heard by the mic and transcribed."""
    import os
    import subprocess
    import sys
    import time
    from eli.perception.audio_stt import speaking_lock_held
    lock = tmp_path / "speaking.lock"
    assert not speaking_lock_held(lock)
    lock.write_text(str(os.getpid()))
    long_ago = time.time() - 3600
    os.utime(lock, (long_ago, long_ago))
    assert speaking_lock_held(lock), "a long reply is still being spoken"
    ended = subprocess.run([sys.executable, "-c", "import os; print(os.getpid())"],
                           capture_output=True, text=True, check=True).stdout.strip()
    lock.write_text(ended)
    assert not speaking_lock_held(lock) and not lock.exists(), "left by a process that has ended"


def test_a_voice_command_said_during_a_reply_is_sent_after_it(monkeypatch):
    """"computer, one more" said while a reply was coming was dropped."""
    import types
    import eli.gui.eli_pro_audio_gui_v2_0 as gui
    from eli.gui.eli_pro_audio_gui_v2_0 import EliMainWindow as _Window
    later, sent = [], []
    monkeypatch.setattr(gui.QTimer, "singleShot", lambda ms, fn: later.append(fn))
    box = types.SimpleNamespace(text="", setPlainText=lambda t: setattr(box, "text", t))
    win = types.SimpleNamespace(is_generating=True, _voice_waiting=["one more"], chat_input=box,
                                send_message=lambda: sent.append(box.text))
    win._send_waiting_voice = lambda: _Window._send_waiting_voice(win)
    _Window._send_waiting_voice(win)
    assert sent == [] and later, "waits while the reply is coming"
    win.is_generating = False
    later.pop()()
    assert sent == ["one more"] and win._voice_waiting == []


# ── the voice profile learns the owner's speech, not the room's music ─────────
def _scripted_listener(monkeypatch, said, *, threshold=1200.0, base=1200.0, media_playing=False):
    """The real listen loop with the microphone and Whisper stood in: each capture in `said` is
    (transcript, rms); nothing is heard, played or transcribed for real."""
    import threading
    import numpy as np
    from eli.perception import local_whisper_stt
    sr = audio_stt.sr
    monkeypatch.setenv("ELI_VOICE_TONE", "0")
    monkeypatch.setenv("ELI_WAKE_ACOUSTIC", "0")
    monkeypatch.setattr(audio_stt, "_eli_media_probably_audible", lambda: media_playing)
    monkeypatch.setattr(audio_stt, "_eli_duck_output", lambda: None)
    monkeypatch.setattr(audio_stt, "media_player_duck_pause", lambda: None)
    monkeypatch.setattr(local_whisper_stt, "heard_clearly", lambda text: True)
    stt = audio_stt.ELIAudioSTT.__new__(audio_stt.ELIAudioSTT)
    script = list(said)
    transcripts = {}

    class _Mic:
        def __enter__(self):
            return types.SimpleNamespace(stream=None, CHUNK=1024, SAMPLE_RATE=16000, SAMPLE_WIDTH=2)

        def __exit__(self, *a):
            return False

    def _capture(*_a, **_k):
        if not script:
            stt._stop_event.set()
            raise sr.WaitTimeoutError("done")
        text, level = script.pop(0)
        pcm = (np.sin(np.arange(16000) / 3.0) * level * np.sqrt(2)).astype("<i2").tobytes()
        audio = sr.AudioData(pcm, 16000, 2)
        transcripts[id(audio)] = text
        return audio

    stt.recognizer = types.SimpleNamespace(energy_threshold=threshold, pause_threshold=1.2, non_speaking_duration=0.35,
                                           listen=_capture)
    stt._listen_adaptive_pause = _capture
    stt._recognize = lambda audio: transcripts.get(id(audio), "")
    stt.microphone = _Mic()
    stt.is_listening, stt._stop_event, stt._state_lock = True, threading.Event(), threading.Lock()
    stt._thread, stt.callback, stt.audio_queue = None, None, __import__("queue").Queue()
    stt._voice_gate = audio_stt.VoiceGate()
    stt._eli_duck_snapshot, stt._eli_ignore_until, stt._eli_ignore_reason = None, 0.0, ""
    stt._threshold_base, stt._noise_stuck_streak = base, 0
    stt._voice_profile = {"count": 0, "energy_mean": 0.0}
    stt._save_voice_profile = lambda: None
    return stt


_SONG = [("i think i lost my mind", 9500), ("thanks for watching", 9300), ("this is the life that i chose", 9700),
         ("don't play it off", 9400), ("i love you", 9600), ("welcome to the ground", 9500)]


def test_the_voice_profile_learns_the_owners_speech_not_the_songs(monkeypatch):
    """Every capture went into the profile before the wake-word gate, so its 'voice' samples
    were mostly song lyrics the mic transcribed and dropped. Only what the gate takes as the owner's
    (the wake word, a command it sends on) is learnt now."""
    stt = _scripted_listener(monkeypatch, _SONG + [("computer", 2100), ("what time is it", 1900)])
    stt._listen_loop()
    prof = stt._voice_profile
    assert prof["count"] == 2, f"learnt from {prof['count']} captures, the songs among them"
    assert prof["energy_mean"] < 3000


def test_the_voice_profile_does_not_learn_while_the_music_or_the_room_is_louder():
    for kw in ({"media_playing": True}, {"threshold": 11453.0}):
        mp = pytest.MonkeyPatch()
        try:
            stt = _scripted_listener(mp, [("computer", 9800), ("what time is it", 9900)], **kw)
            stt._listen_loop()
            assert stt._voice_profile["count"] == 0, kw
        finally:
            mp.undo()

