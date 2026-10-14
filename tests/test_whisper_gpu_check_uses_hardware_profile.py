"""_gpu_total_mb() used to shell out to nvidia-smi directly with no fallback
-- the same fragile pattern fixed elsewhere in hardware_profile.py. A broken
driver (NVML version mismatch, a transient hiccup) read as "no GPU", silently
forcing faster-whisper onto CPU even on a machine with a perfectly good big
NVIDIA card. It now routes through detect_hardware(), which already has the
kernel-level fallbacks for exactly that failure.

Deliberately NVIDIA-only, not a bug: the caller sets device="cuda" for
ctranslate2, which has no ROCm/Vulkan backend -- AMD/Intel/Apple correctly
stay on CPU here regardless of VRAM.
"""
import eli.perception.local_whisper_stt as stt


def _reset_cache(monkeypatch):
    monkeypatch.setattr(stt, "_GPU_TOTAL_MB", None)


def _fake_hw(**kw):
    base = {"has_gpu": False, "gpu_vendor": "", "total_vram_mb": 0}
    base.update(kw)
    return type("HW", (), base)()


def test_nvidia_vram_is_reported(monkeypatch):
    _reset_cache(monkeypatch)
    monkeypatch.setattr(
        "eli.core.hardware_profile.detect_hardware",
        lambda: _fake_hw(has_gpu=True, gpu_vendor="nvidia", total_vram_mb=16384),
    )
    assert stt._gpu_total_mb() == 16384


def test_amd_reports_zero_not_its_own_vram(monkeypatch):
    """ctranslate2 has no ROCm backend -- an AMD card's VRAM must not make
    the caller think a CUDA device is usable."""
    _reset_cache(monkeypatch)
    monkeypatch.setattr(
        "eli.core.hardware_profile.detect_hardware",
        lambda: _fake_hw(has_gpu=True, gpu_vendor="amd", total_vram_mb=24576),
    )
    assert stt._gpu_total_mb() == 0


def test_broken_driver_still_reports_real_vram_via_fallback(monkeypatch):
    """The field case: nvidia-smi itself is broken, but detect_hardware()'s
    own fallback (model-name lookup) still knows the real card."""
    _reset_cache(monkeypatch)
    monkeypatch.setattr(
        "eli.core.hardware_profile.detect_hardware",
        lambda: _fake_hw(has_gpu=True, gpu_vendor="nvidia", total_vram_mb=8192),
    )
    assert stt._gpu_total_mb() == 8192


def test_no_gpu_reports_zero(monkeypatch):
    _reset_cache(monkeypatch)
    monkeypatch.setattr("eli.core.hardware_profile.detect_hardware", lambda: _fake_hw())
    assert stt._gpu_total_mb() == 0


def test_result_is_cached(monkeypatch):
    _reset_cache(monkeypatch)
    calls = {"n": 0}
    def _detect():
        calls["n"] += 1
        return _fake_hw(has_gpu=True, gpu_vendor="nvidia", total_vram_mb=16384)
    monkeypatch.setattr("eli.core.hardware_profile.detect_hardware", _detect)
    assert stt._gpu_total_mb() == 16384
    assert stt._gpu_total_mb() == 16384
    assert calls["n"] == 1


# ── what faster-whisper is given ─────────────────────────────────────────────

def test_a_recording_reaches_faster_whisper_as_16_khz_samples_not_a_file(tmp_path):
    """faster-whisper opens a file with PyAV, and PyAV 18 refused the argument faster-whisper
    1.2.1 passes: every transcription in the 2.5.11 packaged app failed. Handed samples, it
    opens nothing."""
    import wave
    import numpy as np
    path = tmp_path / "said.wav"
    with wave.open(str(path), "wb") as f:
        f.setnchannels(2)
        f.setsampwidth(2)
        f.setframerate(44100)
        f.writeframes(np.full(2 * 44100, 1000, dtype="<i2").tobytes())
    seen = {}

    class _Model:
        def transcribe(self, audio, **kw):
            seen["audio"] = audio
            return iter([type("S", (), {"text": " Open Spotify."})()]), None

    assert stt._do_transcribe(_Model(), str(path), "en") == "open spotify."
    audio = seen["audio"]
    assert isinstance(audio, np.ndarray) and audio.dtype == np.float32 and abs(len(audio) - 16000) <= 2
    assert abs(float(audio.mean()) - 1000 / 32768) < 1e-3, "the two channels are averaged, not run end to end"


def test_a_file_that_cannot_be_read_here_is_left_to_faster_whisper(tmp_path):
    odd = tmp_path / "talk.m4a"
    odd.write_bytes(b"not a wav")
    assert stt._audio_for_whisper(odd) == str(odd)
