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
