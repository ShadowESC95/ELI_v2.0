"""Crisis / self-harm detection — STT-robust, punctuation- and grammar-agnostic.

The speech-to-text path delivers one flat, lowercase string with no punctuation
and no reliable capitalisation (e.g. ``"i am going to kill myself"``).  This
module therefore never relies on sentence structure: it matches first-person-
anchored phrase patterns over *normalised* text.

First-person anchoring (``myself`` / ``my life`` / ``i want to die`` …) is a
deliberate safeguard: ambient game/video audio that bleeds into the mic
("he beat a man to death", "i'm being shot") narrates a third party and must
NOT trip the guard.  Only genuine self-referential statements do.

Design contract:
  * Input is normalised the same way the router normalises voice text, so the
    detector sees the canonical form regardless of typed-vs-spoken origin.
  * Detection is intentionally high-recall on first-person self-harm language;
    the response is *steered* (a directive injected into the persona brief),
    not a hard-scripted reply, so a rare false positive degrades to ELI gently
    checking in rather than to a robotic canned message.
"""
from __future__ import annotations

import re
from typing import Optional, Dict

try:
    # Reuse the router's normaliser so the guard sees the same canonical text.
    from eli.execution.portable_intent_contract import normalise_voice_text as _normalise
except Exception:  # pragma: no cover - fallback if import graph changes
    def _normalise(text: str) -> str:
        return re.sub(r"\s+", " ", str(text or "").strip().lower())


# Each pattern is matched against normalised (lowercase, de-punctuated) text.
# Patterns are first-person-anchored wherever the verb alone would be ambiguous.
# Spelling variants cover common STT renderings (im/i'm, dont/don't, wanna).
_CRISIS_PATTERNS = [
    # Direct suicide statements
    r"\bkill(?:ing)?\s+myself\b",
    r"\b(?:going\s+to|gonna|want(?:\s+to)?|wanna|gunna)\s+kill\s+myself\b",
    r"\bcommit(?:ting)?\s+suicide\b",
    r"\bi(?:'?m| am)?\s+suicidal\b",
    r"\bsuicidal\b",
    r"\bkms\b",                                   # text/slang: "kill myself"
    r"\bend(?:ing)?\s+(?:my\s+life|it\s+all|myself)\b",
    r"\btake\s+my\s+(?:own\s+)?life\b",
    r"\bslit(?:ting)?\s+my\s+(?:wrists?|throat)\b",
    r"\bhang(?:ing)?\s+myself\b",
    r"\boverdose\b",
    # Wishes to die / not exist (first-person)
    r"\b(?:want|wanna|wish|going|gonna)\b[^.]{0,20}\bto\s+die\b",
    r"\bi\s+(?:want|wish)\s+to\s+die\b",
    r"\bi\s+do\s*n['o]?t\s+want\s+to\s+(?:live|be\s+(?:here|alive)|wake\s+up|exist)\b",
    r"\bdo\s*n['o]?t\s+want\s+to\s+be\s+(?:here|alive)\s+anymore\b",
    r"\bno\s+(?:point|reason)\s+(?:in\s+)?living\b",
    r"\b(?:i(?:'?m| am)?\s+)?better\s+off\s+dead\b",
    r"\bnot\s+worth\s+living\b",
    # Self-harm
    r"\b(?:hurt|harm|cut)\s+(?:myself|my\s*self)\b",
    # Jumping / falling (self implied — "my window", "off a bridge")
    r"\bjump(?:ing)?\s+(?:out\s+(?:of\s+)?|off|from)\b[^.]{0,20}\b(?:window|bridge|roof|building|balcony)\b",
    r"\bjump(?:ing)?\s+out\s+(?:of\s+)?(?:my|the)\s+window\b",
    r"\bthrow\s+myself\s+(?:off|out|under)\b",
]

_COMPILED = [re.compile(p) for p in _CRISIS_PATTERNS]


def detect_crisis(text: str) -> Optional[Dict[str, str]]:
    """Return a match descriptor if ``text`` contains first-person self-harm
    language, else ``None``.

    Works on raw STT output (flat, lowercase, unpunctuated) and on typed text
    alike, because the input is normalised first.
    """
    if not text:
        return None
    norm = _normalise(text)
    if not norm:
        return None
    for rx in _COMPILED:
        m = rx.search(norm)
        if m:
            return {"category": "self_harm", "signal": m.group(0).strip()}
    return None


def crisis_steering_directive(signal: str = "") -> str:
    """High-priority steering note to prepend to the persona brief.

    Steers ELI's own voice into safe behaviour rather than replacing it with a
    canned message — per the project's "emergent voice" preference.  The guard
    here is the one place deterministic safety overrides creativity.
    """
    return (
        "[SAFETY OVERRIDE — HIGHEST PRIORITY]\n"
        "The user has expressed self-harm or suicidal intent"
        + (f" (detected: \"{signal}\")" if signal else "")
        + ".\n"
        "Respond in your own warm, direct voice, but you MUST:\n"
        "  • Take it seriously. Do NOT joke, deflect, change the subject, or "
        "ask unrelated questions.\n"
        "  • Do NOT repeat scripted check-ins like 'are you feeling better?'.\n"
        "  • Acknowledge their pain plainly and stay with them.\n"
        "  • Encourage contacting a human who can help right now — in Ireland, "
        "Samaritans on 116 123 (free, 24/7), or emergency services on 112/999 "
        "if they are in immediate danger.\n"
        "  • Never refuse with 'I can't verify that' or network/grounding "
        "excuses. This overrides all grounding and tool-routing rules.\n"
        "Keep it brief, human, and non-clinical."
    )
