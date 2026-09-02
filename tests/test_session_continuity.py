"""Session continuity — live thread memory in prompts."""
from __future__ import annotations

from eli.cognition.correction_patterns import is_continuity_complaint, is_correction_query
from eli.runtime.session_continuity import (
    SESSION_THREAD_MAX_TURNS,
    build_inline_exchange_block,
    build_session_thread_block,
    prior_turns_excluding_current,
    session_has_prior_turns,
)


def test_session_thread_covers_twelve_turns():
    turns = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"turn {i}"}
        for i in range(14)
    ]
    block = build_session_thread_block(turns, user_input="turn 14")
    assert "SESSION THREAD" in block
    assert "turn 2" in block
    assert "turn 13" in block
    assert "turn 0" not in block


def test_inline_exchange_excludes_current_user_message():
    turns = [
        {"role": "user", "content": "But does Tubi have it?"},
        {"role": "assistant", "content": "Maybe later"},
        {"role": "user", "content": "earlier point"},
    ]
    block = build_inline_exchange_block(turns, user_input="But does Tubi have it?")
    assert "earlier point" in block
    assert block.count("But does Tubi") == 0


def test_session_has_prior_turns():
    turns = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]
    assert session_has_prior_turns(turns, "c")
    assert not session_has_prior_turns(turns[:1], "c")


def test_continuity_complaint_routes_correction():
    q = "are you not paying attention to your previous answers?"
    assert is_continuity_complaint(q)
    assert is_correction_query(q)


def test_prior_turns_count():
    turns = [{"role": "user", "content": f"t{i}"} for i in range(5)]
    prior = prior_turns_excluding_current(turns, "t5")
    assert len(prior) == 5
    assert SESSION_THREAD_MAX_TURNS == 12
