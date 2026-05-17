"""Memory service — provides session functions backed by persistent SQLite memory."""
from __future__ import annotations
import os
import uuid
from typing import Optional

_session_id = str(uuid.uuid4())


def ensure_schema() -> None:
    """Ensure memory tables exist (delegates to Memory class)."""
    try:
        from eli.memory import get_memory
        get_memory()  # Schema created on init
    except Exception:
        pass


def get_or_create_session_id() -> str:
    """Return a persistent session ID for this process lifetime."""
    return _session_id


def append_chat_turn(session_id: str, user_msg: str, assistant_msg: str) -> None:
    """
    Legacy compatibility wrapper.

    Canonical chat-turn persistence lives in CognitiveEngine.
    This helper is disabled by default to prevent duplicate writes.

    To re-enable for a standalone non-CognitiveEngine caller only:
        export ELI_ALLOW_MEMORY_SERVICE_PERSIST=1
    """
    if str(os.environ.get("ELI_ALLOW_MEMORY_SERVICE_PERSIST", "")).strip() != "1":
        return

    try:
        from eli.memory import get_memory
        mem = get_memory()
        mem.add_conversation_turn("user", user_msg, session_id=session_id)
        mem.add_conversation_turn("assistant", assistant_msg, session_id=session_id)
    except Exception:
        pass  # Never crash the chat pipeline


def get_last_user_utterance(session_id: str) -> Optional[str]:
    """Return the most recent user message from the database."""
    try:
        from eli.memory import get_memory
        mem = get_memory()
        turns = mem.get_recent_conversation(limit=5, session_id=session_id)
        for turn in turns:
            if turn.get("role") == "user":
                return turn.get("content")
    except Exception:
        pass
    return None


def summarize_recent_window(session_id: str, window: int = 10) -> str:
    """Return a summary of recent conversation from the database."""
    try:
        from eli.memory import get_memory
        mem = get_memory()
        turns = mem.get_recent_conversation(limit=window * 2, session_id=session_id)
        if not turns:
            return "No conversation yet."
        turns = list(reversed(turns))
        summary = []
        for turn in turns:
            role = turn.get("role", "?")
            content = (turn.get("content") or "")[:80]
            summary.append(f"{role}: {content}...")
        return "\n".join(summary)
    except Exception:
        return "No conversation yet."
