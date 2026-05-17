from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List


_VAGUE_DYNAMIC_STATUS_RE = re.compile(
    r"(?is)\b(?:"
    r"currently\s+being\s+processed"
    r"|being\s+processed"
    r"|processing\s+(?:some\s+)?(?:updates?|changes?|routine\s+checks?)"
    r"|still\s+(?:processing|working\s+on|incorporating)\s+(?:an?\s+)?(?:updates?|changes?)"
    r"|receiving\s+and\s+incorporating\s+new\s+information"
    r"|routine\s+check\s+to\s+ensure\s+everything\s+is\s+functioning"
    r"|confirm\s+everything\s+is\s+up\s+and\s+running"
    r"|ready\s+to\s+go\s+live"
    r"|keep\s+an\s+eye\s+on\s+it"
    r"|i(?:'| wi)ll\s+inform\s+you"
    r"|i(?:'| wi)ll\s+let\s+you\s+know"
    r")\b"
)

_IMAGE_STATUS_RE = re.compile(
    r"(?is)\b(?:image|images|picture|visual|render)\b.{0,120}\b(?:"
    r"update|processed|processing|go\s+live|ready|status|generated|job"
    r")\b"
)

_USER_CHALLENGE_RE = re.compile(
    r"(?is)\b(?:"
    r"i\s+did(?:n'?t| not)\s+ask"
    r"|not\s+what\s+i\s+asked"
    r"|stop\s+talking\s+about"
    r"|what\s+(?:the\s+)?(?:fuck|hell|heck)"
    r"|do\s+you\s+not\s+understand"
    r"|what\s+is\s+going\s+on\s+with\s+you"
    r"|what\s+is\s+happening\s+with\s+you"
    r")\b"
)

_POISONED_ASSISTANT_TURN_RE = re.compile(
    r"(?is)\b(?:"
    r"your\s+state\s+isn'?t\s+felt\s+or\s+expressed"
    r"|how\s+are\s+you\s+feeling\s+today\??"
    r"|i'?m\s+good,\s+just\s+a\s+bit\s+tired"
    r"|run-?in\s+with\s+some\s+synthetic\s+syntax"
    r"|overzealous\s+punctuation\s+checker"
    r"|artifact\s+of\s+our\s+interaction\s+protocol"
    r"|i\s+don'?t\s+have\s+information\s+about\s+a\s+person\s+named\s+eli"
    r"|you\s+may\s+need\s+to\s+ask\s+eli\s+directly"
    r")\b"
)


def is_vague_dynamic_status_claim(text: Any) -> bool:
    return bool(_VAGUE_DYNAMIC_STATUS_RE.search(str(text or "")))


def is_image_status_claim(text: Any) -> bool:
    value = str(text or "")
    return bool(_IMAGE_STATUS_RE.search(value) and _VAGUE_DYNAMIC_STATUS_RE.search(value))


def is_user_challenge(text: Any) -> bool:
    return bool(_USER_CHALLENGE_RE.search(str(text or "")))


def should_exclude_turn_from_prompt(role: Any, content: Any) -> bool:
    if str(role or "").lower() != "assistant":
        return False
    value = str(content or "")
    return bool(is_vague_dynamic_status_claim(value) or _POISONED_ASSISTANT_TURN_RE.search(value))


def recent_turn_diagnostics(turns: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    rows: List[Dict[str, str]] = []
    assistant_counts: Dict[str, int] = {}
    dynamic_status_claims: List[str] = []
    challenge_after_claim = False
    last_assistant_claim = False

    for turn in turns or []:
        role = str((turn or {}).get("role") or "").lower()
        content = re.sub(r"\s+", " ", str((turn or {}).get("content") or "")).strip()
        if not content:
            continue
        rows.append({"role": role or "unknown", "content": content[:260]})
        if role == "assistant":
            key = content.lower()
            assistant_counts[key] = assistant_counts.get(key, 0) + 1
            last_assistant_claim = is_vague_dynamic_status_claim(content)
            if last_assistant_claim:
                dynamic_status_claims.append(content[:260])
        elif role == "user" and last_assistant_claim and is_user_challenge(content):
            challenge_after_claim = True

    repeated = [
        {"text": text[:220], "count": count}
        for text, count in assistant_counts.items()
        if count > 1
    ]
    repeated.sort(key=lambda item: item["count"], reverse=True)

    return {
        "recent_turns": rows[-10:],
        "repeated_assistant_text": repeated[:5],
        "dynamic_status_claims": dynamic_status_claims[-5:],
        "challenge_after_dynamic_status_claim": challenge_after_claim,
    }
