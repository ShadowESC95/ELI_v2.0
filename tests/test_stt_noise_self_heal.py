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
