from __future__ import annotations

import re
from typing import Any, Dict


_INVALID_SINGLE_TOKENS = {
    "",
    "a",
    "an",
    "the",
    "this",
    "that",
    "these",
    "those",
    "it",
    "its",
    "not",
    "none",
    "null",
    "unknown",
    "n/a",
    "na",
    "user",
    "username",
    "local_user",
    "assistant",
    "ai",
    "eli",
    "model",
    "artificial",
    "intelligence",
    "asking",
    "saying",
    "telling",
    "calling",
    "going",
    "trying",
    "doing",
    "working",
    "looking",
    "talking",
    "wondering",
    "thinking",
    "checking",
    "testing",
    "using",
    "getting",
    "waiting",
    "coming",
    "running",
}

_PLACEHOLDER_RE = re.compile(r"(?i)<[^>]*(?:user|name|username|local_user)[^>]*>|\[[^\]]*(?:user|name|username)[^\]]*\]")
_IDENTITY_CHARS_RE = re.compile(r"^[A-Za-z][A-Za-z .'\-]{0,48}$")


def normalize_identity_candidate(value: Any, *, max_words: int = 3) -> str:
    """
    Return a clean personal-name/nickname candidate, or "" when the value is
    a grammar fragment, placeholder, sentence, or model-generated explanation.

    This deliberately validates shape only. It does not encode any specific
    user's identity.
    """
    raw = " ".join(str(value or "").strip().split())
    if _PLACEHOLDER_RE.search(raw):
        return ""
    candidate = raw
    candidate = candidate.strip(" .,:;!?\"'`[](){}<>")
    if not candidate:
        return ""

    low = candidate.lower()
    if _PLACEHOLDER_RE.search(candidate):
        return ""
    if low in _INVALID_SINGLE_TOKENS:
        return ""
    if any(ch in candidate for ch in "\n\r\t:;?!"):
        return ""
    if "." in candidate:
        return ""
    if not _IDENTITY_CHARS_RE.match(candidate):
        return ""

    words = [w for w in re.split(r"\s+", candidate) if w]
    if not words or len(words) > max_words:
        return ""
    if any(w.lower() in _INVALID_SINGLE_TOKENS for w in words):
        return ""
    if len(words) == 1 and words[0].lower().endswith("ing") and len(words[0]) > 4:
        return ""

    return candidate


def is_valid_identity_candidate(value: Any, *, max_words: int = 3) -> bool:
    return bool(normalize_identity_candidate(value, max_words=max_words))


def extract_explicit_identity_facts(text: Any) -> Dict[str, str]:
    """
    Extract only explicit user identity declarations. Questions, broad "it is"
    phrasing, and generic "or ..." fragments are intentionally ignored.
    """
    raw = " ".join(str(text or "").strip().split())
    if not raw:
        return {}

    low = raw.lower()
    if "?" in raw and not any(x in low for x in ("my name is", "call me", "i go by", "my nickname is")):
        return {}

    patterns: tuple[tuple[str, str], ...] = (
        ("name", r"\bmy\s+name\s+is\s+([A-Za-z][A-Za-z .'\-]{1,48})(?=$|[.!?,])"),
        ("preferred_name", r"\bmy\s+preferred\s+name\s+is\s+([A-Za-z][A-Za-z .'\-]{1,48})(?=$|[.!?,])"),
        ("preferred_name", r"\bi\s+prefer\s+to\s+be\s+called\s+([A-Za-z][A-Za-z .'\-]{1,48})(?=$|[.!?,])"),
        ("preferred_name", r"\bi\s+go\s+by\s+([A-Za-z][A-Za-z .'\-]{1,48})(?=$|[.!?,])"),
        ("preferred_name", r"\bcall\s+me\s+([A-Za-z][A-Za-z .'\-]{1,48})(?=$|[.!?,])"),
        ("nickname", r"\bmy\s+nickname\s+is\s+([A-Za-z][A-Za-z .'\-]{1,48})(?=$|[.!?,])"),
        ("nickname", r"\bnickname\s+is\s+([A-Za-z][A-Za-z .'\-]{1,48})(?=$|[.!?,])"),
    )

    facts: Dict[str, str] = {}
    for key, pattern in patterns:
        match = re.search(pattern, raw, flags=re.I)
        if not match:
            continue
        value = normalize_identity_candidate(match.group(1))
        if value and key not in facts:
            facts[key] = value
    return facts
