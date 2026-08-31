"""Guards against fabricated user biography (wild night, etc.)."""
from __future__ import annotations

import inspect

import pytest

from eli.cognition.correction_patterns import (
    correction_shortcut_allowed,
    explicit_web_search_request,
    is_biographical_dispute,
    is_correction_query,
)
from eli.kernel import engine


@pytest.mark.parametrize(
    "text",
    [
        "what wild night did i have, what do you mean?",
        "What are you talking about, what wild night?",
        "why do you say that i have been through a bit lately?",
        "i never said that",
        "what do you mean by that",
    ],
)
def test_correction_patterns_match_disputes(text):
    assert is_correction_query(text)
    assert is_biographical_dispute(text)


@pytest.mark.parametrize(
    "text",
    [
        "hey buddy how's things",
        "play spotify",
        "what is python",
    ],
)
def test_correction_patterns_skip_normal_chat(text):
    assert not is_correction_query(text)
    assert not is_biographical_dispute(text)


def test_classify_query_marks_wild_night_dispute_as_correction():
    assert engine._classify_query("what wild night did i have?", "CHAT") == "CORRECTION"


def test_correction_repair_has_biographical_dispute_steering():
    src = inspect.getsource(engine.CognitiveEngine._correction_repair)
    low = src.lower()
    assert "biographical" in low or "wild night" in low or "life, habits, or experiences" in low
    assert "patches" in low and "upgrades" in low


def test_correction_repair_caps_long_budget():
    src = inspect.getsource(engine.CognitiveEngine._correction_repair)
    assert "_corr_max > 512" in src or "512" in src


def test_web_search_request_not_hijacked_by_correction_shortcut():
    msg = 'what are you talking about? go search the web and tell me how "classic" it is'
    assert is_correction_query(msg)
    assert explicit_web_search_request(msg)
    assert not correction_shortcut_allowed(msg, "WEB_SEARCH")
    assert not correction_shortcut_allowed(msg, "CHAT")


def test_persona_handoff_has_low_grounding_guard():
    src = inspect.getsource(engine.CognitiveEngine._build_persona_handoff_once)
    assert "LOW GROUNDING" in src
    assert "wild night" in src.lower() or "personal events" in src.lower()
