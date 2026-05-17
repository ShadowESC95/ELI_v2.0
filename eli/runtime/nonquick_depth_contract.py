from __future__ import annotations

from typing import Any


NONQUICK_MARKERS = (
    "constitutional",
    "const",
    "cot",
    "chain",
    "tree",
    "tot",
    "self_consistency",
    "self-c",
    "reason",
)

QUICK_MARKERS = ("quick", "fast", "raw")


META_CONTINUITY_TRIGGERS = (
    "short answer",
    "short answers",
    "terribly short",
    "why are you",
    "what is with",
    "what's with",
    "where is your continuity",
    "continuity",
    "awareness",
    "memory",
    "lobotom",
    "constitutional",
    "reasoning mode",
    "quick mode",
    "fallback",
    "pipeline",
    "orchestration",
    "why did you",
    "what the fuck",
)


BAD_GENERIC_FALLBACKS = (
    "short and sweet",
    "what can i do for you",
    "feel free to ask",
    "i apologize if my responses have been lacking",
    "my goal is to provide concise",
    "i can't assist with that",
)


def mode_name(mode: Any) -> str:
    if mode is None:
        return ""
    if hasattr(mode, "value"):
        return str(mode.value).lower()
    return str(mode).lower()


def is_quick_mode(mode: Any) -> bool:
    m = mode_name(mode)
    return any(x == m or x in m for x in QUICK_MARKERS)


def is_nonquick_mode(mode: Any) -> bool:
    m = mode_name(mode)
    return (not is_quick_mode(m)) and any(x in m for x in NONQUICK_MARKERS)


def is_meta_continuity_query(text: str) -> bool:
    t = (text or "").lower()
    return any(x in t for x in META_CONTINUITY_TRIGGERS)


def strengthen_query_class(query_class: str, text: str, mode: Any) -> str:
    if is_nonquick_mode(mode) and is_meta_continuity_query(text):
        return "META_CONTINUITY_DIAGNOSTIC"
    if is_meta_continuity_query(text):
        return "META_CONTINUITY_DIAGNOSTIC"
    return query_class


def force_nonquick_plan(existing_plan: Any, mode: Any, text: str = "") -> str:
    if is_nonquick_mode(mode):
        if existing_plan in (None, "", "none", "NONE"):
            return "mandatory_nonquick_grounded_synthesis"
    if is_meta_continuity_query(text):
        if existing_plan in (None, "", "none", "NONE"):
            return "continuity_diagnostic_synthesis"
    return existing_plan


def block_bad_nonquick_output(text: str, mode: Any, user_text: str = "") -> str:
    if not is_nonquick_mode(mode):
        return text

    t = (text or "").strip()
    low = t.lower()

    if len(t) < 220 or any(x in low for x in BAD_GENERIC_FALLBACKS):
        return (
            "Internal cognition-contract fault: this was a non-Quick response, but the generated "
            "answer collapsed into a short/generic fallback. The correct behavior is to run the "
            "full continuity-aware synthesis path: route → memory/context grounding → plan → "
            "draft → critique/check → revised final → output governor. This indicates the current "
            "engine still allowed a shallow fallback surface in a non-Quick mode."
        )

    return text


def stage11_zero_visible_fault(mode: Any) -> str:
    m = mode_name(mode) or "unknown"
    return (
        "Internal Stage-11 synthesis fault: the primary synthesis path produced zero visible tokens. "
        f"Current mode was `{m}`, so raw GGUF fallback is blocked. The fix is to repair the stream/"
        "broker assembly path, not to answer from a quick fallback template."
    )
