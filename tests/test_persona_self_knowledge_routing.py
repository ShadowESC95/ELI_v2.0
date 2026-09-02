"""Persona self-knowledge must stay in CHAT, not the SELF_REPORT runtime one-liner."""
from __future__ import annotations

import pytest

from eli.execution.router_enhanced import route
from eli.runtime.control_contracts import (
    is_identity_depth_followup,
    is_persona_self_knowledge_query,
    route_control_text,
)


@pytest.mark.parametrize("question", [
    "what do you know about yourself?",
    "what else can you tell me about yourself?",
    "what do you know of yourself",
    "describe yourself",
])
def test_persona_self_knowledge_stays_chat(question):
    assert is_persona_self_knowledge_query(question)
    r = route(question)
    assert r["action"] == "CHAT"
    assert r["meta"]["matched_by"] in {
        "identity.persona_chat",
        "eli.followup.identity_depth",
    }
    assert route_control_text(question, "CHAT") is None


@pytest.mark.parametrize("question", [
    "be more in depth eli",
    "go deeper",
    "tell me more",
    "what else",
])
def test_identity_depth_followup_stays_conversational(question):
    assert is_identity_depth_followup(question)
    r = route(question)
    assert r["action"] == "CHAT"
    assert route_control_text(question, "CHAT") is None


def test_runtime_self_report_still_reaches_self_report():
    assert route_control_text("who are you", "CHAT") == "SELF_REPORT"
    assert route_control_text("do you know who you are?", "CHAT") == "SELF_REPORT"


def test_reasoning_modes_request_not_hijacked_by_depth_guard():
    assert not is_identity_depth_followup("explain all your reasoning modes in depth")
    r = route("explain all your reasoning modes")
    assert r["action"] == "EXPLAIN_ALL_REASONING_MODES"
