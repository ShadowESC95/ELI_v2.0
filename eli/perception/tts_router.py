#!/usr/bin/env python3
"""
tts_router.py — TTS router for ELI.

Priority:
1. Piper (Python API, no binary required) — uses ONNX voices
2. Piper CLI binary (fallback if Python API fails)
3. pyttsx3
4. espeak-ng / espeak
"""
from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import threading
import tempfile
from pathlib import Path
from typing import Optional

from eli.utils.platform_compat import LINUX, play_sound


from eli.utils.log import get_logger
log = get_logger(__name__)

_LOCK = threading.Lock()
_ENGINE = None  # lazy pyttsx3 engine
_NO_BACKEND_CONFIRMED = False

# === PHASE13B_V2_PACKAGED_TTS_PIPER_SEARCH ===
# Packaged ELI builds place Piper assets under:
#   <project_root>/tts_piper/piper
# Keep this as a search location; do not duplicate or move assets.
_PROJECT_ROOT_TTS = Path(
    os.environ.get("ELI_PROJECT_ROOT")
    or Path(__file__).resolve().parents[2]
).expanduser()

_PACKAGED_TTS_PIPER_ROOT = _PROJECT_ROOT_TTS / "tts_piper" / "piper"
_PACKAGED_TTS_PIPER_PARENT = _PROJECT_ROOT_TTS / "tts_piper"


def _packaged_piper_voice_dirs() -> list[Path]:
    candidates = [
        _PACKAGED_TTS_PIPER_ROOT,
        _PACKAGED_TTS_PIPER_ROOT / "voices",
        _PACKAGED_TTS_PIPER_PARENT,
        _PACKAGED_TTS_PIPER_PARENT / "voices",
    ]
    return candidates


def _packaged_piper_binary_candidates() -> list[Path]:
    return [
        _PACKAGED_TTS_PIPER_ROOT / "piper",
        _PACKAGED_TTS_PIPER_PARENT / "piper",
        _PACKAGED_TTS_PIPER_PARENT / "bin" / "piper",
    ]


# ── Voice discovery ────────────────────────────────────────────────────────

_VOICE_SEARCH_DIRS = [
    Path(__file__).resolve().parents[2] / "models" / "tts" / "piper",
    Path(__file__).resolve().parents[1] / "voices",
    Path(__file__).resolve().parents[2] / "voices",
    Path(os.environ.get("ELI_PROJECT_ROOT", ".")) / "models" / "tts" / "piper",
    Path(os.environ.get("ELI_PROJECT_ROOT", ".")) / "voices",
    Path.home() / ".local" / "share" / "piper",
    *_packaged_piper_voice_dirs(),
]

# Default voice (can be overridden via setting or env)
_DEFAULT_VOICE = "en_US-ryan-high"


def _voice_dir() -> Path:
    """Return the project's canonical TTS voice directory."""
    try:
        from eli.core.paths import models_dir

        return models_dir() / "tts" / "piper"
    except Exception:
        return Path(__file__).resolve().parents[2] / "models" / "tts" / "piper"


def _voice_search_dirs() -> list[Path]:
    dirs = [_voice_dir(), *_VOICE_SEARCH_DIRS]
    seen: set[str] = set()
    unique: list[Path] = []
    for d in dirs:
        key = str(d.expanduser())
        if key not in seen:
            seen.add(key)
            unique.append(d.expanduser())
    return unique


def _has_piper_config(model: Path) -> bool:
    return any(
        p.exists()
        for p in (
            Path(str(model) + ".json"),
            model.with_suffix(".onnx.json"),
            model.with_suffix(".json"),
            model.parent / "config.json",
        )
    )


def _play_wav_bytes(wav_bytes: bytes) -> bool:
    """Play WAV bytes on any supported OS without requiring Linux audio CLIs."""
    if not wav_bytes:
        return False
    try:
        import sounddevice as sd  # type: ignore
        import soundfile as sf  # type: ignore

        data, sample_rate = sf.read(io.BytesIO(wav_bytes), dtype="float32")
        sd.play(data, int(sample_rate))
        sd.wait()
        return True
    except Exception:
        pass

    suffix = ".wav"
    try:
        with tempfile.NamedTemporaryFile(prefix="eli_tts_", suffix=suffix, delete=False) as f:
            f.write(wav_bytes)
            path = f.name
        return play_sound(path)
    except Exception:
        return False


def _raw_pcm_to_wav(raw_bytes: bytes, sample_rate: int = 22050) -> bytes:
    """Wrap 16-bit mono PCM bytes from Piper CLI in a WAV container."""
    if not raw_bytes:
        return b""
    import wave

    wav_buf = io.BytesIO()
    with wave.open(wav_buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(raw_bytes)
    return wav_buf.getvalue()


def list_voices() -> list[str]:
    """Return runnable Piper voices (without .onnx extension)."""
    voices: list[str] = []
    seen: set[str] = set()
    for d in _voice_search_dirs():
        try:
            for f in sorted(d.glob("*.onnx")):
                if not _has_piper_config(f):
                    continue
                name = f.stem  # e.g. en_US-lessac-high
                if name not in seen:
                    seen.add(name)
                    voices.append(name)
        except Exception:
            pass
    return voices


def find_voice_model(voice_name: str) -> Optional[Path]:
    """Locate the .onnx file for a named voice."""
    # Exact override via env
    env_model = os.environ.get("ELI_PIPER_MODEL", "").strip()
    if env_model:
        p = Path(env_model).expanduser()
        if p.exists():
            return p

    # Direct path check
    vn = voice_name or _DEFAULT_VOICE
    for d in _voice_search_dirs():
        candidate = d / f"{vn}.onnx"
        try:
            if candidate.exists() and _has_piper_config(candidate):
                return candidate.resolve()
        except Exception:
            pass

    # Fallback: any runnable .onnx in search dirs
    for d in _voice_search_dirs():
        try:
            hits = [p for p in sorted(d.glob("*.onnx")) if _has_piper_config(p)]
            if hits:
                return hits[0].resolve()
        except Exception:
            pass
    return None


def get_active_voice() -> str:
    """Return the currently configured voice name."""
    env = os.environ.get("ELI_PIPER_VOICE", "").strip()
    if env:
        return env
    try:
        from eli.core.runtime_settings import load_settings
        s = load_settings()
        v = s.get("tts_voice", "").strip()
        if v:
            return v
    except Exception:
        pass
    return _DEFAULT_VOICE


def set_active_voice(voice_name: str) -> None:
    """Persist the selected voice to settings."""
    os.environ["ELI_PIPER_VOICE"] = voice_name
    try:
        from eli.core.runtime_settings import save_settings
        save_settings({"tts_voice": voice_name})
    except Exception:
        pass
    # (Piper Python API voice cache was removed; nothing to clear here)


# ── Text cleanup ───────────────────────────────────────────────────────────

def _clean_text(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    text = re.sub(r"[*_`#>|]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:800]


def _find_piper_bin() -> Optional[str]:
    """Locate the piper CLI binary. Used by available_backends() reporting."""
    env_bin = os.environ.get("ELI_PIPER_BINARY", "").strip().strip('"') or os.environ.get("ELI_PIPER_BIN", "").strip()
    if env_bin:
        p = Path(env_bin).expanduser()
        if p.exists():
            return str(p)
        if shutil.which(env_bin):
            return env_bin
    for packaged in _packaged_piper_binary_candidates():
        try:
            if packaged.exists() and packaged.is_file():
                return str(packaged.resolve())
        except Exception:
            pass

    for guess in (
        "piper",
        str(Path.cwd() / ".venv" / "bin" / "piper"),
        str(Path.home() / ".local" / "bin" / "piper"),
        "/usr/local/bin/piper",
        "/usr/bin/piper",
    ):
        if shutil.which(guess) or Path(guess).exists():
            return guess
    return None


def available_backends() -> dict:
    installed = list_voices()
    active = get_active_voice()
    active_model = find_voice_model(active)
    return {
        "piper_python": True,
        "piper_bin": _find_piper_bin(),
        "piper_voices": installed,
        "active_voice": active,
        "active_model": str(active_model) if active_model else None,
        "pyttsx3": True,
        "espeak_ng": shutil.which("espeak-ng") is not None,
        "espeak": shutil.which("espeak") is not None,
    }


# ── Piper-only TTS path ────────────────────────────────────────────────────
# Final authoritative TTS path:
# - respects GUI/config voice via get_active_voice()
# - uses known-working Piper CLI WAV path
# - does NOT use Piper Python API because this install lacks synthesize_stream_raw()
# - does NOT fall back to pyttsx3/espeak robot voices

def _tts_chunks(text, max_chars=None):
    import os as _os
    import re as _re

    if max_chars is None:
        if _os.environ.get("ELI_TTS_CHUNK_CHARS"):
            max_chars = _os.environ.get("ELI_TTS_CHUNK_CHARS", "360")
        else:
            try:
                from eli.runtime.runtime_policy import tts_chunk_chars as _eli_tts_chunk_chars
                max_chars = _eli_tts_chunk_chars(360)
            except Exception:
                max_chars = "360"
    max_chars = int(max_chars)
    text = str(text or "").strip()
    if not text:
        return []

    text = _re.sub(r'^\s*(?:As\s+ELI|ELI)\s*:\s*', '', text, flags=_re.I).strip()

    sentences = _re.split(r'(?<=[.!?])\s+', text)
    chunks = []
    cur = ""

    for sent in sentences:
        sent = sent.strip()
        if not sent:
            continue

        if len(sent) > max_chars:
            words = sent.split()
            tmp = ""
            for w in words:
                if len(tmp) + len(w) + 1 > max_chars and tmp:
                    if cur:
                        chunks.append(cur)
                        cur = ""
                    chunks.append(tmp)
                    tmp = w
                else:
                    tmp = (tmp + " " + w).strip()
            sent = tmp

        if len(cur) + len(sent) + 1 <= max_chars:
            cur = (cur + " " + sent).strip()
        else:
            if cur:
                chunks.append(cur)
            cur = sent

    if cur:
        chunks.append(cur)

    return chunks


def _find_piper_config(model_path):
    from pathlib import Path as _Path

    mp = _Path(model_path)
    candidates = [
        _Path(str(mp) + ".json"),
        mp.with_suffix(".onnx.json"),
        mp.with_suffix(".json"),
        mp.parent / "config.json",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None

# ── Piper CLI synthesise + play, with speaking-lock for STT echo guard ────
# Final authoritative TTS path: Piper CLI only, aplay first, blocking playback,
# explicit rc logging, and lock held through playback tail.

def _speak_piper_cli(text, voice_name=None):
    import os as _os
    import time as _time
    import shutil as _shutil
    import subprocess as _subprocess
    import tempfile as _tempfile
    from pathlib import Path as _Path

    active = voice_name or get_active_voice()
    model = find_voice_model(active)

    if not model:
        log.debug(f"[TTS_FINAL_PIPER_ONLY] no voice model for active={active}")
        return False

    _eli_packaged_cli_bins = [
        _Path(p) for p in _packaged_piper_binary_candidates()
    ]
    _eli_packaged_cli_bin = next(
        (str(p.resolve()) for p in _eli_packaged_cli_bins if p.exists() and p.is_file()),
        "",
    )

    piper_bin = (
        _os.environ.get("ELI_PIPER_BINARY", "").strip().strip('"')
        or _eli_packaged_cli_bin
        or _shutil.which("piper")
        or str(_Path.cwd() / ".venv" / "bin" / "piper")
    )

    if not (_Path(piper_bin).exists() or _shutil.which(piper_bin)):
        log.debug(f"[TTS_FINAL_PIPER_ONLY] missing piper binary: {piper_bin}")
        return False

    players = []
    for cand in ("aplay", "paplay"):
        found = _shutil.which(cand)
        if found:
            players.append(found)

    if not players:
        log.debug("[TTS_FINAL_PIPER_ONLY] missing aplay/paplay")
        return False

    cfg = _find_piper_config(model)
    lock_path = _Path(_os.environ.get("ELI_TTS_SPEAKING_LOCK", "/tmp/eli_tts_speaking.lock"))

    with _tempfile.NamedTemporaryFile(prefix="eli_piper_final_", suffix=".wav", delete=False) as tmp:
        wav = _Path(tmp.name)

    cmd = [piper_bin, "--model", str(model), "--output_file", str(wav)]
    if cfg:
        cmd.extend(["--config", str(cfg)])

    try:
        try:
            lock_path.write_text(str(_os.getpid()), encoding="utf-8")
        except Exception:
            pass

        proc = _subprocess.run(
            cmd,
            input=str(text or ""),
            text=True,
            stdout=_subprocess.PIPE,
            stderr=_subprocess.PIPE,
            timeout=45,
        )

        if proc.returncode != 0:
            log.debug(f"[TTS_FINAL_PIPER_ONLY] piper failed rc={proc.returncode}: {proc.stderr[-800:]}")
            return False

        if not wav.exists() or wav.stat().st_size < 1000:
            log.debug(f"[TTS_FINAL_PIPER_ONLY] wav missing/empty: {wav}")
            return False

        log.debug(
            f"[TTS_FINAL_PIPER_ONLY] voice={active} model={_Path(model).name} bytes={wav.stat().st_size}",
        )

        for player in players:
            player_name = _Path(player).name
            if player_name == "aplay":
                play_cmd = [player, "-q", str(wav)]
            else:
                play_cmd = [player, str(wav)]

            play_proc = _subprocess.run(
                play_cmd,
                stdout=_subprocess.PIPE,
                stderr=_subprocess.PIPE,
                text=True,
                check=False,
            )

            log.debug(
                f"[TTS_FINAL_PIPER_ONLY_PLAY] player={player_name} rc={play_proc.returncode}",
            )

            if play_proc.returncode == 0:
                _time.sleep(float(_os.environ.get("ELI_TTS_POST_PLAY_TAIL_SEC", "0.05")))
                return True

            if play_proc.stderr:
                log.debug(
                    f"[TTS_FINAL_PIPER_ONLY_PLAY] stderr={play_proc.stderr[-800:]}",
                )

        return False

    finally:
        try:
            wav.unlink(missing_ok=True)
        except Exception:
            pass
        try:
            lock_path.unlink(missing_ok=True)
        except Exception:
            pass


def _eli_tts_visible_text(text) -> str:
    """
    Final-only TTS surface.

    TTS must never read private reasoning scaffolds. Use the central visible
    output contract and return its result directly.
    """
    try:
        from eli.runtime.visible_output import visible_text as _eli_visible_text
        clean = _eli_visible_text(text)
    except Exception:
        clean = str(text or "").strip()

    return clean if clean else "..."


def _run_tts(text: str, voice_name: str | None = None) -> bool:
    import os as _os

    active = voice_name or get_active_voice()
    chunks = _tts_chunks(text)

    if not chunks:
        return False

    try:
        max_chunks = int(_os.environ.get("ELI_TTS_MAX_CHUNKS", "0") or "0")
    except Exception:
        max_chunks = 0
    if max_chunks > 0 and len(chunks) > max_chunks:
        try:
            from eli.runtime.evidence_ledger import record_event as _eli_record_event
            _eli_record_event(
                "tts_truncated",
                source="tts_router",
                action="SPEAK",
                subject=active,
                content=str(text or "")[:1000],
                payload={"chunks": len(chunks), "max_chunks": max_chunks},
                severity="error",
                outcome="truncated",
                reusable=True,
            )
        except Exception:
            pass
        # The default is unlimited. If the operator explicitly sets a cap, log it
        # but do not silently pretend the spoken response was complete.
        chunks = chunks[:max_chunks]

    ok_all = True
    for i, chunk in enumerate(chunks, 1):
        log.debug(f"[TTS_FINAL_PIPER_ONLY_CHUNK] {i}/{len(chunks)} voice={active} chars={len(chunk)}")
        ok = _speak_piper_cli(chunk, active)
        if not ok:
            log.debug("[TTS_FINAL_PIPER_ONLY] failed; robot fallback disabled.")
            ok_all = False
            break

    try:
        from eli.runtime.evidence_ledger import record_event as _eli_record_event
        _eli_record_event(
            "tts_playback",
            source="tts_router",
            action="SPEAK",
            subject=active,
            content=str(text or "")[:1000],
            payload={"chunks": len(chunks), "ok": ok_all},
            severity="info" if ok_all else "error",
            outcome="ok" if ok_all else "failed",
            reusable=True,
        )
    except Exception:
        pass

    return ok_all


def speak(text: str, voice_name: str | None = None) -> bool:
    import threading as _threading

    text = _eli_tts_visible_text(text)
    clean = str(text or "").strip()
    if not clean:
        return False

    def _runner():
        _run_tts(clean, voice_name=voice_name)

    _threading.Thread(target=_runner, daemon=True).start()
    return True


def speak_if_enabled(text: str, enabled: bool = True, voice_name: str | None = None) -> bool:
    if not enabled:
        return False
    return speak(text, voice_name=voice_name)


def maybe_speak(response, tts_engine=None, enabled: bool = False, voice_name: str | None = None):
    if not enabled:
        return None
    text = response.get("full_text") or response.get("response") or response.get("content") if isinstance(response, dict) else str(response or "")
    if text:
        return speak(text, voice_name=voice_name)
    return None


def speak_text(text: str, *, piper_path: str | None = None, model_path: str | None = None, rate: str = "165") -> dict:
    text = _eli_tts_visible_text(text)
    voice_name = None
    if model_path:
        from pathlib import Path as _Path
        voice_name = _Path(model_path).stem
    ok = _run_tts(str(text or ""), voice_name=voice_name)
    return {"ok": bool(ok), "backend": "piper_cli_final" if ok else None}
