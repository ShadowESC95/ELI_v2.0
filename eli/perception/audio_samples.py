"""Audio as samples: read a sound file into one channel at the rate a consumer needs.

One place for what three modules did on their own (the wake word and the voice profile each had
the same resampler), and what two more needed:

  * speech recognition: faster-whisper decodes a file with PyAV, whose argument list changed under
    it (PyAV 18 dropped `metadata_errors`, which faster-whisper 1.2.1 still passes), and every
    transcription in the packaged app failed. Handed samples at 16 kHz it never opens a file.
  * playback: a USB headset's ALSA device took only its own rate, and opening it at the voice's
    22,050 Hz failed ("Invalid sample rate").
"""
from __future__ import annotations

from typing import Optional

import numpy as np

# The rate Whisper and the wake-word model are trained at.
SPEECH_RATE = 16000


def resample(x: np.ndarray, sr_in: int, sr_out: int = SPEECH_RATE) -> np.ndarray:
    """Mono float32 samples at sr_in, at sr_out instead (linear interpolation)."""
    x = np.asarray(x, dtype=np.float32).reshape(-1)
    if int(sr_in) == int(sr_out) or x.size == 0:
        return x
    n_out = int(round(x.size * int(sr_out) / int(sr_in)))
    if n_out <= 1:
        return np.zeros(0, dtype=np.float32)
    return np.interp(np.linspace(0, x.size, n_out, endpoint=False),
                     np.arange(x.size, dtype=np.float32), x).astype(np.float32)


def _read_pcm_wav(path):
    """(samples, rate, channels) of an integer PCM WAV, read with the standard library: what ELI
    records and what Piper writes. Raises for anything else."""
    import wave
    with wave.open(str(path), "rb") as w:
        width, rate, channels = w.getsampwidth(), w.getframerate(), w.getnchannels()
        raw = w.readframes(w.getnframes())
    if width == 1:
        x = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif width == 2:
        x = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif width == 3:
        b = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        v = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
        x = (np.where(v >= 1 << 23, v - (1 << 24), v)).astype(np.float32) / float(1 << 23)
    elif width == 4:
        x = np.frombuffer(raw, dtype="<i4").astype(np.float32) / float(1 << 31)
    else:
        raise ValueError(f"unsupported sample width {width}")
    return x, int(rate), int(channels)


def read_mono(path, sr_out: Optional[int] = None):
    """(samples, rate): the file's channels averaged into one, as float32, at sr_out when given.
    A PCM WAV is read with the standard library; other formats with soundfile."""
    try:
        data, sr, channels = _read_pcm_wav(path)
        if channels > 1:
            data = data[: data.size - data.size % channels].reshape(-1, channels).mean(axis=1)
    except Exception:
        import soundfile as sf
        data, sr = sf.read(str(path), dtype="float32", always_2d=False)
        if getattr(data, "ndim", 1) > 1:
            data = data.mean(axis=1)
    data = np.asarray(data, dtype=np.float32).reshape(-1)
    if sr_out and int(sr_out) != int(sr):
        return resample(data, int(sr), int(sr_out)), int(sr_out)
    return data, int(sr)


__all__ = ["SPEECH_RATE", "resample", "read_mono"]
