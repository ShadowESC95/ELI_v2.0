"""A new conversation must not inherit the previous one.

Live failure: a fresh "hello" was answered with a reply from the PREVIOUS session
("You're not asking for a repeat — you're telling me to stop being a walking meme…"),
prompting the user to point out "I never said any of that, that was the last
conversation." Turns are written with a session_id but were read back without one, so
the block labelled "Active chat history" actually held the last N turns from ANY
session. That is also why deleting the offending text never helped — the next session
simply inherited whatever was newest.
"""
from __future__ import annotations
import os, tempfile
import pytest
from eli.memory import Memory

OLD = "still glitchy, post-breakfast haze and Rick and Morty on repeat"


@pytest.fixture
def mem():
    db = tempfile.mktemp(suffix=".sqlite3")
    m = Memory(db_path=db)
    m.add_conversation_turn("user", "old chat", "session_OLD", "alex")
    m.add_conversation_turn("assistant", OLD, "session_OLD", "alex")
    m.add_conversation_turn("user", "hello", "session_NEW", "alex")
    yield m
    if os.path.exists(db):
        os.unlink(db)


def test_scoped_fetch_excludes_the_previous_session(mem):
    turns = mem.get_recent_conversation(limit=20, user_id="alex", session_id="session_NEW")
    assert not any(OLD in str(t.get("content", "")) for t in turns), \
        "a new session still inherits the previous conversation"


def test_scoped_fetch_keeps_this_session(mem):
    turns = mem.get_recent_conversation(limit=20, user_id="alex", session_id="session_NEW")
    assert any("hello" in str(t.get("content", "")) for t in turns)


def test_unscoped_fetch_is_the_documented_leak(mem):
    # guards the regression: without a session_id the old conversation comes back
    turns = mem.get_recent_conversation(limit=20, user_id="alex")
    assert any(OLD in str(t.get("content", "")) for t in turns)


def test_cross_session_recall_is_still_possible_when_asked(mem):
    # deliberate cross-session lookups must keep working — only the DEFAULT is scoped
    turns = mem.get_recent_conversation(limit=20, user_id="alex", session_id="session_OLD")
    assert any(OLD in str(t.get("content", "")) for t in turns)
