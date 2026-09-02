"""Session continuity — live thread memory injected into every CHAT turn.

Pure context plumbing: recent session turns are always visible to the model
(above the persona-handoff cap and inline on the user prompt). Does not alter
web escalation, follow-through, or conversational content policy.
"""
from __future__ import annotations

import re
from typing import Any, List

# How far back the live session thread reaches (user + ELI turns).
SESSION_THREAD_MAX_TURNS = 12
SESSION_THREAD_CHARS_PER_TURN = 320
INLINE_EXCHANGE_MAX_TURNS = 12
INLINE_EXCHANGE_CHARS_PER_TURN = 280


def _normalise_turn(item: Any) -> tuple[str, str]:
    role = ""
    content = ""
    if isinstance(item, dict):
        role = str(item.get("role") or item.get("speaker") or "").lower()
        content = str(item.get("content") or item.get("message") or item.get("text") or "")
    elif isinstance(item, (list, tuple)) and len(item) >= 2:
        role = str(item[0] or "").lower()
        content = str(item[1] or "")
    else:
        content = str(item or "")
    return role, re.sub(r"\s+", " ", content).strip()


def prior_turns_excluding_current(turns: Any, user_input: str = "") -> List[dict]:
    """Chronological turns before the current user message (for injection)."""
    _key = str(user_input or "").strip()[:80]
    out: List[dict] = []
    for item in list(turns or []):
        role, content = _normalise_turn(item)
        if not content:
            continue
        if role == "user" and _key and content[:80] == _key:
            continue
        out.append({"role": role, "content": content})
    return out


def session_has_prior_turns(turns: Any, user_input: str = "") -> bool:
    return len(prior_turns_excluding_current(turns, user_input)) >= 2


def build_session_thread_block(
    turns: Any,
    *,
    max_turns: int = SESSION_THREAD_MAX_TURNS,
    max_chars_per: int = SESSION_THREAD_CHARS_PER_TURN,
    user_input: str = "",
) -> str:
    """Authoritative live session transcript — rides above persona cap (never truncated)."""
    prior = prior_turns_excluding_current(turns, user_input)
    lines: List[str] = []
    for item in prior[-max_turns:]:
        role, content = _normalise_turn(item)
        if not content:
            continue
        label = "User" if role == "user" else "ELI"
        if len(content) > max_chars_per:
            content = content[: max_chars_per - 3].rstrip() + "..."
        lines.append(f"{label}: {content}")
    if not lines:
        return ""
    return (
        "[SESSION THREAD — live transcript of THIS session, oldest→newest. "
        "Use it for continuity: the user may refer to the last message or something "
        f"several turns back (up to {max_turns} turns shown). "
        "Do not contradict or forget what appears here.]\n"
        + "\n".join(lines)
    )


def build_inline_exchange_block(
    turns: Any,
    *,
    max_turns: int = INLINE_EXCHANGE_MAX_TURNS,
    max_chars_per: int = INLINE_EXCHANGE_CHARS_PER_TURN,
    user_input: str = "",
) -> str:
    """Same thread, prepended directly to the user prompt (broker + stream paths)."""
    prior = prior_turns_excluding_current(turns, user_input)
    lines: List[str] = []
    for item in prior[-max_turns:]:
        role, content = _normalise_turn(item)
        if not content:
            continue
        label = "You" if role == "user" else "ELI"
        if len(content) > max_chars_per:
            content = content[: max_chars_per - 3].rstrip() + "..."
        lines.append(f"{label}: {content}")
    if len(lines) < 2:
        return ""
    return "[Recent session]\n" + "\n".join(lines)
