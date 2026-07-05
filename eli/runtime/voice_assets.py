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


def _piper_present() -> bool:
    try:
        from eli.perception import tts_router
        return bool(tts_router.list_voices())
    except Exception:
        log.debug("voice_assets: piper presence check failed", exc_info=True)
        return False


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


def ensure_piper_voice() -> Dict[str, Any]:
    """Fetch the default Piper voice (``.onnx`` + ``.onnx.json``) if no voice exists."""
    if _piper_present():
        _mirror_piper_to_packaged_layout(_PIPER_VOICE)
        return {"ok": True, "asset": "piper", "already_present": True, "voice": _PIPER_VOICE}
    dest = _piper_dest()
    try:
        dest.mkdir(parents=True, exist_ok=True)
        import urllib.request
        from eli.core import netguard
        with netguard.allow_network("voice asset: piper voice"):
            for fn in (f"{_PIPER_VOICE}.onnx", f"{_PIPER_VOICE}.onnx.json"):
                target = dest / fn
                if target.exists() and target.stat().st_size > 0:
                    continue
                req = urllib.request.Request(_PIPER_BASE + fn,
                                             headers={"User-Agent": "ELI/2.0 (voice-assets)"})
                with netguard.guarded_urlopen(req, timeout=180) as r:
                    data = r.read()
                if not data:
                    return {"ok": False, "asset": "piper", "error": f"empty download: {fn}"}
                tmp = target.with_suffix(target.suffix + ".part")
                tmp.write_bytes(data)
                tmp.replace(target)
        _mirror_piper_to_packaged_layout(_PIPER_VOICE)
        return {"ok": True, "asset": "piper", "already_present": False, "voice": _PIPER_VOICE}
    except Exception as e:
        log.debug("voice_assets: piper fetch failed", exc_info=True)
        return {"ok": False, "asset": "piper", "error": str(e)}


def ensure_whisper() -> Dict[str, Any]:
    """Ensure the faster-whisper STT model is cached. faster-whisper downloads it on
    first construction; force CPU so the installer claims no VRAM, and gate the fetch."""
    os.environ.setdefault("ELI_WHISPER_DEVICE", "cpu")
    try:
        from eli.core import netguard
        from eli.perception import local_whisper_stt as W
        with netguard.allow_network("voice asset: whisper model"):
            W.preload_model()  # loads from disk if present, else downloads
        present = getattr(W, "_MODEL", None) is not None
        return {"ok": present, "asset": "whisper",
                "already_present": present, **({} if present else {"error": "model not loaded"})}
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
