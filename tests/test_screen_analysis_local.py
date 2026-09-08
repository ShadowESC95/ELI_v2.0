"""Screen analysis + local UI grounding."""
from __future__ import annotations

from eli.perception.screen_analysis import (
    analysis_depth_from_text,
    build_screen_analysis_prompt,
    wants_prior_screen_recall,
    wants_research_link,
)


def test_depth_from_in_depth_phrase():
    assert analysis_depth_from_text("analyze my screen in depth") == "deep"
    assert analysis_depth_from_text("exactly what is on my screen") == "deep"


def test_research_and_memory_intent():
    assert wants_research_link("how does this relate to my research")
    assert wants_prior_screen_recall("do you remember seeing this before")


def test_build_prompt_includes_user_question():
    p = build_screen_analysis_prompt("what app is open?", depth="standard")
    assert "what app is open?" in p


def test_ui_ground_local_only_by_default(monkeypatch):
    import eli.perception.ui_ground as ug
    monkeypatch.setattr(ug, "_setting", lambda k, d="": d)
    assert ug.configured_precision_backend() == ""
    assert ug.configured_agent_backend() == ""
