"""Context synthesiser — the persona handoff builder.

build_persona_handoff compiles grounded evidence (agent-bus context, intent,
recent turns) into the package handed to ELI's persona-bound LLM. The grounding
MUST survive into the assembled context (that's the anti-confabulation link — the
model answers from evidence, not thin air). live_runtime_brief gives an honest
one-liner about where the model actually runs. Pure/model-free. Normal suite.
"""
from __future__ import annotations

import pytest

from eli.cognition.context_synthesiser import build_persona_handoff, live_runtime_brief


def test_handoff_shape():
    h = build_persona_handoff("hello there")
    assert isinstance(h, dict)
    assert {"assembled_context", "user_prompt", "intent"} <= set(h)


def test_handoff_carries_user_input():
    h = build_persona_handoff("what is the weather in Dublin")
    assert "weather" in str(h["user_prompt"]).lower()


def test_handoff_incorporates_grounded_evidence():
    # The whole point: evidence from the agent bus reaches the persona context so the
    # model answers from it rather than inventing.
    h = build_persona_handoff(
        "what's the weather",
        agent_bus_context="EVIDENCE: it is 12 degrees and cloudy in Dublin",
    )
    assert "cloudy" in str(h["assembled_context"]).lower()


def test_handoff_with_no_context_is_safe():
    h = build_persona_handoff("just chatting")
    assert isinstance(h["assembled_context"], str)  # never None/crash


def test_intent_is_threaded_through():
    h = build_persona_handoff("do a thing", intent={"action": "CHAT", "confidence": 0.9})
    assert isinstance(h["intent"], dict)


def test_live_runtime_brief_is_str():
    assert isinstance(live_runtime_brief(), str)
