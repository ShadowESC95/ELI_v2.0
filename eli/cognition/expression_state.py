"""Live avatar/expression state — the thin bridge that lets ELI's face react in
real time to what he's *doing*, not just what he's feeling.

Three cheap process-local flags the face widget polls each frame:
  • speaking  — set while TTS audio is playing (drives lip-sync mouth movement),
  • thinking  — set while the model is generating a reply (a focused/"working" look),
  • amplitude — optional 0..1 loudness of the current speech frame (for amplitude-
                driven lip-sync; falls back to a natural oscillation when absent).

Deliberately dependency-free and side-effect-free so tts_router (playback) and the
kernel (inference) can set it without importing any GUI code, and the GUI can read
it without importing the runtime. Priority the face applies: thinking > speaking >
expressed tone.
"""
from __future__ import annotations

import threading
import time

_lock = threading.Lock()
_speaking_until = 0.0      # speaking flag auto-expires (a missed clear can't freeze the mouth)
_thinking = False
_amplitude = 0.0


def set_speaking(on: bool, *, ttl: float = 30.0) -> None:
    """Mark TTS playback active/inactive. ``ttl`` caps how long a stuck 'on' lasts."""
    global _speaking_until
    with _lock:
        _speaking_until = (time.time() + ttl) if on else 0.0
        if not on:
            globals()["_amplitude"] = 0.0


def is_speaking() -> bool:
    with _lock:
        return time.time() < _speaking_until


def set_amplitude(level: float) -> None:
    """0..1 loudness of the current speech frame (optional, for real lip-sync)."""
    global _amplitude
    with _lock:
        try:
            _amplitude = max(0.0, min(1.0, float(level)))
        except (TypeError, ValueError):
            _amplitude = 0.0


def amplitude() -> float:
    with _lock:
        return _amplitude


def set_thinking(on: bool) -> None:
    global _thinking
    with _lock:
        _thinking = bool(on)


def is_thinking() -> bool:
    with _lock:
        return _thinking
