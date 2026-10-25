"""Session continuity — live thread memory injected into every CHAT turn.

Pure context plumbing: recent session turns are always visible to the model
(above the persona-handoff cap and inline on the user prompt). Does not alter
web escalation, follow-through, or conversational content policy.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

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


def _turn_time(item: Any) -> Any:
    if isinstance(item, dict):
        return item.get("timestamp") or item.get("ts") or item.get("event_ts")
    return None


def _stamped(item: Any, text: str) -> str:
    from eli.cognition.evidence_format import turn_stamp
    stamp = turn_stamp(_turn_time(item))
    return f"[{stamp}] {text}" if stamp else text


# Turns come from every session of this user, so they are history with times on
# them, not "this session". Said once, in the header of every block that shows them.
_HISTORY_NOTE = ("each line is timestamped. Lines from before today are history: what was "
                 "true then (a song playing, an app open, a plan) is not the current state")


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
        out.append({"role": role, "content": content, "timestamp": _turn_time(item)})
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
        lines.append(_stamped(item, f"{label}: {content}"))
    if not lines:
        return ""
    return (
        "[CONVERSATION THREAD — your recent exchanges with this user, oldest→newest "
        f"(up to {max_turns} turns); {_HISTORY_NOTE}. Use it for continuity: the user may "
        "refer to the last message or something several turns back.]\n"
        + "\n".join(lines)
    )


def exchange_budget_chars(user_input: str = "") -> int:
    """Characters the recent exchange may take: its share of the live context window, the same
    quarter of the prompt room the stream path's overflow guard gives the user prompt (3 characters
    a token, an answer floor of an eighth of the window). Built to fit it, the block is never cut
    from the front afterwards — which is how a news briefing two turns back vanished."""
    try:
        from eli.cognition import gguf_inference
        n_ctx = int(gguf_inference.current_context_limit() or 0)
    except Exception:
        n_ctx = 0
    if n_ctx <= 0:
        return 4000
    room = ((n_ctx - max(1024, n_ctx // 8) - 64) * 3) // 4
    return max(1200, room - len(str(user_input or "")) - 64)


# Actions whose reply is the result of something carried out, not something the model recalled:
# a news briefing, a search, a file read. Named on ELI's line in the exchange so a follow-up ("go
# deeper on the sea wall story") and a challenge ("you just told me that") are read against
# what was fetched — the model called a real Guardian story its own invention.
def _reply_actions(items: List[Any]) -> Dict[int, str]:
    try:
        from eli.runtime import orchestrator_audit_ledger as oal
        rows = [r for r in oal.recent_turns(80) if not r.get("parent_request_id")]
    except Exception:
        return {}
    out: Dict[int, str] = {}
    for i, item in enumerate(items):
        role, _ = _normalise_turn(item)
        if role == "user":
            continue
        try:
            t = float(_turn_time(item) or 0)
        except (TypeError, ValueError):
            continue
        if not t or not rows:
            continue
        best = min(rows, key=lambda r: abs(float(r.get("ts") or 0) - t))
        act = str(best.get("action") or "").upper()
        if abs(float(best.get("ts") or 0) - t) <= 30 and act and act not in ("CHAT", "GENERAL_CHAT"):
            out[i] = act
    return out


def build_inline_exchange_block(
    turns: Any,
    *,
    max_turns: int = INLINE_EXCHANGE_MAX_TURNS,
    max_chars_per: int = INLINE_EXCHANGE_CHARS_PER_TURN,
    user_input: str = "",
    budget_chars: Optional[int] = None,
) -> str:
    """Same thread, prepended directly to the user prompt (broker + stream paths). Filled newest
    first within budget_chars (default: exchange_budget_chars). ELI's latest reply is given whole —
    what a follow-up or a correction is about — and so is a fetched result (news, a search) up to
    three replies back, and every reply when the user points back at one; older turns are clipped to
    max_chars_per. A reply that was the result of an action is labelled with it."""
    from eli.cognition.correction_patterns import refers_to_earlier_reply
    whole_replies = refers_to_earlier_reply(user_input)
    budget = int(budget_chars if budget_chars is not None else exchange_budget_chars(user_input))
    reply_cap = max(max_chars_per, budget // 3)
    items = prior_turns_excluding_current(turns, user_input)[-max_turns:]
    actions = _reply_actions(items)
    picked: List[str] = []
    used = 0
    replies_seen = 0
    for i in range(len(items) - 1, -1, -1):
        item = items[i]
        role, content = _normalise_turn(item)
        if not content:
            continue
        if role == "user":
            label, cap = "You", max_chars_per * 2
            # Pasted text is someone else's (correction_patterns.split_pasted): shown as the user's,
            # ELI argued with ChatGPT's critique as if the user had written it, and then sent it back
            # as its own reply.
            from eli.cognition.correction_patterns import split_pasted
            own, pasted = split_pasted(content)
            if pasted:
                content = f'{own} [then pasted text written by someone else, not the user: "{pasted}"]'
        else:
            replies_seen += 1
            label = f"ELI (result of {actions[i]}, not recalled)" if i in actions else "ELI"
            # whole: ELI's latest reply, a fetched result a few replies back (news, search), or any
            # reply the user points back at
            whole = whole_replies or replies_seen == 1 or (i in actions and replies_seen <= 3)
            cap = reply_cap if whole else max_chars_per
        if len(content) > cap:
            content = content[: cap - 3].rstrip() + "..."
        line = _stamped(item, f"{label}: {content}")
        room = budget - used
        if len(line) > room:
            if room >= 200:
                picked.append(line[: room - 3].rstrip() + "...")
            break
        picked.append(line)
        used += len(line) + 1
    lines = list(reversed(picked))
    if len(lines) < 2:
        return ""
    return f"[Recent conversation — {_HISTORY_NOTE}]\n" + "\n".join(lines)


def fit_exchange_prompt(prompt: str, budget: int) -> str:
    """A prompt of [Recent conversation] + "You: <message>" cut to `budget` characters by dropping
    the oldest whole lines, never the message or the newest turns. (Cutting the string from the
    front took the news briefing a follow-up was about and left half a line.)"""
    prompt = str(prompt or "")
    if len(prompt) <= budget:
        return prompt
    head, sep, msg = prompt.rpartition("\n\nYou: ")
    if not sep:
        return prompt[-budget:]
    tail = sep + msg
    lines = head.split("\n")
    header = lines[0] if lines and lines[0].startswith("[Recent conversation") else ""
    body = lines[1:] if header else lines
    room = budget - len(tail) - len(header) - 1
    kept: List[str] = []
    for line in reversed(body):
        if len(line) + 1 > room:
            break
        kept.append(line)
        room -= len(line) + 1
    if not kept:
        return ("You: " + msg)[-budget:]
    return "\n".join(([header] if header else []) + list(reversed(kept))) + tail
