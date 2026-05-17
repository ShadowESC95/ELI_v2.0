"""
eli/memory/habits_memory_service.py
Canonical implementation lives in eli.memory.memory_service.
This module re-exports everything from there for backwards compatibility.
"""
from eli.memory.memory_service import (  # noqa: F401
    ensure_schema,
    get_or_create_session_id,
    append_chat_turn,
    get_last_user_utterance,
    summarize_recent_window,
)
