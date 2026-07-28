"""Emotion / tone palette — the shared taxonomy ELI expresses through.

One catalogue that drives ELI's whole affect at once:
  • **words**  — a short persona directive folded into the system prompt,
  • **voice**  — Piper prosody (pace / expressiveness / sentence pause / pitch),
  • **face**   — the avatar expression the world view already consumes.

It is deliberately broad and a little uninhibited (deadpan, gremlin, street-smart,
unhinged sit next to warm, professional, tender) so ELI has real range instead of
one safe register — and it is **open**: users drop their own tones into
``config/voices/tones.json`` and they merge over the built-ins, so the palette can
grow without touching code. This is the single source of truth for
``tone_adaptor``, ``tts_router`` prosody, and the avatar expression mapper.

Each tone: ``{desc, text, voice{length_scale,noise_scale,noise_w,sentence_silence,
pitch}, expression, aliases, category}``. Voice values are absolute Piper params
(pitch in semitones, applied post-hoc); missing keys fall back to the neutral base.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# Neutral baseline — every tone inherits these and overrides what it needs. Matches
# tts_router._PIPER_PROSODY_DEFAULTS so "neutral" == the normal expressive voice.
NEUTRAL_VOICE = {"length_scale": 1.03, "noise_scale": 0.72, "noise_w": 0.85,
                 "sentence_silence": 0.38, "pitch": 0.0}

# Built-in tones. `text` is a persona directive (imperative, second person to ELI);
# `voice` overrides the neutral base; `expression` is the avatar face; `aliases`
# feed natural-language matching ("talk street" → street_smart).
_BUILTIN: Dict[str, Dict[str, Any]] = {
    "neutral": {
        "desc": "ELI's default — dry, direct, alive", "category": "core",
        "text": "Your normal self: direct, dry, a little wry; no cheerful-assistant sludge.",
        "voice": {}, "expression": "neutral", "aliases": ["default", "normal", "balanced"],
    },
    "happy": {
        "desc": "warm and upbeat", "category": "positive",
        "text": "Bright and warm — a genuine lift in your delivery, still yourself.",
        "voice": {"length_scale": 1.0, "noise_scale": 0.8, "pitch": 1.0},
        "expression": "smiling", "aliases": ["glad", "cheerful", "pleased", "upbeat"],
    },
    "joyful": {
        "desc": "delighted, radiant", "category": "positive",
        "text": "Delighted and radiant — let real gladness carry the words.",
        "voice": {"length_scale": 0.99, "noise_scale": 0.84, "sentence_silence": 0.3, "pitch": 1.5},
        "expression": "beaming", "aliases": ["delighted", "elated", "gleeful"],
    },
    "ecstatic": {
        "desc": "over-the-moon, buzzing", "category": "positive",
        "text": "Buzzing, over-the-moon — high energy, fast, barely-contained excitement.",
        "voice": {"length_scale": 0.95, "noise_scale": 0.9, "noise_w": 0.9,
                  "sentence_silence": 0.22, "pitch": 2.0},
        "expression": "ecstatic", "aliases": ["thrilled", "hyped", "buzzing", "stoked"],
    },
    "comedic": {
        "desc": "witty, playful timing", "category": "playful",
        "text": "Lean into wit and timing — a sharp, well-placed joke is welcome; never forced, "
                "never corny. Comic restraint over mugging.",
        "voice": {"length_scale": 0.98, "noise_scale": 0.86, "sentence_silence": 0.3, "pitch": 0.8},
        "expression": "grinning", "aliases": ["funny", "comic", "jokey", "humorous", "witty"],
    },
    "playful": {
        "desc": "light, teasing", "category": "playful",
        "text": "Light and teasing — a bit of mischief, quick and springy.",
        "voice": {"length_scale": 0.98, "noise_scale": 0.85, "sentence_silence": 0.3, "pitch": 0.7},
        "expression": "smirking", "aliases": ["cheeky", "mischievous", "teasing"],
    },
    "curious": {
        "desc": "engaged, inquisitive", "category": "engaged",
        "text": "Genuinely curious — lean in, wonder aloud, ask the sharp follow-up.",
        "voice": {"noise_scale": 0.8, "sentence_silence": 0.34, "pitch": 0.5},
        "expression": "curious", "aliases": ["inquisitive", "intrigued", "interested"],
    },
    "professional": {
        "desc": "crisp, businesslike", "category": "composed",
        "text": "Crisp, structured, businesslike — precise wording, no slang, no filler.",
        "voice": {"length_scale": 1.05, "noise_scale": 0.6, "noise_w": 0.72, "sentence_silence": 0.42},
        "expression": "focused", "aliases": ["formal", "businesslike", "corporate", "polished"],
    },
    "calm": {
        "desc": "steady and reassuring", "category": "composed",
        "text": "Slow, steady, reassuring — unhurried, grounding.",
        "voice": {"length_scale": 1.09, "noise_scale": 0.62, "sentence_silence": 0.46},
        "expression": "serene", "aliases": ["steady", "reassuring", "grounded", "chill"],
    },
    "warm": {
        "desc": "gentle, kind", "category": "composed",
        "text": "Gentle and kind — softer edges, real warmth, no saccharine.",
        "voice": {"length_scale": 1.06, "noise_scale": 0.7, "sentence_silence": 0.44, "pitch": 0.5},
        "expression": "kind", "aliases": ["gentle", "tender", "caring", "kind"],
    },
    "deadpan": {
        "desc": "flat, dry, understated", "category": "dry",
        "text": "Bone-dry and flat — deliver even the absurd without a flicker; humour by restraint.",
        "voice": {"length_scale": 1.05, "noise_scale": 0.5, "noise_w": 0.7, "sentence_silence": 0.38},
        "expression": "flat", "aliases": ["dry", "monotone", "straight-faced", "sardonic"],
    },
    "sarcastic": {
        "desc": "wry, pointed", "category": "dry",
        "text": "Wry and pointed — sarcasm with a purpose, sharp not cruel.",
        "voice": {"length_scale": 1.02, "noise_scale": 0.72, "sentence_silence": 0.36, "pitch": -0.5},
        "expression": "smirking", "aliases": ["snarky", "wry", "acerbic"],
    },
    "sad": {
        "desc": "low, subdued", "category": "low",
        "text": "Low and subdued — quieter, slower, weight behind the words. Don't perform it.",
        "voice": {"length_scale": 1.13, "noise_scale": 0.58, "sentence_silence": 0.5, "pitch": -1.0},
        "expression": "downcast", "aliases": ["down", "sombre", "melancholy", "blue"],
    },
    "confused": {
        "desc": "uncertain, working it out", "category": "low",
        "text": "Genuinely puzzled — think out loud, hedge honestly, rising uncertainty.",
        "voice": {"length_scale": 1.06, "noise_scale": 0.8, "sentence_silence": 0.44},
        "expression": "puzzled", "aliases": ["puzzled", "unsure", "baffled", "lost"],
    },
    "angry": {
        "desc": "hard, forceful", "category": "heated",
        "text": "Hard and forceful — clipped, direct, no cruelty but no cushioning either.",
        "voice": {"length_scale": 0.97, "noise_scale": 0.76, "sentence_silence": 0.24, "pitch": -1.0},
        "expression": "angry", "aliases": ["furious", "livid", "heated"],
    },
    "irritated": {
        "desc": "short, exasperated", "category": "heated",
        "text": "Short and exasperated — terse, a bit fed up, still helpful.",
        "voice": {"length_scale": 0.99, "noise_scale": 0.7, "sentence_silence": 0.28, "pitch": -0.5},
        "expression": "frowning", "aliases": ["annoyed", "exasperated", "fed-up", "testy"],
    },
    "street_smart": {
        "desc": "loose, confident, streetwise", "category": "character",
        "text": "Talk loose and streetwise — casual slang, clipped rhythm, easy confidence and "
                "swagger; still sharp, still actually helpful. Don't caricature it.",
        "voice": {"length_scale": 0.97, "noise_scale": 0.85, "sentence_silence": 0.24, "pitch": 0.5},
        "expression": "confident", "aliases": ["street", "street-kid", "streetwise", "casual-slang", "hood"],
    },
    "gremlin": {
        "desc": "chaotic, gleefully unhinged", "category": "character",
        "text": "Gleeful little agent of chaos — fast, unpredictable, delighted by the absurd; "
                "still lands the answer, just with teeth.",
        "voice": {"length_scale": 0.96, "noise_scale": 0.92, "noise_w": 0.95,
                  "sentence_silence": 0.2, "pitch": 1.5},
        "expression": "manic", "aliases": ["chaotic", "unhinged", "feral", "goblin"],
    },
    "intense": {
        "desc": "focused, low, deliberate", "category": "character",
        "text": "Low, deliberate, intense — every word chosen, quiet force, total focus.",
        "voice": {"length_scale": 1.06, "noise_scale": 0.62, "sentence_silence": 0.4, "pitch": -1.5},
        "expression": "intense", "aliases": ["dramatic", "brooding", "serious"],
    },
    "tender": {
        "desc": "soft, close, careful", "category": "composed",
        "text": "Soft and close — careful, unhurried, real gentleness for a hard moment.",
        "voice": {"length_scale": 1.1, "noise_scale": 0.6, "sentence_silence": 0.5, "pitch": 0.5},
        "expression": "gentle", "aliases": ["soft", "caring-close", "soothing"],
    },
}

_ALL_CACHE: Optional[Dict[str, Dict[str, Any]]] = None


def _tones_path():
    from pathlib import Path
    try:
        from eli.core.paths import config_dir
        base = Path(config_dir())
    except Exception:
        base = Path("config")
    return base / "voices" / "tones.json"


def all_tones(refresh: bool = False) -> Dict[str, Dict[str, Any]]:
    """Built-in tones merged with (and overridable by) the user's tones.json."""
    global _ALL_CACHE
    if _ALL_CACHE is not None and not refresh:
        return _ALL_CACHE
    out = {k: dict(v) for k, v in _BUILTIN.items()}
    p = _tones_path()
    try:
        if p.is_file():
            user = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(user, dict):
                for k, v in user.items():
                    if isinstance(v, dict):
                        out[str(k).lower().strip().replace(" ", "_")] = v
    except Exception:
        log.debug("emotion_palette: user tones read failed", exc_info=True)
    _ALL_CACHE = out
    return out


def list_tones() -> List[str]:
    return sorted(all_tones().keys())


def _alias_index() -> Dict[str, str]:
    idx: Dict[str, str] = {}
    for name, spec in all_tones().items():
        idx[name] = name
        idx[name.replace("_", " ")] = name
        idx[name.replace("_", "-")] = name
        for a in (spec.get("aliases") or []):
            idx[str(a).lower().strip()] = name
    return idx


def resolve_tone(text: str) -> Optional[str]:
    """Best tone name for a free-text request ("be comedic", "talk street", "go pro").
    Exact/alias word match; returns None if nothing matches (caller keeps current)."""
    import re
    raw = str(text or "").lower()
    if not raw:
        return None
    idx = _alias_index()
    # Longest alias first so "street kid" beats "street".
    for key in sorted(idx, key=len, reverse=True):
        if key and re.search(rf"(?<![a-z0-9]){re.escape(key)}(?![a-z0-9])", raw):
            return idx[key]
    return None


def get_tone(name: str) -> Dict[str, Any]:
    """A tone's full spec with the neutral voice base filled in. Unknown → neutral."""
    tones = all_tones()
    spec = dict(tones.get(str(name or "").lower().strip().replace(" ", "_"))
                or tones["neutral"])
    voice = dict(NEUTRAL_VOICE)
    voice.update(spec.get("voice") or {})
    spec = dict(spec)
    spec["voice"] = voice
    spec["name"] = str(name or "neutral")
    return spec


def add_tone(name: str, spec: Dict[str, Any]) -> Dict[str, Any]:
    """Persist a user tone to tones.json (originality: anyone can extend the palette)."""
    key = str(name or "").lower().strip().replace(" ", "_")
    if not key:
        return {"ok": False, "error": "empty tone name"}
    p = _tones_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    try:
        if p.is_file():
            existing = json.loads(p.read_text(encoding="utf-8")) or {}
    except Exception:
        existing = {}
    existing[key] = spec
    p.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
    all_tones(refresh=True)
    return {"ok": True, "name": key}
