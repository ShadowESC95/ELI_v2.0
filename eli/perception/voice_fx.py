"""Character-voice effects layer.

A "character voice" (HAL, TARS, Rick, GLaDOS, JARVIS, or a user's own) is a base
Piper voice plus a DSP effect chain applied to the synthesized WAV via ffmpeg —
so it needs no extra ML model, just ffmpeg (already required for media/TTS).

A preset is: {base, pitch (semitones), speed (tempo x), filters (raw ffmpeg -af),
desc}. Presets live in ``config/voices/characters.json`` and are seeded with the
built-ins below on first use; users add/edit their own (see save_preset).

tts_router resolves a voice named ``char:<name>`` through here.
"""
from __future__ import annotations

import io
import json
import logging
import os
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)

CHAR_PREFIX = "char:"

# Built-in character presets. `filters` is a raw ffmpeg -af chain; pitch is in
# semitones (±), speed is a tempo multiplier. Base voices are from the Piper catalog.
_BUILTIN: Dict[str, Dict[str, Any]] = {
    "hal": {
        "base": "en_US-lessac-medium", "pitch": -1.0, "speed": 0.93,
        "filters": "aecho=0.8:0.88:55:0.28,lowpass=f=3200,acompressor=threshold=-18dB:ratio=3",
        "desc": "HAL 9000 — calm, smooth, quietly menacing",
    },
    "tars": {
        "base": "en_US-joe-medium", "pitch": -2.0, "speed": 0.98,
        "filters": "tremolo=f=55:d=0.35,aphaser=type=t:speed=0.5,highpass=f=120,acompressor=threshold=-16dB:ratio=4",
        "desc": "TARS — deadpan robotic, metallic buzz",
    },
    "rick": {
        "base": "en_US-ryan-high", "pitch": 1.0, "speed": 1.03,
        "filters": "vibrato=f=6.5:d=0.35,tremolo=f=8:d=0.2,acompressor=threshold=-12dB:ratio=6,treble=g=4",
        "desc": "Rick — erratic, wobbly, a little fried",
    },
    "glados": {
        "base": "en_US-amy-medium", "pitch": -1.0, "speed": 0.97,
        "filters": "aphaser=type=t:speed=0.3,flanger=depth=4:speed=0.2,lowpass=f=3500,highpass=f=180",
        "desc": "GLaDOS — flat, synthetic, metallic",
    },
    "jarvis": {
        "base": "en_GB-alan-medium", "pitch": 0.0, "speed": 0.98,
        "filters": "treble=g=3,aecho=0.9:0.9:40:0.15,highpass=f=90",
        "desc": "JARVIS — refined British, subtle sheen",
    },
}


def _has_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def _presets_path() -> Path:
    try:
        from eli.core.paths import config_dir
        base = Path(config_dir())
    except Exception:
        base = Path("config")
    return base / "voices" / "characters.json"


def _load_all() -> Dict[str, Dict[str, Any]]:
    """Built-ins merged with (and overridable by) the user's characters.json."""
    presets = {k: dict(v) for k, v in _BUILTIN.items()}
    p = _presets_path()
    try:
        if p.is_file():
            user = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(user, dict):
                for k, v in user.items():
                    if isinstance(v, dict):
                        presets[str(k).lower()] = v
    except Exception:
        log.debug("voice_fx: reading %s failed", p, exc_info=True)
    return presets


def list_characters() -> "list[Dict[str, Any]]":
    out = []
    user = set()
    p = _presets_path()
    try:
        if p.is_file():
            user = set(k.lower() for k in json.loads(p.read_text(encoding="utf-8")))
    except Exception:
        pass
    for name, spec in _load_all().items():
        out.append({"name": name, "id": CHAR_PREFIX + name,
                    "builtin": name in _BUILTIN and name not in user,
                    "base": spec.get("base"), "desc": spec.get("desc", "")})
    return out


def get_preset(name: str) -> Optional[Dict[str, Any]]:
    return _load_all().get(str(name or "").lower().replace(CHAR_PREFIX, "", 1))


def save_preset(name: str, spec: Dict[str, Any]) -> Dict[str, Any]:
    """Create/overwrite a user character preset. Merges onto the built-in if one exists,
    so a user can tweak just pitch/speed/filters of e.g. 'hal'."""
    key = str(name or "").lower().replace(CHAR_PREFIX, "", 1).strip()
    if not key:
        return {"ok": False, "error": "empty name"}
    base = dict(_BUILTIN.get(key, {}))
    base.update({k: v for k, v in (spec or {}).items() if v is not None})
    if not base.get("base"):
        base["base"] = "en_US-amy-medium"
    p = _presets_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    try:
        if p.is_file():
            existing = json.loads(p.read_text(encoding="utf-8")) or {}
    except Exception:
        existing = {}
    existing[key] = base
    p.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, "name": key, "id": CHAR_PREFIX + key, "spec": base}


def delete_preset(name: str) -> Dict[str, Any]:
    key = str(name or "").lower().replace(CHAR_PREFIX, "", 1).strip()
    p = _presets_path()
    try:
        existing = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    except Exception:
        existing = {}
    if key in existing:
        existing.pop(key, None)
        p.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
        return {"ok": True, "name": key, "reverted_to_builtin": key in _BUILTIN}
    return {"ok": False, "error": f"no user preset '{key}'"}


def _wav_sample_rate(wav_bytes: bytes) -> int:
    try:
        with wave.open(io.BytesIO(wav_bytes)) as w:
            return w.getframerate() or 22050
    except Exception:
        return 22050


def _build_filter_chain(spec: Dict[str, Any], sample_rate: int) -> str:
    parts: list[str] = []
    # Pitch shift in semitones without changing duration: resample up/down, then
    # correct tempo back. atempo only accepts 0.5–2.0, which covers ±12 semitones.
    try:
        semitones = float(spec.get("pitch") or 0.0)
    except (TypeError, ValueError):
        semitones = 0.0
    if abs(semitones) > 0.01:
        factor = 2.0 ** (semitones / 12.0)
        factor = max(0.5, min(2.0, factor))
        parts.append(f"asetrate={int(sample_rate * factor)}")
        parts.append(f"aresample={sample_rate}")
        parts.append(f"atempo={1.0/factor:.4f}")
    try:
        speed = float(spec.get("speed") or 1.0)
    except (TypeError, ValueError):
        speed = 1.0
    if abs(speed - 1.0) > 0.01:
        parts.append(f"atempo={max(0.5, min(2.0, speed)):.4f}")
    custom = str(spec.get("filters") or "").strip()
    if custom:
        parts.append(custom)
    return ",".join(parts)


def apply_fx(wav_bytes: bytes, spec: Dict[str, Any]) -> Optional[bytes]:
    """Run a character's ffmpeg effect chain over a synthesized WAV; return processed
    WAV bytes (or the original if ffmpeg/chain is unavailable — always fail open)."""
    if not wav_bytes or not _has_ffmpeg():
        return wav_bytes
    chain = _build_filter_chain(spec, _wav_sample_rate(wav_bytes))
    if not chain:
        return wav_bytes
    outpath = ""
    try:
        # Output to a seekable temp file (NOT pipe:1) so ffmpeg backfills correct RIFF/
        # data sizes — a piped WAV has placeholder sizes that break strict decoders.
        fd, outpath = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        proc = subprocess.run(
            ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "wav", "-i", "pipe:0", "-af", chain, outpath],
            input=wav_bytes, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
        )
        if proc.returncode == 0 and os.path.getsize(outpath) > 0:
            return Path(outpath).read_bytes()
        log.debug("voice_fx: ffmpeg rc=%s err=%s", proc.returncode, proc.stderr[:200])
    except Exception:
        log.debug("voice_fx: ffmpeg failed", exc_info=True)
    finally:
        if outpath:
            try:
                os.unlink(outpath)
            except OSError:
                pass
    return wav_bytes  # fail open — better a clean base voice than silence
