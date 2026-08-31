"""Fail-closed CHAT gate — skip LLM when user-fact grounding is required but absent.

Complements post-generation claim validation (user_claim_validator): this path
avoids calling the model at all when verified evidence is empty and the turn
requires user-specific facts.
"""
from __future__ import annotations

import os
import re
from typing import Any, Optional

from eli.runtime.memory_provenance import is_explicit_memory_audit_query

# Kill-switch for redistribution debugging only — default ON.
_FAIL_CLOSED_ENABLED = os.environ.get("ELI_CHAT_FAIL_CLOSED", "1").strip().lower() not in (
    "0", "false", "no", "off",
)

_GROUNDING_FLOOR = float(os.environ.get("ELI_CHAT_GROUNDING_FLOOR", "0.35") or "0.35")

_PHATIC_RE = re.compile(
    r"^\s*(?:"
    r"hi\b|hey\b|hello\b|yo\b|sup\b|what(?:'?s| is) up\b|how(?:'?s| is) it going\b|"
    r"good (?:morning|afternoon|evening|night)\b|thanks\b|thank you\b|cheers\b|"
    r"ok(?:ay)?\b|got it\b|cool\b|nice\b|lol\b|haha\b"
    r")[\s!?.]*$",
    re.I,
)

_SELF_REF_USER_RE = re.compile(
    r"\b("
    r"about me|who am i|my name|what do you know about me|what do you remember about me|"
    r"what have i told you|what did i say|what were we|how am i|how have i been|"
    r"my life|my day|my night|my week|remember when i|did i tell you"
    r")\b",
    re.I,
)

_VERIFIED_BLOCK_MARKER = "Verified stored memories"


def is_phatic_turn(user_input: str) -> bool:
    text = str(user_input or "").strip()
    if not text:
        return True
    if _PHATIC_RE.match(text):
        return True
    if len(text.split()) <= 4:
        low = text.lower()
        if low.startswith(("hey ", "hi ", "hello ", "yo ")) and not _SELF_REF_USER_RE.search(low):
            return True
    return False


def requires_user_fact_grounding(user_input: str, query_class: str = "") -> bool:
    """True when a truthful reply needs verified user-specific memory."""
    qclass = str(query_class or "").strip().upper()
    if qclass in {"PHATIC", "COMMAND", "FACTUAL", "CORRECTION"}:
        return False
    if qclass == "PERSONAL":
        return True
    if _SELF_REF_USER_RE.search(str(user_input or "")):
        return True
    return False


def count_verified_memory_lines(memory_context: str) -> int:
    ctx = str(memory_context or "")
    if _VERIFIED_BLOCK_MARKER not in ctx:
        return 0
    lines = [
        ln for ln in ctx.splitlines()
        if ln.strip().startswith("- [memory_id=") or ln.strip().startswith("  - [memory_id=")
    ]
    return len(lines)


def fail_closed_response(
    user_input: str,
    *,
    query_class: str = "",
    memory_context: str = "",
    grounding_confidence: float = 0.0,
    aggregated_confidence: float = 0.0,
) -> Optional[str]:
    """Return a deterministic hedge when LLM generation must not proceed."""
    if not _FAIL_CLOSED_ENABLED:
        return None
    if is_phatic_turn(user_input):
        return None
    if not requires_user_fact_grounding(user_input, query_class):
        return None

    verified_lines = count_verified_memory_lines(memory_context)
    gnd = float(grounding_confidence or 0.0)
    agg = float(aggregated_confidence or 0.0)

    if is_explicit_memory_audit_query(user_input):
        if verified_lines == 0:
            return (
                "I checked verified memory — nothing stored yet under the verified tier. "
                "Hypothesis-tier extractions (if any) aren't shown unless you ask for a memory audit."
            )
        return None

    low_grounding = gnd < _GROUNDING_FLOOR and agg < _GROUNDING_FLOOR
    if verified_lines == 0 and low_grounding:
        return (
            "I don't have that in verified memory, and the grounding score is too low "
            "for me to guess about your life or habits. Tell me what you'd like me to "
            "remember — I'll store it properly."
        )
    if verified_lines == 0 and requires_user_fact_grounding(user_input, query_class):
        return (
            "Nothing on that in verified memory yet — I won't invent it. "
            "Say it plainly if you want me to remember."
        )
    return None


def evaluate_chat_grounding_gate(
    user_input: str,
    *,
    query_class: str = "",
    memory_context: str = "",
    bus_result: Any = None,
) -> Optional[str]:
    gnd = agg = 0.0
    if bus_result is not None:
        gnd = float(getattr(bus_result, "grounding_confidence", 0.0) or 0.0)
        agg = float(
            getattr(bus_result, "aggregated_confidence",
                    getattr(bus_result, "agg_conf", 0.0)) or 0.0
        )
    ctx = str(memory_context or "")
    if not ctx and bus_result is not None:
        ctx = str(getattr(bus_result, "memory_context", "") or "")
    return fail_closed_response(
        user_input,
        query_class=query_class,
        memory_context=ctx,
        grounding_confidence=gnd,
        aggregated_confidence=agg,
    )
