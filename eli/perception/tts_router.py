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
from typing import Any, Dict, Optional

from eli.utils.platform_compat import LINUX


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

# Default Piper voice (can be overridden via setting or env).
# Must match voice_assets._PIPER_VOICE and public bundle policy (no NC-SA ryan).
_DEFAULT_VOICE = "en_US-amy-medium"
_SYSTEM_VOICE_PREFIX = "sys:"

# Expressive Piper prosody. Piper at bare defaults sounds flat and clips full
# stops (the "Amy misses ?/!/." complaint): the CLI default sentence silence is
# ~0.2s, and the model's own noise/length defaults are conservative. These give a
# clear pause after each sentence and slightly more pitch variation so questions
# and exclamations land, without sounding wobbly. All overridable via env.
#   length_scale    phoneme duration (pacing); >1 slower/more deliberate
#   noise_scale     generator noise (expressiveness / pitch variation)
#   noise_w         phoneme-width noise (natural timing variation)
#   sentence_silence seconds of silence after each '.', '?' or '!'
_PIPER_PROSODY_DEFAULTS = {
    "length_scale": 1.03,
    "noise_scale": 0.72,
    "noise_w": 0.85,
    "sentence_silence": 0.38,
}


def _piper_prosody_args() -> "list[str]":
    """Build Piper CLI prosody flags from env overrides + expressive defaults.
    Returns [] if disabled (ELI_TTS_PROSODY=0) so a user can fall back to Piper's
    own per-voice defaults. Reads settings once; never raises."""
    if os.environ.get("ELI_TTS_PROSODY", "1").strip().lower() in {"0", "false", "no", "off"}:
        return []
    vals = dict(_PIPER_PROSODY_DEFAULTS)
    try:
        from eli.core.runtime_settings import load_settings
        s = load_settings() or {}
        for k in vals:
            v = s.get(f"tts_{k}")
            if v is not None:
                vals[k] = v
    except Exception:
        log.debug("[TTS] prosody settings read failed", exc_info=True)
    # Emotional delivery: the current tone (from tone_adaptor) overrides the base
    # pace / expressiveness / sentence-pause so ELI's VOICE carries the emotion —
    # slow+flat+long pauses for sad, fast+bright+short for ecstatic, etc.
    try:
        from eli.cognition import tone_adaptor
        for k, v in (tone_adaptor.voice_prosody() or {}).items():
            if k in vals and v is not None:
                vals[k] = v
    except Exception:
        log.debug("[TTS] tone prosody merge skipped", exc_info=True)
    for k in vals:  # env wins over everything (explicit user pin)
        ev = os.environ.get(f"ELI_TTS_{k.upper()}", "").strip()
        if ev:
            vals[k] = ev
    args: "list[str]" = []
    for flag, key in (("--length_scale", "length_scale"), ("--noise_scale", "noise_scale"),
                      ("--noise_w", "noise_w"), ("--sentence_silence", "sentence_silence")):
        try:
            args += [flag, str(float(vals[key]))]
        except (TypeError, ValueError):
            log.debug("[TTS] bad prosody value for %s: %r", key, vals[key])
    return args


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


def _play_wav_blocking(wav_path, *, fallback_players=None, post_play_tail: float | None = None) -> bool:
    """Blocking WAV playback; feeds expression_state amplitude when sounddevice is available."""
    import os as _os
    import subprocess as _subprocess
    import time as _time
    from pathlib import Path as _Path

    path = _Path(wav_path)
    if not path.is_file() or path.stat().st_size < 100:
        return False

    _es = None
    try:
        from eli.cognition import expression_state as _es_mod
        _es = _es_mod
    except Exception:
        log.debug("[TTS] expression_state unavailable for amplitude lip-sync", exc_info=True)

    try:
        import numpy as _np
        import sounddevice as _sd
        import soundfile as _sf

        data, sr = _sf.read(str(path), dtype="float32")
        if getattr(data, "ndim", 1) > 1:
            data = data.mean(axis=1)
        data = _np.asarray(data, dtype="float32").reshape(-1)
        if data.size == 0:
            raise ValueError("empty wav")

        pos = 0
        block = max(512, int(sr * 0.04))

        def _callback(outdata, frames, _time_info, status):
            nonlocal pos
            if status:
                log.debug(f"[TTS] sounddevice status: {status}")
            end = min(pos + frames, data.size)
            chunk = data[pos:end]
            if chunk.size == 0:
                outdata.fill(0)
                raise _sd.CallbackStop()
            outdata[:chunk.size, 0] = chunk
            if chunk.size < frames:
                outdata[chunk.size:, 0] = 0
                pos = data.size
                raise _sd.CallbackStop()
            pos = end
            if _es is not None:
                rms = float(_np.sqrt(_np.mean(chunk ** 2)))
                _es.set_amplitude(min(1.0, rms * 4.0))

        with _sd.OutputStream(samplerate=int(sr), channels=1, callback=_callback):
            _sd.sleep(int((data.size / float(sr)) * 1000) + 80)
        if _es is not None:
            _es.set_amplitude(0.0)
        tail = post_play_tail
        if tail is None:
            tail = float(_os.environ.get("ELI_TTS_POST_PLAY_TAIL_SEC", "0.35"))
        if tail > 0:
            _time.sleep(tail)
        return True
    except Exception:
        log.debug("[TTS] amplitude-aware playback unavailable; falling back to CLI player", exc_info=True)

    players = list(fallback_players or [])
    for player in players:
        player_name = _Path(player).name.lower()
        if player_name == "aplay":
            play_cmd = [player, "-q", str(path)]
        elif player_name in ("powershell", "pwsh", "powershell.exe", "pwsh.exe"):
            _safe_wav = str(path).replace("'", "''")
            play_cmd = [
                player, "-NoProfile", "-Command",
                f"(New-Object Media.SoundPlayer '{_safe_wav}').PlaySync()",
            ]
        else:
            play_cmd = [player, str(path)]

        play_proc = _subprocess.run(
            play_cmd,
            stdout=_subprocess.PIPE,
            stderr=_subprocess.PIPE,
            text=True,
            check=False,
        )
        log.debug(f"[TTS_PLAY] player={player_name} rc={play_proc.returncode}")
        if play_proc.returncode == 0:
            tail = post_play_tail
            if tail is None:
                tail = float(_os.environ.get("ELI_TTS_POST_PLAY_TAIL_SEC", "0.35"))
            if tail > 0:
                _time.sleep(tail)
            return True
    return False


def _play_wav_bytes(wav_bytes: bytes) -> bool:
    """Play WAV bytes on any supported OS without requiring Linux audio CLIs."""
    if not wav_bytes:
        return False
    suffix = ".wav"
    try:
        with tempfile.NamedTemporaryFile(prefix="eli_tts_", suffix=suffix, delete=False) as f:
            f.write(wav_bytes)
            path = f.name
        return _play_wav_blocking(path)
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


# Enumerating system voices is done OUT OF PROCESS on purpose — see below.
_SYSTEM_VOICES_CACHE: "list[str] | None" = None

_ENUM_SNIPPET = (
    "import pyttsx3\n"
    "e = pyttsx3.init()\n"
    "for v in (e.getProperty('voices') or []):\n"
    "    i = getattr(v, 'id', None)\n"
    "    if i:\n"
    "        print(i)\n"
    "try:\n"
    "    e.stop()\n"
    "except Exception:\n"
    "    pass\n"
)


def _list_system_voices(refresh: bool = False) -> list[str]:
    """OS-installed voices via pyttsx3 (SAPI on Windows, NSS on macOS, espeak on
    Linux), prefixed ``sys:``.

    Runs in a SUBPROCESS, deliberately. espeak-ng has a fixed ``N_VOICES_LIST``
    of 350; on a box with more installed voice/variant combinations than that,
    ``espeak_ListVoices`` walks off the end of the array and corrupts the heap —
    "double free or corruption (!prev)" then ``abort()``. That is a native crash,
    so a Python ``except`` around it catches NOTHING: it took the whole GUI down
    mid-session (observed on Linux with a large voice set installed). Isolating
    the enumeration means the worst case is an empty list from a dead child
    instead of ELI core-dumping. Result is cached for the process.
    """
    global _SYSTEM_VOICES_CACHE
    if _SYSTEM_VOICES_CACHE is not None and not refresh:
        return list(_SYSTEM_VOICES_CACHE)

    out: list[str] = []
    try:
        # Probe the binding IN-PROCESS first. Importing pyttsx3 is safe (the
        # espeak overflow is in init()/getProperty(), not import), and this keeps
        # the child honest: if the caller has no real pyttsx3 — absent, or
        # replaced by a stub in the mocked test lane — there are no system
        # voices, and we must NOT shell out to a fresh interpreter that would
        # bypass that substitution and report the host's real voices.
        import pyttsx3 as _p3
        if type(_p3).__name__ == "MagicMock" or type(getattr(_p3, "init", None)).__name__ == "MagicMock":
            _SYSTEM_VOICES_CACHE = []
            return []
    except Exception:
        log.debug("[TTS] pyttsx3 unavailable — no system voices", exc_info=True)
        _SYSTEM_VOICES_CACHE = []
        return []

    try:
        import subprocess as _sp
        import sys as _sys
        proc = _sp.run([_sys.executable, "-c", _ENUM_SNIPPET],
                       stdout=_sp.PIPE, stderr=_sp.DEVNULL, timeout=20)
        if proc.returncode == 0:
            for line in (proc.stdout or b"").decode("utf-8", "replace").splitlines():
                vid = line.strip()
                if vid:
                    out.append(f"{_SYSTEM_VOICE_PREFIX}{vid}")
        else:
            # Negative return code = killed by a signal (SIGABRT/SIGSEGV) — the
            # espeak overflow above. Report it; do not retry in-process.
            log.debug("[TTS] system-voice enumeration exited %s (native crash "
                      "isolated in the child — no system voices listed)",
                      proc.returncode)
    except Exception:
        log.debug("[TTS] system-voice enumeration unavailable", exc_info=True)

    _SYSTEM_VOICES_CACHE = list(out)
    return out


# Piper quality tiers that sound synthetic/robotic. Hidden by default so the voice
# list is only natural-sounding voices; still loadable if explicitly named, and
# surfaced as a genuine last resort when nothing better exists on the box.
_LOW_QUALITY_SUFFIXES = ("-x_low", "-low")


def _is_low_quality_piper(name: str) -> bool:
    return str(name or "").endswith(_LOW_QUALITY_SUFFIXES)


def _allow_robotic_voices() -> bool:
    """Opt back in to espeak `sys:` + low-quality Piper voices (default: hidden)."""
    return os.environ.get("ELI_TTS_ALLOW_ROBOTIC", "0").strip().lower() in {"1", "true", "yes", "on"}


def list_voices() -> list[str]:
    """Runnable voices, natural-sounding only by default.

    Order: good Piper voices (medium/high), then character (`char:`) and cloned/
    natural neural (`clone:`) voices. Robotic voices — espeak `sys:` and Piper
    `low`/`x_low` — are HIDDEN unless ``ELI_TTS_ALLOW_ROBOTIC=1``, or unless the box
    has no natural voice at all (then they return as a functional last resort so
    ELI is never mute). This is the "get rid of the robotic voices" policy.
    """
    voices: list[str] = []
    low: list[str] = []
    seen: set[str] = set()
    allow_robotic = _allow_robotic_voices()
    for d in _voice_search_dirs():
        try:
            for f in sorted(d.glob("*.onnx")):
                if not _has_piper_config(f):
                    continue
                name = f.stem  # e.g. en_US-lessac-high
                if name in seen:
                    continue
                seen.add(name)
                if _is_low_quality_piper(name) and not allow_robotic:
                    low.append(name)      # deferred; only used as last resort
                else:
                    voices.append(name)
        except Exception:
            pass
    # Character voices (char:hal, char:tars, …) — base voice + ffmpeg effect chain.
    try:
        from eli.perception import voice_fx
        for c in voice_fx.list_characters():
            if c["id"] not in seen:
                seen.add(c["id"])
                voices.append(c["id"])
    except Exception:
        pass
    # Cloned / natural neural voices (clone:<name>) — XTTS-v2.
    try:
        from eli.perception import tts_xtts
        for c in tts_xtts.list_clones():
            if c["id"] not in seen:
                seen.add(c["id"])
                voices.append(c["id"])
    except Exception:
        pass
    # Natural neural built-in voices (natural:<speaker>) — XTTS-v2, no clone needed.
    try:
        from eli.perception import tts_xtts
        for nid in tts_xtts.list_natural_voices():
            if nid not in seen:
                seen.add(nid)
                voices.append(nid)
    except Exception:
        pass
    sys_voices = [sv for sv in _list_system_voices() if sv not in seen]
    if allow_robotic:
        voices.extend(sys_voices)
        voices.extend(low)
    elif not voices:
        # Nothing natural on this box — return the robotic ones so ELI can still
        # speak, rather than an empty list (mute).
        voices.extend(low)
        voices.extend(sys_voices)
    return voices


def _is_system_voice(name: str) -> bool:
    return str(name or "").startswith(_SYSTEM_VOICE_PREFIX)


def _system_voice_id(name: str) -> str:
    return str(name or "")[len(_SYSTEM_VOICE_PREFIX):]


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
    installed = list_voices()
    if _DEFAULT_VOICE in installed:
        return _DEFAULT_VOICE
    piper_only = [v for v in installed if not _is_system_voice(v)]
    if piper_only:
        return piper_only[0]
    if installed:
        return installed[0]
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


def _neural_engine_available() -> bool:
    """True when XTTS-v2 can actually synthesise (coqui-tts + torch present)."""
    try:
        from eli.perception import tts_xtts
        return bool(tts_xtts.xtts_available())
    except Exception:
        return False


def available_backends() -> dict:
    installed = list_voices()
    active = get_active_voice()
    # `natural:`/`clone:`/`char:` voices are not Piper models. find_voice_model()
    # cannot resolve them and returns whatever its fallback picks — alphabetically
    # the first installed voice — so the panel showed "Active model file:
    # cs_CZ-jirka-medium.onnx" for a natural: voice while synthesis actually used
    # en_US-amy-medium. Report the model that will really be used.
    _is_neural = str(active).startswith(("natural:", "clone:"))
    active_model = find_voice_model(_DEFAULT_VOICE if _is_neural else active)
    return {
        "piper_python": True,
        "piper_bin": _find_piper_bin(),
        "piper_voices": installed,
        "system_voices": [v for v in installed if _is_system_voice(v)],
        "active_voice": active,
        "default_voice": _DEFAULT_VOICE,
        "neural_available": _neural_engine_available(),
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

# Set once if the piper binary can't use CUDA (build without GPU / CUDA
# unavailable). Keeps the session on CPU after a single failed --cuda attempt.
_PIPER_CUDA_FAILED = False

# ── Neural-voice fallback state (observable, not silent) ─────────────────────
# A `natural:`/`clone:` voice that cannot synthesise fell through to Piper with no
# log line at all. Live consequence: Settings reported "Active voice: natural:sophia"
# while every reply was spoken by en_US-amy-medium, and a user who dropped in a voice
# clip had no way to learn that the clone was registered but never used — the only
# hint appeared once, in the creation dialog. Record WHY, so the diagnostics panel and
# the console agree with what is actually coming out of the speakers.
_NEURAL_FALLBACK: Dict[str, Any] = {"active": False, "requested": "", "reason": ""}


def _neural_unavailable_reason() -> str:
    """Why a neural voice cannot synthesise right now, in one line."""
    try:
        from eli.perception import tts_xtts
        if not tts_xtts.xtts_available():
            return ("the neural voice engine (coqui-tts + torch) is not installed in "
                    "this build")
    except Exception:
        return "the neural voice engine could not be loaded"
    return "the neural engine is present but produced no audio for this voice"


def _note_neural_fallback(requested) -> None:
    """Record (and log once per change) that a neural voice fell back to Piper."""
    global _NEURAL_FALLBACK
    if not requested:
        if _NEURAL_FALLBACK.get("active"):
            log.debug("[TTS_NEURAL] neural voice is working again")
        _NEURAL_FALLBACK = {"active": False, "requested": "", "reason": ""}
        return
    reason = _neural_unavailable_reason()
    if (not _NEURAL_FALLBACK.get("active")) or _NEURAL_FALLBACK.get("requested") != requested:
        log.warning(
            "[TTS_NEURAL] '%s' could not synthesise — %s. Falling back to the Piper "
            "voice '%s'. The selected voice is NOT what you are hearing.",
            requested, reason, _DEFAULT_VOICE,
        )
    _NEURAL_FALLBACK = {"active": True, "requested": str(requested), "reason": reason}


def neural_fallback_state() -> Dict[str, Any]:
    """Public read for the diagnostics panel. Empty dict-ish when all is well."""
    return dict(_NEURAL_FALLBACK)


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
        or _os.environ.get("ELI_PIPER_BIN", "").strip()
        or _eli_packaged_cli_bin
        or _shutil.which("piper")
        or str(_Path.cwd() / ".venv" / "bin" / "piper")
    )

    if not (_Path(piper_bin).exists() or _shutil.which(piper_bin)):
        log.debug(f"[TTS_FINAL_PIPER_ONLY] missing piper binary: {piper_bin}")
        return False

    # Blocking WAV players, chosen per platform. Linux: ALSA/Pulse. macOS: afplay.
    # Windows: PowerShell's SoundPlayer.PlaySync (blocking).
    from eli.utils import platform_compat as _pc
    players = []
    if _pc.WINDOWS:
        ps = _shutil.which("powershell") or _shutil.which("pwsh")
        if ps:
            players.append(ps)
    elif _pc.MACOS:
        found = _shutil.which("afplay")
        if found:
            players.append(found)
    else:
        for cand in ("aplay", "paplay"):
            found = _shutil.which(cand)
            if found:
                players.append(found)

    if not players:
        log.debug("[TTS_FINAL_PIPER_ONLY] no blocking WAV player found for this platform")
        return False

    cfg = _find_piper_config(model)
    lock_path = _Path(
        _os.environ.get("ELI_TTS_SPEAKING_LOCK")
        or (_Path(_tempfile.gettempdir()) / "eli_tts_speaking.lock")
    )

    with _tempfile.NamedTemporaryFile(prefix="eli_piper_final_", suffix=".wav", delete=False) as tmp:
        wav = _Path(tmp.name)

    global _PIPER_CUDA_FAILED
    _want_cuda = (
        _os.environ.get("ELI_PIPER_CUDA", "1").strip().lower() in {"1", "true", "yes", "on"}
        and not _PIPER_CUDA_FAILED
    )
    _base_cmd = [piper_bin, "--model", str(model), "--output_file", str(wav)]
    if cfg:
        _base_cmd.extend(["--config", str(cfg)])
    _base_cmd.extend(_piper_prosody_args())  # expressive pacing + sentence pauses

    def _run_piper(use_cuda):
        _cmd = list(_base_cmd) + (["--cuda"] if use_cuda else [])
        return _subprocess.run(
            _cmd, input=str(text or ""), text=True,
            stdout=_subprocess.PIPE, stderr=_subprocess.PIPE, timeout=45,
        )

    try:
        try:
            lock_path.write_text(str(_os.getpid()), encoding="utf-8")
        except Exception:
            pass

        proc = _run_piper(_want_cuda)
        # GPU not supported by this piper build / CUDA unavailable → remember and
        # use CPU for the rest of the session (piper is fast on CPU anyway).
        if proc.returncode != 0 and _want_cuda:
            _PIPER_CUDA_FAILED = True
            log.debug(
                f"[TTS_FINAL_PIPER_ONLY] --cuda failed rc={proc.returncode}; "
                f"falling back to CPU: {proc.stderr[-300:]}")
            proc = _run_piper(False)

        if proc.returncode != 0:
            log.debug(f"[TTS_FINAL_PIPER_ONLY] piper failed rc={proc.returncode}: {proc.stderr[-800:]}")
            return False

        if not wav.exists() or wav.stat().st_size < 1000:
            log.debug(f"[TTS_FINAL_PIPER_ONLY] wav missing/empty: {wav}")
            return False

        log.debug(
            f"[TTS_FINAL_PIPER_ONLY] voice={active} model={_Path(model).name} bytes={wav.stat().st_size}",
        )

        if _play_wav_blocking(wav, fallback_players=players):
            return True

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


def _eli_tts_is_unspeakable(text) -> bool:
    """True for degenerate output that must never be spoken — empty, too short,
    punctuation-only, or a leading-symbol stub ('-', '-Auto', '-Auto/G 5/').
    Speaking these is meaningless and crashed piper ('# channels not specified')
    on a lone '-'. Mirrors the engine fragment guard so '34G', 'No.', 'Volume
    down' remain speakable."""
    s = str(text or "").strip()
    if len(s) < 2:
        return True
    if not re.search(r"[A-Za-z0-9]", s):          # only symbols/whitespace
        return True
    words = re.findall(r"[A-Za-z]{2,}", s)
    if not words and not re.search(r"\d", s):      # e.g. '-G' (no word, no digit)
        return True
    if len(s) < 12 and not s[0].isalnum():         # short leading-symbol stub
        return True
    return False


def _speak_pyttsx3(text: str, voice_name: str) -> bool:
    """Speak via OS TTS (Windows SAPI, macOS NSS, Linux espeak backend in pyttsx3)."""
    try:
        import pyttsx3

        eng = pyttsx3.init()
        vid = _system_voice_id(voice_name) if _is_system_voice(voice_name) else voice_name
        if vid:
            eng.setProperty("voice", vid)
        eng.say(str(text or ""))
        eng.runAndWait()
        try:
            eng.stop()
        except Exception:
            pass
        return True
    except Exception:
        log.debug("[TTS] pyttsx3 speak failed", exc_info=True)
        return False


def _run_tts(text: str, voice_name: str | None = None) -> bool:
    # Mark the avatar "speaking" for the whole synth+play so the face lip-syncs;
    # cleared in every exit path. Best-effort — never let it block TTS.
    try:
        from eli.cognition import expression_state as _es
        _es.set_speaking(True)
    except Exception:
        _es = None
        log.debug("[TTS] speaking-state set failed", exc_info=True)
    try:
        return _run_tts_impl(text, voice_name=voice_name)
    finally:
        if _es is not None:
            try:
                _es.set_speaking(False)
            except Exception:
                log.debug("[TTS] speaking-state clear failed", exc_info=True)


def _run_tts_impl(text: str, voice_name: str | None = None) -> bool:
    import os as _os

    active = voice_name or get_active_voice()
    # Character (char:) / cloned (clone:) / natural neural (natural:) voice → render via
    # synthesize_wav (which owns the effect chain / XTTS + fallback), then play the WAV.
    if str(active).startswith(("char:", "clone:", "natural:")):
        wav = synthesize_wav(text, voice_name=active)
        return _play_wav_bytes(wav) if wav else False
    # Never voice a degenerate fragment (also avoids the piper wave crash on '-').
    if _eli_tts_is_unspeakable(text):
        log.debug(f"[TTS_FINAL_PIPER_ONLY] skipped unspeakable text: {str(text)[:24]!r}")
        return False
    chunks = _tts_chunks(text)

    if not chunks:
        return False

    use_system = _is_system_voice(active) or (
        _os.environ.get("ELI_TTS_BACKEND", "").strip().lower() in {"system", "pyttsx3"}
    )
    if use_system and _is_system_voice(active):
        ok_all = True
        for i, chunk in enumerate(chunks, 1):
            log.debug(f"[TTS_SYSTEM] {i}/{len(chunks)} voice={active[:48]} chars={len(chunk)}")
            if not _speak_pyttsx3(chunk, active):
                ok_all = False
                break
        return ok_all

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
        if not ok and _os.environ.get("ELI_TTS_FALLBACK", "").strip().lower() in {
            "1", "true", "yes", "on", "system", "pyttsx3",
        }:
            sys_voices = _list_system_voices()
            if sys_voices:
                log.debug("[TTS] Piper failed; falling back to system voice.")
                ok = _speak_pyttsx3(chunk, sys_voices[0])
        if not ok:
            log.debug("[TTS_FINAL_PIPER_ONLY] failed; no further fallback.")
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


# ── Synthesise to WAV bytes (no host playback) — powers browser voice ───────
# The browser plays the audio itself, so the host must NOT use aplay/afplay here.
# Reuses the same Piper binary/voice discovery + CUDA→CPU fallback as _speak_piper_cli.

def _piper_render_wav(text: str, model, cfg, piper_bin: str) -> Optional[bytes]:
    """Run Piper once for `text`, returning WAV bytes (CUDA→CPU fallback). No playback."""
    import os as _os
    import subprocess as _subprocess
    import tempfile as _tempfile
    from pathlib import Path as _Path

    with _tempfile.NamedTemporaryFile(prefix="eli_piper_wav_", suffix=".wav", delete=False) as tmp:
        wav = _Path(tmp.name)

    global _PIPER_CUDA_FAILED
    _want_cuda = (
        _os.environ.get("ELI_PIPER_CUDA", "1").strip().lower() in {"1", "true", "yes", "on"}
        and not _PIPER_CUDA_FAILED
    )
    base_cmd = [piper_bin, "--model", str(model), "--output_file", str(wav)]
    if cfg:
        base_cmd.extend(["--config", str(cfg)])
    base_cmd.extend(_piper_prosody_args())  # same expressive prosody as host playback

    def _run(use_cuda):
        cmd = list(base_cmd) + (["--cuda"] if use_cuda else [])
        return _subprocess.run(cmd, input=str(text or ""), text=True,
                               stdout=_subprocess.PIPE, stderr=_subprocess.PIPE, timeout=45)
    try:
        proc = _run(_want_cuda)
        if proc.returncode != 0 and _want_cuda:
            _PIPER_CUDA_FAILED = True
            log.debug(f"[TTS_WAV] --cuda failed rc={proc.returncode}; CPU fallback: {proc.stderr[-300:]}")
            proc = _run(False)
        if proc.returncode != 0:
            log.debug(f"[TTS_WAV] piper failed rc={proc.returncode}: {proc.stderr[-400:]}")
            return None
        if not wav.exists() or wav.stat().st_size < 1000:
            return None
        return wav.read_bytes()
    except Exception:
        log.debug("[TTS_WAV] render failed", exc_info=True)
        return None
    finally:
        try:
            wav.unlink(missing_ok=True)
        except Exception:
            pass


def _concat_wavs(wavs: list[bytes]) -> Optional[bytes]:
    """Concatenate same-format WAV chunks into a single WAV (PCM frame splice)."""
    wavs = [w for w in wavs if w]
    if not wavs:
        return None
    if len(wavs) == 1:
        return wavs[0]
    import wave
    params = None
    frames = bytearray()
    for wb in wavs:
        with wave.open(io.BytesIO(wb), "rb") as wf:
            if params is None:
                params = wf.getparams()
            frames += wf.readframes(wf.getnframes())
    out = io.BytesIO()
    with wave.open(out, "wb") as wf:
        wf.setparams(params)
        wf.writeframes(bytes(frames))
    return out.getvalue()


def _apply_tone_pitch(wav_bytes: Optional[bytes]) -> Optional[bytes]:
    """Shift the synthesized audio by the current emotion's pitch (semitones) so a
    `sad` reply sounds lower and an `ecstatic` one higher — the pitch dimension the
    Piper CLI can't do itself. No-op when pitch≈0 or ffmpeg is missing (fail open)."""
    if not wav_bytes:
        return wav_bytes
    try:
        from eli.cognition import tone_adaptor
        semis = float((tone_adaptor.voice_prosody() or {}).get("pitch") or 0.0)
    except Exception:
        return wav_bytes
    if abs(semis) < 0.1 or not shutil.which("ffmpeg"):
        return wav_bytes
    import subprocess as _sp
    import tempfile as _tf
    sr = _wav_sample_rate_bytes(wav_bytes)
    factor = max(0.5, min(2.0, 2.0 ** (semis / 12.0)))
    # asetrate shifts pitch+speed; atempo restores duration → pitch-only shift.
    chain = f"asetrate={int(sr*factor)},aresample={sr},atempo={1.0/factor:.4f}"
    out = ""
    try:
        fd, out = _tf.mkstemp(suffix=".wav"); __import__("os").close(fd)
        proc = _sp.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                        "-f", "wav", "-i", "pipe:0", "-af", chain, out],
                       input=wav_bytes, stdout=_sp.PIPE, stderr=_sp.PIPE, timeout=30)
        if proc.returncode == 0 and __import__("os").path.getsize(out) > 0:
            return Path(out).read_bytes()
    except Exception:
        log.debug("[TTS] tone pitch shift failed", exc_info=True)
    finally:
        if out:
            try:
                __import__("os").unlink(out)
            except OSError:
                log.debug("[TTS] pitch temp cleanup failed", exc_info=True)
    return wav_bytes


def _wav_sample_rate_bytes(wav_bytes: bytes) -> int:
    import io as _io
    import wave as _wave
    try:
        with _wave.open(_io.BytesIO(wav_bytes)) as w:
            return w.getframerate() or 22050
    except Exception:
        return 22050


def synthesize_wav(text: str, voice_name: str | None = None) -> Optional[bytes]:
    """Render `text` to WAV bytes with the active Piper voice — for clients that
    play audio themselves (browser voice). Returns None if nothing speakable or
    no Piper voice/binary is available. Never plays on the host."""
    text = _eli_tts_visible_text(text)
    if _eli_tts_is_unspeakable(text):
        return None
    active = voice_name or get_active_voice()
    # Natural neural voice (natural:<id>): XTTS-v2 built-in speaker, human-like, no
    # clone needed. If the neural extra isn't installed, returns None → Piper default.
    if str(active).startswith("natural:"):
        try:
            from eli.perception import tts_xtts
            wav = tts_xtts.synthesize_natural_wav(text, active)
            if wav:
                _note_neural_fallback(None)
                return _apply_tone_pitch(wav)
            _note_neural_fallback(active)
        except Exception:
            log.debug("[TTS_WAV] natural voice resolve failed", exc_info=True)
            _note_neural_fallback(active)
        active = _DEFAULT_VOICE
    # Cloned voice (clone:<name>): Coqui XTTS-v2 from a reference sample. If the extra
    # isn't installed / no reference, returns None → we fall back to the default voice.
    if str(active).startswith("clone:"):
        try:
            from eli.perception import tts_xtts
            wav = tts_xtts.synthesize_wav(text, active)
            if wav:
                _note_neural_fallback(None)
                return _apply_tone_pitch(wav)
            _note_neural_fallback(active)
        except Exception:
            log.debug("[TTS_WAV] clone voice resolve failed", exc_info=True)
            _note_neural_fallback(active)
        active = _DEFAULT_VOICE
    # Character voice (char:hal, char:tars, …): synth the base Piper voice, then run
    # its ffmpeg effect chain over the result. Recurses once with a real base voice.
    if str(active).startswith("char:"):
        try:
            from eli.perception import voice_fx
            spec = voice_fx.get_preset(active)
            if spec:
                # Resolve to a base voice that is actually installed: the ideal
                # `base`, else each gender-matched `fallback` in order, else the
                # English default. Never let a missing base fall through to the
                # generic resolver, which picks the first .onnx alphabetically (a
                # foreign-language voice in the shipped pack) and garbles the text.
                base = voice_fx.resolve_base_voice(
                    spec, list_voices(), default=_DEFAULT_VOICE)
                base_wav = synthesize_wav(text, voice_name=base)
                return voice_fx.apply_fx(base_wav, spec) if base_wav else None
        except Exception:
            log.debug("[TTS_WAV] character voice resolve failed", exc_info=True)
        active = _DEFAULT_VOICE  # unknown character → safe default
    model = find_voice_model(active)
    if not model:
        log.debug(f"[TTS_WAV] no voice model for active={active}")
        return None
    piper_bin = _find_piper_bin()
    if not piper_bin:
        log.debug("[TTS_WAV] no piper binary available")
        return None
    cfg = _find_piper_config(model)
    chunks = _tts_chunks(text) or [text]
    rendered = [_piper_render_wav(c, model, cfg, piper_bin) for c in chunks]
    return _apply_tone_pitch(_concat_wavs([r for r in rendered if r]))
