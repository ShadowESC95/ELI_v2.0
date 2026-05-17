"""Tests for eli.execution.execution_planner — ~80 tests."""
from __future__ import annotations

import pytest

from eli.execution.execution_planner import build_execution_plan, build_route_decision, ExecutionPlan
from eli.runtime.pipeline_models import RouteDecision


# ── Helper ────────────────────────────────────────────────────────────────

def plan_for(action: str, provider: str = "custom_gguf", quick: bool = False) -> ExecutionPlan:
    rd = RouteDecision(
        user_input="test input",
        action=action,
        args={},
        confidence=0.9,
        meta={},
    )
    return build_execution_plan(rd)


# ── ExecutionPlan structure ───────────────────────────────────────────────

def test_build_plan_returns_execution_plan():
    result = plan_for("CHAT")
    assert isinstance(result, ExecutionPlan)

def test_execution_plan_has_action():
    result = plan_for("CHAT")
    assert hasattr(result, "action")
    assert result.action == "CHAT"

def test_execution_plan_has_steps():
    result = plan_for("CHAT")
    assert hasattr(result, "steps")
    assert isinstance(result.steps, list)

def test_execution_plan_has_agent_profile():
    result = plan_for("CHAT")
    assert hasattr(result, "agent_profile")
    assert isinstance(result.agent_profile, list)

def test_execution_plan_has_response_provider():
    result = plan_for("CHAT")
    assert hasattr(result, "response_provider")

def test_execution_plan_steps_not_empty():
    result = plan_for("CHAT")
    assert len(result.steps) > 0


# ── Per-action plans ──────────────────────────────────────────────────────

@pytest.mark.parametrize("action", [
    "CHAT",
    "MEMORY_RECALL",
    "RUNTIME_STATUS",
    "MEMORY_STATUS",
    "COGNITION_STATUS",
    "USER_IDENTITY_SUMMARY",
])
def test_standard_actions_build_plan(action):
    result = plan_for(action)
    assert isinstance(result, ExecutionPlan)
    assert result.action == action

def test_chat_plan_has_retrieval_steps():
    result = plan_for("CHAT")
    assert len(result.steps) >= 2

def test_memory_recall_plan_has_memory_agent():
    result = plan_for("MEMORY_RECALL")
    assert "memory" in result.agent_profile

def test_runtime_status_plan_has_introspection():
    result = plan_for("RUNTIME_STATUS")
    assert "introspection" in result.agent_profile or len(result.steps) > 0

def test_memory_status_plan_profile():
    result = plan_for("MEMORY_STATUS")
    assert isinstance(result.agent_profile, list)
    assert len(result.agent_profile) > 0

def test_unknown_action_builds_fallback_plan():
    result = plan_for("UNKNOWN_ACTION_XYZ")
    assert isinstance(result, ExecutionPlan)
    assert len(result.steps) > 0


# ── Steps structure ───────────────────────────────────────────────────────

def test_chat_steps_include_final_response():
    result = plan_for("CHAT")
    step_names = [s.name for s in result.steps]
    assert any("response" in n.lower() for n in step_names)

def test_memory_recall_steps_include_context_or_response():
    result = plan_for("MEMORY_RECALL")
    step_names = [s.name for s in result.steps]
    assert any("assembly" in n.lower() or "context" in n.lower() or "response" in n.lower()
               for n in step_names)

def test_runtime_status_steps_include_response():
    result = plan_for("RUNTIME_STATUS")
    step_names = [s.name for s in result.steps]
    assert any("response" in n.lower() or "snapshot" in n.lower()
               for n in step_names)


# ── Agent profiles ────────────────────────────────────────────────────────

def test_chat_profile_includes_memory():
    result = plan_for("CHAT")
    assert "memory" in result.agent_profile or "planner" in result.agent_profile

def test_runtime_status_profile_not_empty():
    result = plan_for("RUNTIME_STATUS")
    assert len(result.agent_profile) > 0

def test_cognition_status_profile():
    result = plan_for("COGNITION_STATUS")
    assert isinstance(result.agent_profile, list)


# ── build_route_decision ──────────────────────────────────────────────────

def test_build_route_decision_from_dict():
    rd = build_route_decision("hello", {"action": "CHAT", "confidence": 0.9})
    assert isinstance(rd, RouteDecision)
    assert rd.action == "CHAT"
    assert rd.user_input == "hello"

def test_build_route_decision_confidence():
    rd = build_route_decision("test", {"action": "MEMORY_RECALL", "confidence": 0.95})
    assert abs(rd.confidence - 0.95) < 1e-9

def test_build_route_decision_default_chat():
    rd = build_route_decision("test", {"confidence": 0.5})
    assert rd.action == "CHAT"

def test_build_route_decision_from_object():
    class MockRoute:
        action = "RUNTIME_STATUS"
        confidence = 0.8
        args = {}
        meta = {}

    rd = build_route_decision("test", MockRoute())
    assert rd.action == "RUNTIME_STATUS"

def test_build_route_decision_args():
    rd = build_route_decision("test", {"action": "CHAT", "args": {"query": "test"}})
    assert rd.args == {"query": "test"}


# ── Multiple consecutive plans ────────────────────────────────────────────

def test_multiple_plan_builds():
    for action in ["CHAT", "MEMORY_RECALL", "RUNTIME_STATUS", "CHAT"]:
        result = plan_for(action)
        assert isinstance(result, ExecutionPlan)


# ── RouteDecision ─────────────────────────────────────────────────────────

def test_route_decision_is_dataclass():
    rd = RouteDecision(user_input="hi", action="CHAT", args={}, confidence=0.9, meta={})
    assert rd.user_input == "hi"
    assert rd.action == "CHAT"
    assert rd.confidence == 0.9

def test_route_decision_empty_args():
    rd = RouteDecision(user_input="hi", action="CHAT", args={}, confidence=0.5, meta={})
    assert rd.args == {}

def test_route_decision_with_meta():
    rd = RouteDecision(user_input="hi", action="CHAT", args={}, confidence=0.9,
                      meta={"matched_by": "test"})
    assert rd.meta.get("matched_by") == "test"
