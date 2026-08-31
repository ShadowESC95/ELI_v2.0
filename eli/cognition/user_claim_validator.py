"""Post-generation validation of user-attribution claims in CHAT output.

Extends the control-path evidence validator to casual dialogue: any claim about
the user's life, habits, preferences, or past must be substantiated by the
verified evidence packet supplied to synthesis (memory hits + user turns).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set

# Sentence-level patterns: assistant attributing facts to the user.
_USER_ATTRIBUTION_RXES: List[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\byou(?:'ve| have) been through\b", re.I), "life_event"),
    (re.compile(r"\byou(?:'ve| have)? (?:had|have had) (?:a |an )?", re.I), "life_event"),
    (re.compile(r"\b(?:that|the|a) wild night\b", re.I), "life_event"),
    (re.compile(r"\byou woke up (?:late|early)\b", re.I), "life_event"),
    (re.compile(r"\byou mentioned\b", re.I), "user_fact"),
    (re.compile(r"\byou (?:said|told me|told us)\b", re.I), "user_fact"),
    (re.compile(r"\byou(?:'re| are) (?:always|usually|often|never)\b", re.I), "habit"),
    (re.compile(r"\byou (?:like|love|prefer|hate|enjoy)\b", re.I), "preference"),
    (re.compile(r"\byour (?:favourite|favorite|preferred)\b", re.I), "preference"),
    (re.compile(r"\bwhen you (?:said|mentioned|told)\b", re.I), "user_fact"),
    (re.compile(r"\byou (?:said|told me).{0,40}\blast week\b", re.I), "user_fact"),
    (re.compile(r"\bback when you\b", re.I), "life_event"),
    (re.compile(r"\byou(?:'ve| have) been (?:working|dealing|struggling)\b", re.I), "life_event"),
]

_STOP = frozenset({
    "you", "your", "you've", "have", "been", "that", "this", "what", "when",
    "with", "about", "from", "they", "them", "just", "like", "said", "told",
    "mentioned", "always", "usually", "often", "never", "wild", "night", "the",
    "and", "but", "for", "are", "was", "were", "had", "did", "not", "lot", "bit",
})

_RETRACTION = (
    "I spoke out of turn — I don't have that in verified memory, and I shouldn't "
    "have implied it. My mistake, buddy."
)

_WILD_NIGHT_BAIT_RE = re.compile(
    r"\b(?:any|got any)\s+wild\s+nights?\b|\bwild\s+nights?\s+to\s+report\b",
    re.I,
)

_USER_NEGATED_WILD_NIGHT_RE = re.compile(
    r"\b(?:don'?t|do not|never)\s+(?:have|get)\s+(?:many\s+)?wild\s+nights?\b"
    r"|\bno\s+(?:more\s+)?wild\s+nights?\b",
    re.I,
)

_CURRENT_ACTIVITY_RE = re.compile(
    r"\b(?:i(?:'m| am)|we(?:'re| are))\s+"
    r"(?:watching|reading|listening to|playing|binge(?:ing)?)\s+"
    r"(.+?)(?:[.?!]|$)",
    re.I,
)

# Assistant inventing a different show/movie/game than the user just named.
_ENTERTAINMENT_MENTION_RE = re.compile(
    r"\b(?:watching|watch(?:ed|ing)?|listening to|reading|playing|"
    r"catching up on)\s+(?:the\s+)?([a-z0-9][a-z0-9\s'\-:]{2,60})",
    re.I,
)


def _significant_tokens(text: str) -> Set[str]:
    words = re.findall(r"[a-zA-Z']{3,}", str(text or "").lower())
    return {w for w in words if w not in _STOP}


def _sentence_supported(sentence: str, evidence: str) -> bool:
    ev = str(evidence or "").lower()
    if not ev.strip():
        return False
    tokens = _significant_tokens(sentence)
    if not tokens:
        return True
    hits = sum(1 for t in tokens if t in ev)
    # Require meaningful overlap — vague life-event claims need >=2 token hits.
    needed = 2 if len(tokens) >= 2 else 1
    return hits >= needed


def _split_sentences(text: str) -> List[str]:
    parts = re.split(r"(?<=[.!?])\s+", str(text or "").strip())
    return [p.strip() for p in parts if p.strip()]


def _activity_tokens(text: str) -> Set[str]:
    words = re.findall(r"[a-z0-9]{3,}", str(text or "").lower())
    skip = _STOP | {
        "watching", "reading", "listening", "playing", "movie", "film", "show",
        "series", "episode", "season", "new", "the", "and", "for", "with",
    }
    return {w for w in words if w not in skip}


def _activities_conflict(stated: str, mentioned: str) -> bool:
    stated_t = _activity_tokens(stated)
    mentioned_t = _activity_tokens(mentioned)
    if not stated_t or not mentioned_t:
        return False
    overlap = stated_t & mentioned_t
    if overlap:
        return False
    return True


def _user_negated_wild_nights(user_input: str, recent_user_turns: Optional[List[str]] = None) -> bool:
    corpus = " ".join([str(user_input or "")] + list(recent_user_turns or []))
    return bool(_USER_NEGATED_WILD_NIGHT_RE.search(corpus))


def _extract_current_user_activity(user_input: str) -> str:
    m = _CURRENT_ACTIVITY_RE.search(str(user_input or ""))
    if not m:
        return ""
    return m.group(1).strip().rstrip(".,!? ")


def extract_current_user_activity(user_input: str) -> str:
    return _extract_current_user_activity(user_input)


def extract_user_attribution_sentences(text: str) -> List[Dict[str, str]]:
    claims: List[Dict[str, str]] = []
    for sentence in _split_sentences(text):
        for rx, kind in _USER_ATTRIBUTION_RXES:
            if rx.search(sentence):
                claims.append({"sentence": sentence, "kind": kind, "pattern": rx.pattern})
                break
    return claims


def validate_user_claims_against_evidence(
    text: Any,
    evidence: Any = "",
    *,
    user_input: str = "",
    mode: str = "strip_unsupported",
    recent_user_turns: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Validate assistant output against verified memory evidence.

    Returns dict compatible with validate_against_evidence shape:
      ok, unsafe, sanitized, violations, stats
    """
    out = str(text or "").strip()
    ev = str(evidence or "").strip()
    if user_input:
        ev = f"{ev}\n{user_input}".strip()

    if not out:
        return {
            "ok": False,
            "unsafe": True,
            "sanitized": _RETRACTION,
            "violations": [{"kind": "empty", "value": "", "reason": "no output"}],
            "stats": {"claims_total": 0, "claims_unverified": 0, "ratio": 0.0},
        }

    attributions = extract_user_attribution_sentences(out)
    violations: List[Dict[str, str]] = []
    sanitized = out
    unverified = 0

    if _WILD_NIGHT_BAIT_RE.search(out) and _user_negated_wild_nights(
            user_input, recent_user_turns):
        violations.append({
            "kind": "wild_night_bait",
            "value": "wild night follow-up",
            "reason": "user recently said they do not have wild nights",
        })
        sanitized = _RETRACTION

    _current_activity = _extract_current_user_activity(user_input)
    if _current_activity:
        for m in _ENTERTAINMENT_MENTION_RE.finditer(out):
            mentioned = str(m.group(1) or "").strip().rstrip(".,!? ")
            if mentioned and _activities_conflict(_current_activity, mentioned):
                if not _sentence_supported(m.group(0), ev):
                    violations.append({
                        "kind": "wrong_current_activity",
                        "value": mentioned[:120],
                        "reason": (
                            f"user said they are {_current_activity[:80]!r} this turn"
                        ),
                    })
                    sanitized = sanitized.replace(m.group(0), "").strip()
                    unverified += 1

    for claim in attributions:
        sentence = claim["sentence"]
        if _sentence_supported(sentence, ev):
            continue
        unverified += 1
        violations.append({
            "kind": "unverified_user_claim",
            "value": sentence[:160],
            "reason": f"user-attribution ({claim['kind']}) not substantiated in verified evidence",
        })
        if mode == "strip_unsupported":
            sanitized = sanitized.replace(sentence, "").strip()
            sanitized = re.sub(r"\n{3,}", "\n\n", sanitized).strip()

    total = len(attributions)
    ratio = (unverified / total) if total else 0.0
    unsafe = bool(unverified > 0 and (ratio >= 0.5 or not sanitized.strip()))
    if any(v.get("kind") in ("wild_night_bait", "wrong_current_activity") for v in violations):
        unsafe = True
        if not sanitized.strip() or sanitized == out:
            sanitized = _RETRACTION

    if unsafe and not sanitized.strip():
        sanitized = _RETRACTION
    elif unsafe and unverified == total:
        # Every attribution sentence was unsupported — full retraction is clearer.
        sanitized = _RETRACTION

    return {
        "ok": not violations,
        "unsafe": unsafe,
        "sanitized": sanitized.strip() or _RETRACTION,
        "violations": violations,
        "stats": {
            "claims_total": total,
            "claims_unverified": unverified,
            "ratio": ratio,
        },
    }
