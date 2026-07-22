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

import hashlib
import json
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Any, Dict

log = logging.getLogger(__name__)

# Default Piper voice to fetch when the box has none. Hosted on rhasspy/piper-voices.
# (This is the same default tts_router falls back to: en_US-amy-medium.)
_PIPER_VOICE = "en_US-amy-medium"
_PIPER_BASE = ("https://huggingface.co/rhasspy/piper-voices/resolve/main/"
               "en/en_US/amy/medium/")

# ── Voice catalog ───────────────────────────────────────────────────────────────
# Upstream publishes an index of every voice it hosts (166 voices / 45 languages
# at time of writing) with exact file paths, sizes and md5 digests. Fetching it
# beats hardcoding voice ids: the user gets every accent/quality upstream offers,
# downloads are checksum-verified, and the list can never drift out of date.
# The curated PIPER_CATALOG below stays as the offline fallback + "recommended".
_INDEX_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/voices.json"
_INDEX_FILENAME = "voices.index.json"
_INDEX_MAX_AGE_S = 7 * 24 * 3600

# Voices ELI does NOT redistribute, keyed by voice NAME so every quality variant
# is covered (the licence attaches to the dataset, not to one .onnx):
#   ryan   — CC-BY-NC-SA 4.0 (non-commercial: incompatible with a shipped product)
#   lessac — Blizzard/Lessac dataset, redistribution not cleared
#   cori   — clearance pending review
# A user may still download these for their own personal use; we simply never
# put them in a release asset. scripts/asset_release_policy.py mirrors this set.
RESTRICTED_VOICE_NAMES = frozenset({"ryan", "lessac", "cori"})

PIPER_CATALOG: Dict[str, Dict[str, str]] = {
    # Standard — clean, neutral, "robotic-normal"
    "en_US-amy-medium":        {"tier": "standard", "desc": "Amy (US female) — default, clear",      "license": "MIT"},
    "en_US-hfc_female-medium": {"tier": "standard", "desc": "HFC female (US) — neutral, crisp",       "license": "MIT"},
    "en_US-hfc_male-medium":   {"tier": "standard", "desc": "HFC male (US) — neutral, even",          "license": "MIT"},
    "en_US-joe-medium":        {"tier": "standard", "desc": "Joe (US male) — calm, steady",           "license": "MIT"},
    "en_US-kathleen-low":      {"tier": "standard", "desc": "Kathleen (US female) — light, quick",    "license": "MIT"},
    # Advanced — higher fidelity / more character
    "en_US-lessac-high":       {"tier": "advanced", "desc": "Lessac (US male) — high fidelity, smooth","license": "Blizzard/Lessac (uncleared)"},
    "en_US-lessac-medium":     {"tier": "advanced", "desc": "Lessac (US male) — smooth, warm",        "license": "Blizzard/Lessac (uncleared)"},
    "en_GB-alan-medium":       {"tier": "advanced", "desc": "Alan (UK male) — refined British",       "license": "OS"},
    "en_GB-northern_english_male-medium": {"tier": "advanced", "desc": "Northern English male — characterful", "license": "OS"},
    "en_US-kusal-medium":      {"tier": "advanced", "desc": "Kusal (US male) — expressive",           "license": "MIT"},
    # NC-SA — never auto-bundled into a release
    "en_US-ryan-high":         {"tier": "advanced", "desc": "Ryan (US male) — very natural (NC-SA)",  "license": "CC-BY-NC-SA"},
}


def voice_name_of(voice_id: str) -> str:
    """'en_GB-northern_english_male-medium' -> 'northern_english_male'."""
    parts = str(voice_id or "").split("-")
    return "-".join(parts[1:-1]) if len(parts) >= 3 else ""


def is_restricted(voice_id: str) -> bool:
    """True when ELI must not redistribute this voice (user may still fetch it)."""
    return voice_name_of(voice_id) in RESTRICTED_VOICE_NAMES


def _index_cache_path() -> Path:
    return _piper_dest() / _INDEX_FILENAME


def voice_index(refresh: bool = False) -> Dict[str, Any]:
    """The upstream voice index, cached on disk. Offline-safe: returns the cached
    copy (or {} if never fetched) without touching the network unless asked."""
    cache = _index_cache_path()
    if not refresh:
        try:
            if cache.is_file() and cache.stat().st_size > 0:
                return json.loads(cache.read_text(encoding="utf-8"))
        except Exception:
            log.debug("voice_assets: cached index unreadable", exc_info=True)
    return {}


def fetch_voice_index(force: bool = False) -> Dict[str, Any]:
    """Download (and cache) the upstream voice index. Netguard-gated. Falls back to
    the cached copy on any failure so a picker still works offline."""
    cache = _index_cache_path()
    try:
        fresh_enough = (cache.is_file() and cache.stat().st_size > 0
                        and (time.time() - cache.stat().st_mtime) < _INDEX_MAX_AGE_S)
    except OSError:
        fresh_enough = False
    if fresh_enough and not force:
        return voice_index()
    try:
        import urllib.request
        from eli.core import netguard
        with netguard.allow_network("voice asset: piper voice index"):
            req = urllib.request.Request(
                _INDEX_URL, headers={"User-Agent": "ELI/2.0 (voice-assets)"})
            with netguard.guarded_urlopen(req, timeout=60) as r:
                raw = r.read()
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict) or not data:
            raise ValueError("empty or malformed voice index")
        cache.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache.with_suffix(cache.suffix + ".part")
        tmp.write_bytes(raw)
        tmp.replace(cache)
        return data
    except Exception:
        log.debug("voice_assets: voice index fetch failed (using cache)", exc_info=True)
        return voice_index()


def _index_files(voice_id: str, index: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """The {relative_path: {size_bytes, md5_digest}} map for a voice, if indexed."""
    entry = index.get(voice_id) or {}
    files = entry.get("files") or {}
    return files if isinstance(files, dict) else {}


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
        dest.mkdir(parents=True, exist_ok=True)
        import urllib.request
        from eli.core import netguard
        # Prefer the upstream index: it gives the exact repo-relative path (voices
        # whose folder isn't derivable from the id, e.g. multi-speaker ones) and an
        # md5 per file so a truncated or proxy-mangled download is caught here
        # rather than surfacing later as a corrupt-model crash.
        index = voice_index() or fetch_voice_index()
        indexed = _index_files(voice_id, index)
        if indexed:
            jobs = [(Path(rel).name, _INDEX_URL.rsplit("/", 1)[0] + "/" + rel,
                     str((meta or {}).get("md5_digest") or ""))
                    for rel, meta in indexed.items()
                    if Path(rel).name.endswith((".onnx", ".onnx.json"))]
        else:
            base = _voice_url_base(voice_id)
            jobs = [(fn, base + fn, "") for fn in (f"{voice_id}.onnx", f"{voice_id}.onnx.json")]
        with netguard.allow_network(f"voice asset: piper {voice_id}"):
            for fn, url, want_md5 in jobs:
                target = dest / fn
                if target.exists() and target.stat().st_size > 0:
                    continue
                req = urllib.request.Request(url,
                                             headers={"User-Agent": "ELI/2.0 (voice-assets)"})
                tmp = target.with_suffix(target.suffix + ".part")
                digest = hashlib.md5()
                with netguard.guarded_urlopen(req, timeout=300) as r, open(tmp, "wb") as fh:
                    while True:
                        chunk = r.read(1 << 20)
                        if not chunk:
                            break
                        digest.update(chunk)
                        fh.write(chunk)
                if tmp.stat().st_size <= 0:
                    tmp.unlink(missing_ok=True)
                    return {"ok": False, "asset": "piper", "voice": voice_id,
                            "error": f"empty download: {fn}"}
                if want_md5 and digest.hexdigest() != want_md5:
                    tmp.unlink(missing_ok=True)
                    return {"ok": False, "asset": "piper", "voice": voice_id,
                            "error": f"checksum mismatch: {fn}"}
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


def list_available_voices(language: str = "", installed_only: bool = False,
                          refresh: bool = False) -> "list[Dict[str, Any]]":
    """Every voice obtainable on this box, annotated for a picker.

    Sourced from the upstream index when available (all languages/accents/qualities),
    else the curated catalog. ``language`` filters on family or locale ('en',
    'en_GB'). Each row carries ``present`` (installed), ``restricted`` (ELI won't
    redistribute it — user may still download it) and ``size_mb`` so a UI can warn
    before a 60 MB fetch. Pure-local unless ``refresh`` is set.
    """
    index = fetch_voice_index() if refresh else (voice_index() or {})
    rows: "list[Dict[str, Any]]" = []
    if index:
        for vid, entry in index.items():
            lang = (entry or {}).get("language") or {}
            code = str(lang.get("code") or "")
            if language and not (code == language or lang.get("family") == language
                                 or code.startswith(f"{language}_")):
                continue
            size = sum(int((m or {}).get("size_bytes") or 0)
                       for p, m in ((entry or {}).get("files") or {}).items()
                       if str(p).endswith(".onnx"))
            curated = PIPER_CATALOG.get(vid, {})
            rows.append({
                "id": vid,
                "name": entry.get("name") or voice_name_of(vid),
                "language": code,
                "language_name": lang.get("name_english") or "",
                "country": lang.get("country_english") or "",
                "quality": entry.get("quality") or "",
                "size_mb": round(size / (1 << 20), 1) if size else 0.0,
                "present": _voice_present_strict(vid),
                "restricted": is_restricted(vid),
                "recommended": vid in PIPER_CATALOG,
                "tier": curated.get("tier", ""),
                "desc": curated.get("desc", ""),
                "license": curated.get("license", ""),
            })
    else:  # offline and never fetched — curated list is better than nothing
        for vid, meta in PIPER_CATALOG.items():
            if language and not vid.startswith(language):
                continue
            rows.append({"id": vid, "name": voice_name_of(vid), "language": vid.split("-")[0],
                         "language_name": "", "country": "", "quality": vid.split("-")[-1],
                         "size_mb": 0.0, "present": _voice_present_strict(vid),
                         "restricted": is_restricted(vid), "recommended": True, **meta})
    if installed_only:
        rows = [r for r in rows if r["present"]]
    rows.sort(key=lambda r: (not r["recommended"], r["id"]))
    return rows


def incomplete_voices(search_dirs: "list[Path] | None" = None) -> "list[Dict[str, Any]]":
    """Voices whose ``.onnx`` is on disk but whose ``.onnx.json`` config is not.

    Piper cannot load a model without its config, so such a voice is invisible to
    ``tts_router.list_voices()`` — it silently occupies ~60 MB while being unusable.
    The config is ~5 KB, so repairing is cheap where re-downloading the model isn't.
    """
    dirs = [Path(d) for d in (search_dirs or [])] or [_piper_dest()]
    try:
        from eli.core.paths import project_root
        packaged = Path(project_root()) / "tts_piper" / "piper"
        if not search_dirs and packaged.is_dir():
            dirs.append(packaged)
    except Exception:
        log.debug("voice_assets: packaged dir probe failed", exc_info=True)
    out: "list[Dict[str, Any]]" = []
    seen: set = set()
    for d in dirs:
        try:
            for onnx in sorted(Path(d).glob("*.onnx")):
                cfg = Path(str(onnx) + ".json")
                key = (str(d), onnx.stem)
                if not cfg.is_file() and key not in seen:
                    seen.add(key)
                    out.append({"voice": onnx.stem, "dir": str(d), "onnx": str(onnx)})
        except Exception:
            log.debug("voice_assets: scan of %s failed", d, exc_info=True)
    return out


def repair_voice_configs(mirror: bool = True) -> Dict[str, Any]:
    """Fetch the missing ``.onnx.json`` for every incomplete voice on disk.

    Netguard-gated and idempotent; returns per-voice results. This makes voices
    that were shipped/downloaded without their config usable instead of dead weight.
    """
    broken = incomplete_voices()
    if not broken:
        return {"ok": True, "repaired": [], "failed": [], "already_complete": True}
    repaired, failed = [], []
    # One fetch per voice — the same voice is commonly incomplete in BOTH the
    # models/ and packaged tts_piper/ layouts, and the mirror covers the second.
    for vid in sorted({str(item["voice"]) for item in broken}):
        res = download_voice(vid, mirror=mirror)
        (repaired if res.get("ok") else failed).append(
            vid if res.get("ok") else {"voice": vid, "error": res.get("error")})
    return {"ok": not failed, "repaired": repaired, "failed": failed}


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
