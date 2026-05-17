from __future__ import annotations

from eli.cognition.agent_bus import SystemAgent, _ALL_AGENTS
from eli.execution.executor_enhanced import execute
from eli.execution.router_enhanced import route
from eli.runtime.control_contracts import CONTROL_ACTIONS, is_control_action


def test_frontier_status_is_control_action():
    assert "FRONTIER_STATUS" in CONTROL_ACTIONS
    assert is_control_action("frontier_status")


def test_frontier_status_has_system_and_agent_bus_wiring():
    assert "FRONTIER_STATUS" in SystemAgent.SYSTEM_ACTIONS
    names = [a.name for a in _ALL_AGENTS]
    assert "frontier" in names


def test_frontier_status_route_and_executor_contract():
    prompt = "run a full system wiring matrix for memory self proactive image world labs and chat flow"
    routed = route(prompt)
    assert routed.get("action") == "FRONTIER_STATUS"

    out = execute(routed.get("action"), routed.get("args") or {})
    assert isinstance(out, dict)
    assert out.get("action") == "FRONTIER_STATUS"
    assert out.get("evidence_source") == "frontier_status_local_runtime_matrix_v1"

    report = out.get("report")
    assert isinstance(report, dict)
    for key in (
        "runtime",
        "memory",
        "awareness",
        "proactive",
        "image",
        "world_labs",
        "chatflow",
        "module_matrix",
    ):
        assert key in report

    chatflow = report.get("chatflow") or {}
    assert "router_priority_pipeline" in chatflow
    assert "executor_middleware_table" in chatflow
    assert "grounding_policy_engine" in chatflow

    world_labs = report.get("world_labs") or {}
    assert world_labs.get("experimental_tab_exists") is True
    assert world_labs.get("experimental_root_exists") is True
