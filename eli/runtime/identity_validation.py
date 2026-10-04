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
    # Pronouns / possessives / prepositions that never form part of a real name
    "my", "by", "your", "our", "their", "his", "her",
    "i", "me", "we", "they", "he", "she",
    "is", "are", "was", "were", "be", "been", "am",
    "in", "on", "at", "to", "for", "of", "with", "from",
    "and", "or", "but", "so", "if", "then",
    # Meta-words that appear when an LLM describes rather than states a name
    "name", "named", "called", "call", "nickname",
    "preferred", "prefer", "known",
    # How a stored name is described, not a name: "my name is listed as unknown" renamed a
    # user "listed".
    "listed", "stored", "saved", "shown", "displayed", "recorded", "written", "spelled",
    "spelt", "set", "missing", "blank", "empty", "wrong", "correct", "incorrect", "different",
    "changed", "gone", "lost", "fine", "ok", "okay", "here", "there", "now", "still",
    "already", "also", "just", "actually", "really", "literally", "obviously", "clearly",
    "definitely", "never", "fucking", "fuckin", "bloody", "damn", "effing",
}

# Imperative command verbs. A captured name almost never opens with one (a session logged
# "pause spotify" as the user's name, so every self-report greeted them that way). A multi-word
# candidate whose first word is a command verb is a command, not a name. Single-word overlaps
# (the name "Mark") are left alone, this only fires on verb + object.
_COMMAND_VERBS = frozenset({
    "pause", "play", "resume", "stop", "skip", "next", "previous", "rewind",
    "open", "close", "launch", "start", "quit", "exit", "run", "execute",
    "mute", "unmute", "turn", "set", "show", "hide", "toggle", "switch",
    "tell", "give", "make", "create", "delete", "remove", "add", "send",
    "search", "find", "go", "put", "take", "get", "download", "install",
    "increase", "decrease", "raise", "lower", "volume", "brightness",
})

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
    # "pause spotify" / "open chrome": a multi-word candidate that opens with an
    # imperative command verb is a command, not a name.
    if len(words) > 1 and words[0].lower() in _COMMAND_VERBS:
        return ""

    return candidate


def is_valid_identity_candidate(value: Any, *, max_words: int = 3) -> bool:
    return bool(normalize_identity_candidate(value, max_words=max_words))


# A name ends at punctuation or at a word that starts the next clause ("my name is sam and i...").
_NAME_END = (r"\s+(?:and|but|btw|by\s+the\s+way|nice|pleased|from|i|i'm|im|please|thanks|"
             r"thank|instead|now|going|ok|okay|eli)\b")

# "If my name is listed as unknown, ..." talks about a name; it doesn't give one.
_HYPOTHETICAL_LEAD_RE = re.compile(
    r"\b(?:if|whether|unless|suppose|supposing|assuming|imagine|pretend|as\s+though|as\s+if)\b"
    r"[^,.;!?]{0,30}$", re.I)
_DECLARATION_RE = re.compile(
    r"\b(?:my\s+(?:preferred\s+)?name\s+is|my\s+nickname\s+is|call\s+me|i\s+go\s+by|"
    r"i\s+prefer\s+to\s+be\s+called)\b", re.I)


def _drop_hypothetical_clauses(raw: str) -> str:
    """Blank out any name declaration that sits inside an if/whether clause."""
    out, last = [], 0
    for m in _DECLARATION_RE.finditer(raw):
        if _HYPOTHETICAL_LEAD_RE.search(raw[max(0, m.start() - 40):m.start()]):
            end = re.search(r"[,.;!?]|$", raw[m.end():])
            stop = m.end() + (end.start() if end else 0)
            out.append(raw[last:m.start()])
            out.append(" " * (stop - m.start()))
            last = stop
    out.append(raw[last:])
    return "".join(out)


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
    raw = _drop_hypothetical_clauses(raw)

    # Unambiguous self-declarations only.
    patterns: tuple[tuple[str, str], ...] = (
        ("name", r"\bmy\s+name\s+is\s+([A-Za-z][A-Za-z .'\-]{1,48}?)(?=\s*$|\s*[.!?,;]|" + _NAME_END + r")"),
        ("preferred_name", r"\bmy\s+preferred\s+name\s+is\s+([A-Za-z][A-Za-z .'\-]{1,48}?)(?=\s*$|\s*[.!?,;]|" + _NAME_END + r")"),
        ("preferred_name", r"\bi\s+prefer\s+to\s+be\s+called\s+([A-Za-z][A-Za-z .'\-]{1,48}?)(?=\s*$|\s*[.!?,;]|" + _NAME_END + r")"),
        ("preferred_name", r"\bi\s+go\s+by\s+([A-Za-z][A-Za-z .'\-]{1,48}?)(?=\s*$|\s*[.!?,;]|" + _NAME_END + r")"),
        ("nickname", r"\bmy\s+nickname\s+is\s+([A-Za-z][A-Za-z .'\-]{1,48}?)(?=\s*$|\s*[.!?,;]|" + _NAME_END + r")"),
        ("nickname", r"\bnickname\s+is\s+([A-Za-z][A-Za-z .'\-]{1,48}?)(?=\s*$|\s*[.!?,;]|" + _NAME_END + r")"),
    )

    facts: Dict[str, str] = {}
    for key, pattern in patterns:
        match = re.search(pattern, raw, flags=re.I)
        if not match:
            continue
        value = normalize_identity_candidate(match.group(1))
        if value and key not in facts:
            facts[key] = value

    # "call me X" is the one ambiguous declarer: it also matches questions and complaints ("why
    # did you call me X", "you called me X", "don't/stop call me X"). Accept it as a
    # preferred-name declaration only as a genuine first-person imperative, never from a question,
    # reference or negation.
    if "preferred_name" not in facts:
        _call_me_is_declaration = not re.search(
            r"\b(?:you|why|what|when|who|how|did|do|does|never|didn'?t|don'?t|"
            r"do\s*not|did\s*not|stop|stopped|quit|cannot|can'?t|not)\b[^.?!]*"
            r"\bcall(?:ed|ing)?\s+me\b",
            low,
        )
        if _call_me_is_declaration:
            _m = re.search(r"\bcall\s+me\s+([A-Za-z][A-Za-z .'\-]{1,48}?)(?=\s*$|\s*[.!?,;]|" + _NAME_END + r")", raw, flags=re.I)
            if _m:
                _v = normalize_identity_candidate(_m.group(1))
                if _v:
                    facts["preferred_name"] = _v
    return facts
