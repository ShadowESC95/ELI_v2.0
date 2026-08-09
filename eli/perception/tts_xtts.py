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
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)

CLONE_PREFIX = "clone:"
NATURAL_PREFIX = "natural:"
_XTTS_MODEL = "tts_models/multilingual/multi-dataset/xtts_v2"
_TTS = None  # lazy singleton

# Curated natural voices using XTTS-v2's BUILT-IN studio speakers — human-like
# neural TTS with NO clone/reference required. Friendly id → the speaker name we
# ask XTTS for; resolution is tolerant (see _resolve_builtin_speaker) so exact
# upstream name drift falls back to a real speaker instead of failing. This is the
# "indistinguishable from a human" path the startup picker can select.
_NATURAL_VOICES = {
    "sophia": {"speaker": "Claribel Dervla", "gender": "female",
               "desc": "Sophia — warm, natural female"},
    "aria":   {"speaker": "Daisy Studious", "gender": "female",
               "desc": "Aria — clear, articulate female"},
    "james":  {"speaker": "Andrew Chipper", "gender": "male",
               "desc": "James — bright, friendly male"},
    "daniel": {"speaker": "Damien Black", "gender": "male",
               "desc": "Daniel — deep, measured male"},
}
_DEFAULT_NATURAL = "sophia"


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
            log.debug('tts_xtts: reference clip cleanup failed', exc_info=True)
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
    """True when the neural backend can actually be imported. Cheap — no model load.

    The shim MUST run before `import TTS`, because coqui-tts reaches for
    `transformers.pytorch_utils.isin_mps_friendly` during its own import and
    transformers>=5 dropped that name. Checking importability first and patching
    afterwards means the patch is never reached: the import raises, this returns
    False, and neural voice is silently off on a machine that has torch, coqui-tts
    AND the 1.8GB XTTS weights all present and working.

    The ordering was swapped to stop a ModuleNotFoundError traceback appearing on
    launches without the optional extra — a real problem, but one the shim already
    handles internally by returning quietly when transformers or torch is absent.
    Quieting the console cost the whole feature.
    """
    _patch_transformers_compat()
    try:
        import TTS  # noqa: F401
    except Exception:
        return False
    return True


_COMPAT_PATCHED = False


def _patch_transformers_compat() -> None:
    """coqui-tts's XTTS layer imports `isin_mps_friendly`, a torch.isin() shim
    transformers carried for old Apple-MPS backends and dropped in transformers>=5.
    Off MPS, plain torch.isin() is exactly the same behaviour, so restore the name
    rather than pin transformers back (the rest of ELI is on transformers==5.x).

    Runs at most once. A missing `transformers`/`torch` is the EXPECTED state when the
    heavy clone extra isn't installed — that path stays quiet; only genuine failures
    (the module is present but the patch didn't take) are worth logging."""
    global _COMPAT_PATCHED
    if _COMPAT_PATCHED:
        return
    _COMPAT_PATCHED = True
    try:
        import transformers.pytorch_utils as _ptu
    except ModuleNotFoundError:
        return  # clone extra not installed — nothing to patch, nothing to report
    except Exception:
        log.debug("tts_xtts: transformers import failed", exc_info=True)
        return
    try:
        if not hasattr(_ptu, "isin_mps_friendly"):
            import torch as _torch
            _ptu.isin_mps_friendly = lambda elements, test_elements: _torch.isin(elements, test_elements)
    except ModuleNotFoundError:
        return  # torch absent — same expected optional-dependency case
    except Exception:
        log.debug("tts_xtts: transformers compat shim failed", exc_info=True)


def _get_model():
    global _TTS
    if _TTS is not None:
        return _TTS
    _patch_transformers_compat()
    # coqui-tts gates the first XTTS-v2 download behind an interactive y/n TOS
    # prompt (agree to the non-commercial CPML, or confirm a paid Coqui licence —
    # see TTS.utils.manage.ModelManager.ask_tos/tos_agreed). ELI's GUI has no TTY
    # for that prompt to read from, so it would otherwise hang/EOF-error on every
    # user's first clone. Using XTTS-v2 here is always the non-commercial path (a
    # local, personal voice — never redistributed, same policy as the rest of the
    # voice library), so this pre-accepts exactly that: COQUI_TOS_AGREED=1 makes
    # tos_agreed() short-circuit True, same effect as answering "y" at the prompt.
    os.environ.setdefault("COQUI_TOS_AGREED", "1")
    from TTS.api import TTS as _TTSApi
    device = _select_device()
    log.info("tts_xtts: loading XTTS-v2 on %s (first run downloads ~1.8GB)…", device)
    _TTS = _TTSApi(_XTTS_MODEL).to(device)
    return _TTS


def _select_device() -> str:
    """cuda if free VRAM allows, else cpu. ``ELI_XTTS_DEVICE`` forces it — this is
    how the startup picker pins the choice made BEFORE the main model grabs VRAM."""
    import os
    forced = os.environ.get("ELI_XTTS_DEVICE", "").strip().lower()
    if forced in ("cpu", "cuda"):
        return forced
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        log.debug("tts_xtts: torch/cuda probe failed", exc_info=True)
    return "cpu"


def natural_available() -> bool:
    """True when the neural natural-voice backend can run (the TTS package is
    installed). Cheap — does NOT load the ~1.8GB model."""
    return xtts_available()


def list_natural_voices() -> "list[str]":
    """Built-in neural voice ids (``natural:<id>``), or [] when XTTS isn't installed.
    Cheap: never loads the model, so it's safe to call from tts_router.list_voices()."""
    if not natural_available():
        return []
    return [NATURAL_PREFIX + k for k in _NATURAL_VOICES]


def natural_voice_meta(voice_id: str) -> Optional[Dict[str, Any]]:
    key = str(voice_id or "").lower().replace(NATURAL_PREFIX, "", 1).strip()
    return _NATURAL_VOICES.get(key)


def _resolve_builtin_speaker(model, wanted: str) -> Optional[str]:
    """Map a curated speaker name to one the loaded model actually has.
    Exact match → case-insensitive contains → first available speaker. Returns None
    only if the model exposes no speaker list at all (then caller omits speaker)."""
    try:
        speakers = list(getattr(model, "speakers", None)
                        or getattr(getattr(model, "synthesizer", None), "speakers", None) or [])
    except Exception:
        speakers = []
    if not speakers:
        return None
    for s in speakers:
        if str(s).strip().lower() == wanted.strip().lower():
            return s
    for s in speakers:
        if wanted.split()[0].lower() in str(s).lower():
            return s
    return speakers[0]


def synthesize_natural_wav(text: str, voice_id: str) -> Optional[bytes]:
    """Synthesize `text` with an XTTS-v2 built-in speaker — no clone needed.
    Returns WAV bytes, or None so the caller falls back to Piper (never raises)."""
    meta = natural_voice_meta(voice_id) or _NATURAL_VOICES.get(_DEFAULT_NATURAL)
    if not natural_available():
        log.info("tts_xtts: natural voice needs the neural extra — "
                 "`pip install -e \".[natural]\"` from the ELI project root (falling back to Piper)")
        return None
    import os as _os
    outpath = ""
    try:
        model = _get_model()
        speaker = _resolve_builtin_speaker(model, str(meta.get("speaker") or ""))
        fd, outpath = tempfile.mkstemp(suffix=".wav")
        _os.close(fd)
        Path(outpath).unlink(missing_ok=True)
        kwargs = {"text": str(text), "language": "en", "file_path": outpath}
        if speaker:
            kwargs["speaker"] = speaker
        model.tts_to_file(**kwargs)
        if Path(outpath).is_file() and Path(outpath).stat().st_size > 0:
            return Path(outpath).read_bytes()
    except Exception:
        log.debug("tts_xtts: natural synthesis failed", exc_info=True)
    finally:
        if outpath:
            try:
                Path(outpath).unlink(missing_ok=True)
            except OSError:
                log.debug('tts_xtts: temp wav cleanup failed', exc_info=True)
    return None


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
        log.info("tts_xtts: %s needs the voice-clone extra — "
                 "`pip install -e \".[clone]\"` from the ELI project root", str(clone_name))
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
