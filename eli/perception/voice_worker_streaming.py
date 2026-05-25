#!/usr/bin/env python3
"""Stream-aware voice worker for ELI."""

from __future__ import annotations

import threading
from typing import Optional

from eli.perception.tts_router import speak_if_enabled

# === PHASE38_STT_TIMING_HARDENING ===
import os as _phase38_os

def _phase38_float_env(_name, _default):
    try:
        return float(_phase38_os.environ.get(_name, str(_default)))
    except Exception:
        return float(_default)

def _phase38_int_env(_name, _default):
    try:
        return int(float(_phase38_os.environ.get(_name, str(_default))))
    except Exception:
        return int(_default)

_PHASE38_STT_PAUSE_THRESHOLD = _phase38_float_env("ELI_STT_PAUSE_THRESHOLD", 1.35)
_PHASE38_STT_NON_SPEAKING_DURATION = _phase38_float_env("ELI_STT_NON_SPEAKING_DURATION", 0.75)
_PHASE38_STT_PHRASE_TIME_LIMIT = _phase38_int_env("ELI_STT_PHRASE_TIME_LIMIT", 10)
_PHASE38_STT_LISTEN_TIMEOUT = _phase38_int_env("ELI_STT_LISTEN_TIMEOUT", 7)
_PHASE38_STT_WAKE_WINDOW = _phase38_float_env("ELI_STT_WAKE_WINDOW", 9.0)
# === END PHASE38_STT_TIMING_HARDENING ===



class VoiceWorker:
    def __init__(self):
        self._lock = threading.Lock()
        self._active = False
        self._current_thread: Optional[threading.Thread] = None

    def speak(self, text: str):
        with self._lock:
            self._active = True
            t = threading.Thread(target=self._run, args=(text,), daemon=True)
            self._current_thread = t
        t.start()

    def _run(self, text: str):
        # Read the flag once while holding the lock. If interrupt() fires
        # after this point the long speak_if_enabled call will still run —
        # that's the inherent trade-off of non-blocking TTS dispatch. The
        # flag is reset to False when we finish so the next speak() is clean.
        with self._lock:
            active = self._active
        if active:
            speak_if_enabled(text, enabled=True)
        with self._lock:
            self._active = False

    def interrupt(self):
        with self._lock:
            self._active = False
