from __future__ import annotations

from typing import Any, Dict, Optional


def _low(text: Any) -> str:
    try:
        return str(text or "").lower()
    except Exception:
        return ""


def wants_memory_internals(text: Any) -> bool:
    low = _low(text)
    return (
        "memory" in low
        and (
            "internally" in low
            or "internal" in low
            or "internals" in low
            or "memory system" in low
            or "db table" in low
            or "db tables" in low
            or "sqlite" in low
            or "which files" in low
            or "which db" in low
            or "which functions" in low
            or "files, which db tables" in low
            or "tables, which functions" in low
        )
    )


def wants_personal_memory(text: Any) -> bool:
    low = _low(text)
    return (
        "memory" in low
        and (
            "about me" in low
            or "remember about me" in low
            or "actually remember about me" in low
            or "what you remember" in low
            or "what do you know about me" in low
            or "my memory" in low
            or "personal memory" in low
            or "personalised" in low
            or "personalized" in low
        )
    )


def wants_personal_memory_deep_explain(text: Any) -> bool:
    if wants_memory_internals(text) and wants_personal_memory(text):
        return True
    return wants_user_model_provenance(text)


def wants_user_model_provenance(text: Any) -> bool:
    """Static template vs dynamic/evolving understanding of the user."""
    low = _low(text)
    if not low:
        return False
    static_markers = (
        "hardcoded", "hard coded", "hard-coded", "template", "stub", "static info",
        "static profile", "about me section",
    )
    dynamic_markers = (
        "dynamic", "emergent", "evolving", "evolve", "update these preference",
        "actually remember", "not updating",
    )
    subject_markers = (
        "about me", "profile", "preference", "memory", "user info", "understanding",
        "who i am", "what you know about me",
    )
    has_static = any(m in low for m in static_markers)
    has_dynamic = any(m in low for m in dynamic_markers)
    has_subject = any(m in low for m in subject_markers)
    return has_subject and (has_static or has_dynamic)


def personal_memory_deep_route(text: Any) -> Dict[str, Any]:
    return {
        "action": "PERSONAL_MEMORY_DEEP_EXPLAIN",
        "args": {"question": str(text or ""), "detail": "full"},
        "confidence": 0.995,
        "meta": {
            "matched_by": "eli.route_contracts.personal_memory_deep_explain",
            "need_grounding": True,
            "allow_chat_without_evidence": False,
            "task_family": "personal_memory",
            "response_contract": "personal_memory_deep_explain_with_runtime_and_user_memory",
        },
    }


def classify_precedence_route(text: Any) -> Optional[Dict[str, Any]]:
    """
    Canonical precedence contract.

    Hybrid question:
      memory internals + what you remember about me
      -> PERSONAL_MEMORY_DEEP_EXPLAIN

    Pure memory internals remains EXPLAIN_MEMORY_RUNTIME elsewhere.

    Pure personal memory remains PERSONAL_MEMORY_SUMMARY elsewhere.

    This module prevents later wrappers from re-implementing contradictory
    phrase tests.
    """
    if wants_personal_memory_deep_explain(text):
        return personal_memory_deep_route(text)
    return None


__all__ = [
    "wants_memory_internals",
    "wants_personal_memory",
    "wants_personal_memory_deep_explain",
    "wants_user_model_provenance",
    "personal_memory_deep_route",
    "classify_precedence_route",
]
