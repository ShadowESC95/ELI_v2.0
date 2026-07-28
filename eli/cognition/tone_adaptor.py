"""Tone adaptor — decides the emotion ELI *expresses* and feeds every output channel.

Two independent identifiers read the emotional context, then ELI expresses a fitting
tone through words, voice and face at once:

  • **System 1 — acoustic** (`perception/voice_profile`): the user's *voice* this
    turn (arousal / valence / coarse emotion from prosody). Present only when the
    user spoke.
  • **System 2 — semantic** (`detect_text_emotion` here): the *content* of the
    conversation — what the user actually said. Always available.

`current_tone()` fuses the two into a read, maps it through a small response policy
to the register ELI should express (empathetic, not mimicry — a distressed user
gets *tender*, not *sad*), and lets an explicit user override win outright
("be comedic", "talk street"). The chosen tone drives:
  • `text_directive()`  → folded into the persona / system prompt,
  • `voice_prosody()`   → Piper params in tts_router,
  • `expression()`      → the avatar face.

Governed by ``ELI_TONE_ADAPT`` (default on). State is process-local + persisted so
an explicit override survives the session.
"""
from __future__ import annotations

import logging
import os
import re
import time
from typing import Any, Dict, Optional, Tuple

from eli.cognition import emotion_palette as _palette

log = logging.getLogger(__name__)

_OVERRIDE: Optional[str] = None          # explicit user-set tone (wins over detection)
_OVERRIDE_TS: float = 0.0


def enabled() -> bool:
    return os.environ.get("ELI_TONE_ADAPT", "1").strip().lower() not in {"0", "false", "no", "off"}


# ── System 2: semantic emotion from the conversation text ─────────────────────
# Ordered, most-specific first. Each maps a content pattern to a DETECTED emotion
# (what the user is feeling / the register they're using), not yet ELI's response.
_SEMANTIC_RULES: "list[Tuple[str, str]]" = [
    (r"\b(kill myself|end it all|want to die|self[- ]harm)\b", "sad"),   # safety-adjacent → tender response
    (r"\b(so sad|depressed|heartbroken|grieving|lost (my|someone)|miss (him|her|them))\b", "sad"),
    (r"\b(furious|livid|so angry|pissed off|fed up|sick of|hate this|infuriating)\b", "angry"),
    (r"\b(annoyed|irritating|ugh|frustrat\w+|come on|seriously\?)\b", "irritated"),
    (r"\b(lol|lmao|rofl|haha+|hehe|so funny|hilarious|joking|kidding)\b", "comedic"),
    (r"\b(amazing|incredible|can'?t wait|so excited|let'?s go+|yes+!+|woo+)\b|!{2,}", "ecstatic"),
    (r"\b(thank you so much|so happy|love (this|it)|brilliant|made my day)\b", "joyful"),
    (r"\b(confused|don'?t (get|understand)|makes no sense|lost|what do you mean)\b", "confused"),
    (r"\b(curious|wonder|how (does|do)|why does|what if|fascinat\w+|interesting)\b", "curious"),
    (r"\b(deadline|invoice|meeting|client|stakeholder|per my|regards|kindly)\b", "professional"),
    (r"\b(bro|bruh|fam|innit|deadass|no cap|lowkey|highkey|vibe|yo\b)\b", "street_smart"),
    (r"\b(chill|relax|no rush|take your time|it'?s fine|all good)\b", "calm"),
]


def detect_text_emotion(text: str) -> Tuple[Optional[str], float]:
    """System 2: coarse emotion from the user's words. (emotion|None, confidence)."""
    raw = str(text or "").lower()
    if len(raw.strip()) < 2:
        return (None, 0.0)
    for pat, emo in _SEMANTIC_RULES:
        if re.search(pat, raw):
            return (emo, 0.7)
    return (None, 0.0)


# ── System 1: acoustic (reuse voice_profile's per-turn read) ──────────────────
def detect_voice_emotion() -> Tuple[Optional[str], float]:
    """System 1: the user's voice this turn, if they spoke. (emotion|None, conf)."""
    try:
        from eli.perception import voice_profile
        t = voice_profile.get_last_tone(max_age_s=15.0) or {}
    except Exception:
        return (None, 0.0)
    emo = str(t.get("emotion") or "").strip().lower()
    conf = float(t.get("confidence") or 0.0)
    if emo and emo != "neutral" and conf > 0.0:
        return (emo, conf)
    # No categorical read → derive coarse arousal cue so a loud/animated voice still
    # nudges the tone rather than being ignored.
    arousal = float(t.get("arousal") or 0.0)
    if arousal >= 0.6:
        return ("ecstatic", min(0.5, arousal))
    return (None, 0.0)


# ── Fusion → the emotion ELI EXPRESSES (empathetic response policy) ───────────
# Detected user emotion → the register ELI should answer in. Mirroring where it
# helps rapport (playful↔playful), softening where it helps (distress→tender,
# heat→calm) — deliberate, not sycophantic.
_RESPONSE_POLICY = {
    "sad": "tender", "angry": "calm", "irritated": "calm", "confused": "curious",
    "comedic": "playful", "ecstatic": "joyful", "joyful": "happy", "curious": "curious",
    "professional": "professional", "street_smart": "street_smart", "calm": "calm",
    "happy": "happy",
}


def _fuse() -> Tuple[str, str, float]:
    """(expressed_tone, detected_emotion, confidence) from the two systems."""
    v_emo, v_conf = detect_voice_emotion()
    t_emo, t_conf = detect_text_emotion(_last_user_text())
    # Agreement boosts confidence; else take the stronger read; voice slightly favoured
    # when both present (tone of voice is a strong signal).
    if v_emo and t_emo and v_emo == t_emo:
        detected, conf = v_emo, min(0.95, v_conf + t_conf)
    elif (v_conf * 1.05) >= t_conf and v_emo:
        detected, conf = v_emo, v_conf
    elif t_emo:
        detected, conf = t_emo, t_conf
    else:
        return ("neutral", "neutral", 0.0)
    expressed = _RESPONSE_POLICY.get(detected, "neutral")
    return (expressed, detected, conf)


# ── Last-user-text side channel (set by the engine each turn) ─────────────────
_LAST_TEXT = ""


def note_user_text(text: str) -> None:
    """Engine calls this with the user's turn so System 2 has content to read."""
    global _LAST_TEXT
    _LAST_TEXT = str(text or "")


def _last_user_text() -> str:
    return _LAST_TEXT


# ── Explicit override control ─────────────────────────────────────────────────
def set_tone(name_or_phrase: str) -> Dict[str, Any]:
    """Pin the tone ELI expresses ("be comedic", "talk street"). Returns the resolved tone."""
    global _OVERRIDE, _OVERRIDE_TS
    resolved = _palette.resolve_tone(name_or_phrase) or (
        name_or_phrase if name_or_phrase in _palette.all_tones() else None)
    if not resolved:
        return {"ok": False, "error": f"no tone matches {name_or_phrase!r}",
                "available": _palette.list_tones()}
    _OVERRIDE, _OVERRIDE_TS = resolved, time.time()
    try:
        from eli.core.runtime_settings import save_settings
        save_settings({"expressed_tone": resolved})
    except Exception:
        log.debug("tone_adaptor: persist override failed", exc_info=True)
    return {"ok": True, "tone": resolved, "desc": _palette.get_tone(resolved).get("desc", "")}


def clear_tone() -> Dict[str, Any]:
    """Drop the override — back to autonomous, emotion-adaptive expression."""
    global _OVERRIDE
    _OVERRIDE = None
    try:
        from eli.core.runtime_settings import save_settings
        save_settings({"expressed_tone": ""})
    except Exception:
        log.debug("tone_adaptor: clear override persist failed", exc_info=True)
    return {"ok": True, "tone": "auto"}


def _load_override() -> Optional[str]:
    global _OVERRIDE
    if _OVERRIDE is not None:
        return _OVERRIDE
    try:
        from eli.core.runtime_settings import load_settings
        v = str((load_settings() or {}).get("expressed_tone", "")).strip()
        if v:
            _OVERRIDE = v
            return v
    except Exception:
        log.debug("tone_adaptor: override load failed", exc_info=True)
    return None


# ── The public read + the three output channels ──────────────────────────────
def current_tone() -> Dict[str, Any]:
    """The tone ELI will express now: {tone, detected, source, confidence}.
    Override → 'override'; else the fused autonomous read → 'auto'; default neutral."""
    if not enabled():
        return {"tone": "neutral", "detected": "neutral", "source": "disabled", "confidence": 0.0}
    ov = _load_override()
    if ov:
        return {"tone": ov, "detected": ov, "source": "override", "confidence": 1.0}
    expressed, detected, conf = _fuse()
    return {"tone": expressed, "detected": detected, "source": "auto", "confidence": conf}


_CORE_GUARD = ("Keep your core personality exactly as it is — this shades HOW you deliver, "
               "never WHO you are; stay recognizably yourself underneath.")


def text_directive() -> str:
    """Situational tone directive folded into the system prompt. It makes ELI AWARE
    of when a different approach is more effective and shades his delivery that way —
    it does NOT overwrite his core personality (that stays fixed). Empty for neutral."""
    cur = current_tone()
    if cur["tone"] == "neutral":
        return ""
    flavour = _palette.get_tone(cur["tone"]).get("text", "")
    if cur["source"] == "override":
        # The user explicitly asked for this register — lean in, but stay ELI underneath.
        return f"The user asked you to lean {cur['tone']}: {flavour} {_CORE_GUARD}"
    # Autonomous: frame as situational efficiency, not an emotional takeover.
    note = ""
    if cur["detected"] not in ("neutral", cur["tone"]) and cur["confidence"] >= 0.5:
        note = (f"The user seems {cur['detected']}, so a {cur['tone']} approach reads best here. ")
    return (f"{note}Shade your delivery toward: {flavour} {_CORE_GUARD} "
            f"This is situational awareness for efficiency, not a change of character.")


def voice_prosody() -> Dict[str, Any]:
    """Piper prosody params (+pitch) for the current tone — consumed by tts_router."""
    return dict(_palette.get_tone(current_tone()["tone"]).get("voice") or {})


def expression() -> str:
    """Avatar face for the current tone — consumed by the world/avatar mapper."""
    return str(_palette.get_tone(current_tone()["tone"]).get("expression") or "neutral")
