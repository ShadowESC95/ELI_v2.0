"""Voice cloning backend (Coqui XTTS-v2).

A "cloned voice" reproduces a target voice from a short reference sample (~6-20s of
clean speech) with zero training — powered by Coqui XTTS-v2. Unlike Piper/character
voices (always available), this needs the optional heavy ``TTS`` package + a ~1.8GB
model that downloads on first use, so everything here **degrades gracefully**:

- Registering a clone (``add_clone``) only stores a reference clip — works offline,
  no ``TTS`` needed. Users can build their voice library any time.
- Synthesis (``synthesize_wav``) needs ``TTS`` installed; if absent it returns None
  and the caller falls back to a normal voice, with a clear one-line reason.

tts_router resolves a voice named ``clone:<name>`` through here.
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)

CLONE_PREFIX = "clone:"
_XTTS_MODEL = "tts_models/multilingual/multi-dataset/xtts_v2"
_TTS = None  # lazy singleton


# ── Registry (offline-safe) ──────────────────────────────────────────────────────
def _registry_path() -> Path:
    try:
        from eli.core.paths import config_dir
        base = Path(config_dir())
    except Exception:
        base = Path("config")
    return base / "voices" / "clones.json"


def _refs_dir() -> Path:
    try:
        from eli.core.paths import models_dir
        base = Path(models_dir())
    except Exception:
        base = Path("models")
    d = base / "voice_profiles"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load_registry() -> Dict[str, Dict[str, Any]]:
    p = _registry_path()
    try:
        if p.is_file():
            obj = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(obj, dict):
                return obj
    except Exception:
        log.debug("tts_xtts: registry read failed", exc_info=True)
    return {}


def _save_registry(reg: Dict[str, Dict[str, Any]]) -> None:
    p = _registry_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(reg, indent=2) + "\n", encoding="utf-8")


def _to_reference_wav(audio_path: str, dest: Path) -> bool:
    """Normalise any input audio to a mono 22.05kHz WAV reference via ffmpeg."""
    if not shutil.which("ffmpeg"):
        # No ffmpeg: only accept an existing .wav as-is.
        if str(audio_path).lower().endswith(".wav") and Path(audio_path).is_file():
            shutil.copy2(audio_path, dest)
            return True
        return False
    try:
        proc = subprocess.run(
            ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
             "-i", str(audio_path), "-ac", "1", "-ar", "22050", str(dest)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60,
        )
        return proc.returncode == 0 and dest.is_file() and dest.stat().st_size > 0
    except Exception:
        log.debug("tts_xtts: reference conversion failed", exc_info=True)
        return False


def add_clone(name: str, audio_path: str, language: str = "en",
              desc: str = "") -> Dict[str, Any]:
    """Register a cloned voice from a reference audio clip (offline; no TTS needed)."""
    key = str(name or "").lower().replace(CLONE_PREFIX, "", 1).strip().replace(" ", "_")
    if not key:
        return {"ok": False, "error": "empty name"}
    if not Path(audio_path).is_file():
        return {"ok": False, "error": f"audio not found: {audio_path}"}
    ref = _refs_dir() / f"{key}.wav"
    if not _to_reference_wav(audio_path, ref):
        return {"ok": False, "error": "could not read/convert the reference audio (need ffmpeg or a .wav)"}
    reg = _load_registry()
    reg[key] = {"ref_wav": str(ref), "language": language or "en", "desc": desc or f"Cloned voice: {key}"}
    _save_registry(reg)
    return {"ok": True, "name": key, "id": CLONE_PREFIX + key, "ref_wav": str(ref),
            "synth_ready": xtts_available()}


def delete_clone(name: str) -> Dict[str, Any]:
    key = str(name or "").lower().replace(CLONE_PREFIX, "", 1).strip()
    reg = _load_registry()
    if key in reg:
        try:
            Path(reg[key].get("ref_wav", "")).unlink(missing_ok=True)
        except Exception:
            pass
        reg.pop(key, None)
        _save_registry(reg)
        return {"ok": True, "name": key}
    return {"ok": False, "error": f"no clone '{key}'"}


def get_clone(name: str) -> Optional[Dict[str, Any]]:
    return _load_registry().get(str(name or "").lower().replace(CLONE_PREFIX, "", 1))


def list_clones() -> "list[Dict[str, Any]]":
    return [{"name": k, "id": CLONE_PREFIX + k, "language": v.get("language", "en"),
             "desc": v.get("desc", ""), "ref_present": Path(v.get("ref_wav", "")).is_file()}
            for k, v in _load_registry().items()]


# ── Synthesis (needs the optional TTS package) ──────────────────────────────────
def xtts_available() -> bool:
    try:
        import TTS  # noqa: F401
        return True
    except Exception:
        return False


def _get_model():
    global _TTS
    if _TTS is not None:
        return _TTS
    from TTS.api import TTS as _TTSApi
    device = "cpu"
    try:
        import torch
        if torch.cuda.is_available():
            device = "cuda"
    except Exception:
        pass
    log.info("tts_xtts: loading XTTS-v2 on %s (first run downloads ~1.8GB)…", device)
    _TTS = _TTSApi(_XTTS_MODEL).to(device)
    return _TTS


def synthesize_wav(text: str, clone_name: str) -> Optional[bytes]:
    """Clone-synthesize `text` in the named voice; None if unavailable (caller falls back)."""
    spec = get_clone(clone_name)
    if not spec:
        log.debug("tts_xtts: no clone '%s'", clone_name)
        return None
    ref = spec.get("ref_wav")
    if not ref or not Path(ref).is_file():
        log.debug("tts_xtts: missing reference for '%s'", clone_name)
        return None
    if not xtts_available():
        log.info("tts_xtts: %s needs the voice-clone extra — `pip install \"eli-v2.0[clone]\"`",
                 str(clone_name))
        return None
    outpath = ""
    try:
        model = _get_model()
        fd, outpath = tempfile.mkstemp(suffix=".wav")
        Path(outpath).unlink(missing_ok=True)
        import os as _os
        _os.close(fd)
        model.tts_to_file(text=str(text), speaker_wav=ref,
                          language=spec.get("language", "en"), file_path=outpath)
        if Path(outpath).is_file() and Path(outpath).stat().st_size > 0:
            return Path(outpath).read_bytes()
    except Exception:
        log.debug("tts_xtts: synthesis failed", exc_info=True)
    finally:
        if outpath:
            try:
                Path(outpath).unlink(missing_ok=True)
            except OSError:
                pass
    return None
