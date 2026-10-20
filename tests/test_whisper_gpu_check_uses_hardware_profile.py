"""Whisper's GPU is read from the one per-card telemetry, never its own nvidia-smi call.

It used to shell out to nvidia-smi directly with no fallback: a broken driver (NVML version
mismatch, a transient hiccup) read as "no GPU", forcing faster-whisper onto the CPU on a machine with
a perfectly good NVIDIA card; then it read detect_hardware()'s total, which on a multi-GPU machine is
every card's memory summed. It now takes CUDA device 0 from get_live_gpu_telemetry, which has the
fallbacks and lists each card.

NVIDIA only on purpose: ctranslate2 has no ROCm, Vulkan or Metal backend, so AMD, Intel, Apple and
Qualcomm machines keep whisper on the CPU whatever their memory.
"""
import eli.perception.local_whisper_stt as stt


def _cards(monkeypatch, *cards):
    monkeypatch.setattr("eli.core.hardware_profile.get_live_gpu_telemetry",
                        lambda: {"ok": bool(cards), "devices": [dict(c) for c in cards]})


def test_the_first_nvidia_card_is_whisper_s(monkeypatch):
    _cards(monkeypatch, {"index": 0, "name": "AMD Radeon RX 7900 XTX", "vendor": "amd", "total_mb": 24576},
           {"index": 1, "name": "RTX A", "vendor": "nvidia", "total_mb": 8192},
           {"index": 2, "name": "RTX B", "vendor": "nvidia", "total_mb": 16384})
    assert stt._whisper_card()["name"] == "RTX A"


def test_other_makers_cards_are_not_offered_to_ctranslate2(monkeypatch):
    _cards(monkeypatch, {"index": 0, "name": "AMD Radeon RX 7900 XTX", "vendor": "amd", "total_mb": 24576})
    assert stt._whisper_card() is None


def test_no_gpu_means_no_card(monkeypatch):
    _cards(monkeypatch)
    assert stt._whisper_card() is None


def test_a_cuda_card_found_only_by_llama_cpp_is_named_nvidia():
    """llama.cpp's device list used to give every card an empty maker."""
    from eli.core.hardware_profile import _vendor_of
    assert _vendor_of("Some Card", "CUDA0") == "nvidia"
    assert _vendor_of("AMD Radeon RX 7900 XTX", "Vulkan0") == "amd"
    assert _vendor_of("Apple M3 Max", "MTL0") == "apple"
    assert _vendor_of("Unknown", "Vulkan0") == ""


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
