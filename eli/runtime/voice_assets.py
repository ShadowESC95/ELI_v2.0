"""Ensure the local voice models (STT + TTS weights) are present.

Browser voice (Phase 3) and desktop TTS need two on-disk assets that are **not**
committed to git (large binaries, gitignored): the faster-whisper STT model and at
least one Piper ``.onnx`` voice. The pip packages (``faster-whisper``, ``piper-tts``)
ship the *runtime*; this module fetches the *weights* during the installer's online
window. Best-effort, idempotent, and offline-safe — already-present assets are
reported WITHOUT touching the network, and every download is gated through
``netguard.allow_network`` so it honours ELI's offline-by-default posture.
"""
from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Any, Dict

log = logging.getLogger(__name__)

# Default Piper voice to fetch when the box has none. Hosted on rhasspy/piper-voices.
# (This is the same default tts_router falls back to: en_US-amy-medium.)
_PIPER_VOICE = "en_US-amy-medium"
_PIPER_BASE = ("https://huggingface.co/rhasspy/piper-voices/resolve/main/"
               "en/en_US/amy/medium/")

# ── Voice catalog ───────────────────────────────────────────────────────────────
# Curated Piper voices from rhasspy/piper-voices. tier: standard | advanced.
# NC-SA 'ryan' voices are offered for manual download but NEVER auto-bundled.
PIPER_CATALOG: Dict[str, Dict[str, str]] = {
    # Standard — clean, neutral, "robotic-normal"
    "en_US-amy-medium":        {"tier": "standard", "desc": "Amy (US female) — default, clear",      "license": "MIT"},
    "en_US-hfc_female-medium": {"tier": "standard", "desc": "HFC female (US) — neutral, crisp",       "license": "MIT"},
    "en_US-hfc_male-medium":   {"tier": "standard", "desc": "HFC male (US) — neutral, even",          "license": "MIT"},
    "en_US-joe-medium":        {"tier": "standard", "desc": "Joe (US male) — calm, steady",           "license": "MIT"},
    "en_US-kathleen-low":      {"tier": "standard", "desc": "Kathleen (US female) — light, quick",    "license": "MIT"},
    # Advanced — higher fidelity / more character
    "en_US-lessac-high":       {"tier": "advanced", "desc": "Lessac (US male) — high fidelity, smooth","license": "BSD"},
    "en_US-lessac-medium":     {"tier": "advanced", "desc": "Lessac (US male) — smooth, warm",        "license": "BSD"},
    "en_GB-alan-medium":       {"tier": "advanced", "desc": "Alan (UK male) — refined British",       "license": "OS"},
    "en_GB-northern_english_male-medium": {"tier": "advanced", "desc": "Northern English male — characterful", "license": "OS"},
    "en_US-kusal-medium":      {"tier": "advanced", "desc": "Kusal (US male) — expressive",           "license": "MIT"},
    # NC-SA — never auto-bundled into a release
    "en_US-ryan-high":         {"tier": "advanced", "desc": "Ryan (US male) — very natural (NC-SA)",  "license": "CC-BY-NC-SA"},
}


def _voice_url_base(voice_id: str) -> str:
    """Derive the rhasspy/piper-voices URL dir for a '<locale>-<name>-<quality>' id."""
    parts = str(voice_id).split("-")
    if len(parts) < 3:
        raise ValueError(f"bad voice id: {voice_id!r}")
    locale, quality = parts[0], parts[-1]
    name = "-".join(parts[1:-1])
    lang = locale.split("_")[0]
    return (f"https://huggingface.co/rhasspy/piper-voices/resolve/main/"
            f"{lang}/{locale}/{name}/{quality}/")


def _voice_present_strict(voice_id: str) -> bool:
    """True only when THIS exact voice's .onnx + .onnx.json exist (no fuzzy any-voice
    fallback — that would make every catalog voice look installed once one exists)."""
    dirs = [_piper_dest()]
    try:
        from eli.perception.tts_router import _voice_search_dirs
        dirs += list(_voice_search_dirs())
    except Exception:
        pass
    try:
        from eli.core.paths import project_root
        dirs.append(Path(project_root()) / "tts_piper" / "piper")
    except Exception:
        pass
    for d in dirs:
        onnx = Path(d) / f"{voice_id}.onnx"
        cfg = Path(d) / f"{voice_id}.onnx.json"
        if onnx.is_file() and onnx.stat().st_size > 0 and cfg.is_file() and cfg.stat().st_size > 0:
            return True
    return False


def piper_voice_ready(voice: str = _PIPER_VOICE) -> bool:
    """True when a runnable Piper ONNX voice exists (not merely OS/espeak voices)."""
    try:
        from eli.perception.tts_router import find_voice_model
        if find_voice_model(voice) is not None:
            return True
    except Exception:
        log.debug("voice_assets: piper router check failed", exc_info=True)
    # Fallback: scan the on-disk layout we download into.
    for base in (_piper_dest(),):
        for fn in (f"{voice}.onnx", f"{voice}.onnx.json"):
            p = base / fn
            if not p.is_file() or p.stat().st_size <= 0:
                break
        else:
            return True
    try:
        from eli.core.paths import project_root
        packaged = Path(project_root()) / "tts_piper" / "piper"
        for fn in (f"{voice}.onnx", f"{voice}.onnx.json"):
            p = packaged / fn
            if not p.is_file() or p.stat().st_size <= 0:
                break
        else:
            return True
    except Exception:
        log.debug("packaged piper voice probe failed", exc_info=True)
    return False


def _piper_present() -> bool:
    return piper_voice_ready(_PIPER_VOICE)


def _piper_dest() -> Path:
    try:
        from eli.core.paths import models_dir
        return Path(models_dir()) / "tts" / "piper"
    except Exception:
        return Path("models/tts/piper")


def _mirror_piper_to_packaged_layout(voice: str) -> None:
    """Also place the default voice where GitHub restore + portable builds expect it."""
    try:
        from eli.core.paths import project_root
        src = _piper_dest()
        dest = Path(project_root()) / "tts_piper" / "piper"
        dest.mkdir(parents=True, exist_ok=True)
        for fn in (f"{voice}.onnx", f"{voice}.onnx.json"):
            s = src / fn
            if s.is_file() and s.stat().st_size > 0:
                shutil.copy2(s, dest / fn)
    except Exception:
        log.debug("voice_assets: packaged piper mirror skipped", exc_info=True)


def download_voice(voice_id: str, mirror: bool = False) -> Dict[str, Any]:
    """Fetch any catalog (or well-formed) Piper voice: ``<id>.onnx`` + ``<id>.onnx.json``.
    Idempotent + offline-safe (netguard-gated). Streams to a ``.part`` then atomically
    replaces, so a killed download never leaves a half-written voice."""
    if _voice_present_strict(voice_id):
        if mirror:
            _mirror_piper_to_packaged_layout(voice_id)
        return {"ok": True, "asset": "piper", "already_present": True, "voice": voice_id}
    dest = _piper_dest()
    try:
        base = _voice_url_base(voice_id)
        dest.mkdir(parents=True, exist_ok=True)
        import urllib.request
        from eli.core import netguard
        with netguard.allow_network(f"voice asset: piper {voice_id}"):
            for fn in (f"{voice_id}.onnx", f"{voice_id}.onnx.json"):
                target = dest / fn
                if target.exists() and target.stat().st_size > 0:
                    continue
                req = urllib.request.Request(base + fn,
                                             headers={"User-Agent": "ELI/2.0 (voice-assets)"})
                tmp = target.with_suffix(target.suffix + ".part")
                with netguard.guarded_urlopen(req, timeout=300) as r, open(tmp, "wb") as fh:
                    shutil.copyfileobj(r, fh, length=1 << 20)
                if tmp.stat().st_size <= 0:
                    tmp.unlink(missing_ok=True)
                    return {"ok": False, "asset": "piper", "voice": voice_id,
                            "error": f"empty download: {fn}"}
                tmp.replace(target)
        if mirror:
            _mirror_piper_to_packaged_layout(voice_id)
        return {"ok": True, "asset": "piper", "already_present": False, "voice": voice_id}
    except Exception as e:
        log.debug("voice_assets: voice fetch failed (%s)", voice_id, exc_info=True)
        return {"ok": False, "asset": "piper", "voice": voice_id, "error": str(e)}


def list_catalog() -> "list[Dict[str, Any]]":
    """Curated Piper voices annotated with on-disk presence (for a picker / CLI)."""
    return [{"id": vid, "present": _voice_present_strict(vid), **meta}
            for vid, meta in PIPER_CATALOG.items()]


def ensure_piper_voice() -> Dict[str, Any]:
    """Fetch the default Piper voice if the box has none (installer's online step)."""
    return download_voice(_PIPER_VOICE, mirror=True)


def ensure_whisper() -> Dict[str, Any]:
    """Ensure the faster-whisper STT model is cached. faster-whisper downloads it on
    first construction; force CPU so the installer claims no VRAM, and gate the fetch."""
    os.environ.setdefault("ELI_WHISPER_DEVICE", "cpu")
    try:
        from eli.perception.local_whisper_stt import whisper_cache_ready
        from eli.perception import local_whisper_stt as W
        already = whisper_cache_ready()
        if already:
            os.environ.setdefault("ELI_WHISPER_LOCAL_ONLY", "1")
            W.preload_model()
            present = getattr(W, "_MODEL", None) is not None
            return {"ok": present, "asset": "whisper", "already_present": True,
                    **({} if present else {"error": "model cache present but load failed"})}
        from eli.core import netguard
        with netguard.allow_network("voice asset: whisper model"):
            prev_local = os.environ.get("ELI_WHISPER_LOCAL_ONLY")
            os.environ["ELI_WHISPER_LOCAL_ONLY"] = "0"
            try:
                W.preload_model()
            finally:
                if prev_local is None:
                    os.environ.pop("ELI_WHISPER_LOCAL_ONLY", None)
                else:
                    os.environ["ELI_WHISPER_LOCAL_ONLY"] = prev_local
        present = getattr(W, "_MODEL", None) is not None
        err = None if present else "model not loaded (is faster-whisper installed?)"
        return {"ok": present, "asset": "whisper",
                "already_present": False, **({} if present else {"error": err})}
    except ImportError:
        return {"ok": False, "asset": "whisper",
                "error": "faster-whisper not installed — re-run INSTALL_ELI.sh"}
    except Exception as e:
        log.debug("voice_assets: whisper preload failed", exc_info=True)
        return {"ok": False, "asset": "whisper", "error": str(e)}


def ensure_voice_assets() -> Dict[str, Any]:
    """Ensure both STT (whisper) and TTS (piper voice) weights are present."""
    return {"piper": ensure_piper_voice(), "whisper": ensure_whisper()}


def _main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    res = ensure_voice_assets()
    ok_all = True
    for asset, r in res.items():
        if r.get("ok"):
            where = "already present" if r.get("already_present") else "downloaded"
            print(f"[OK] voice/{asset}: {where}")
        else:
            ok_all = False
            print(f"[WARN] voice/{asset}: {r.get('error', 'unavailable')}")
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(_main())
