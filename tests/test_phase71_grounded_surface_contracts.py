from __future__ import annotations

import pytest

from eli.execution.router_enhanced import route
from eli.execution.executor_enhanced import execute
from eli.kernel.engine import CognitiveEngine


SURFACES = (
    {
        "name": "runtime_status",
        "prompt": "Who are you and what are you actually running on right now — model, context size, GPU layers, everything.",
        "action": "RUNTIME_STATUS",
        "tokens": ("runtime", "model", "context", "gpu"),
    },
    {
        "name": "gui_runtime_audit",
        "prompt": "scan the gui runtime wiring and prove every hook with actual file-read evidence",
        "action": "GUI_RUNTIME_AUDIT",
        "tokens": ("gui", "runtime", "audit", "proof"),
    },
    {
        "name": "personal_memory_summary",
        "prompt": "what do you know about me",
        "action": "PERSONAL_MEMORY_SUMMARY",
        "tokens": ("memory", "profile", "user"),
    },
    {
        "name": "name_source_audit",
        "prompt": "how do you know my name and which file is it stored in",
        "action": "NAME_SOURCE_AUDIT",
        "tokens": ("name", "source", "file"),
    },
    {
        "name": "memory_count",
        "prompt": "how many memories do you have",
        "action": "MEMORY_STATUS",
        "tokens": ("memory", "rows", "count"),
    },
    {
        "name": "frontier_status",
        "prompt": "run a full system wiring matrix for memory self proactive image world labs and chat flow",
        "action": "FRONTIER_STATUS",
        "tokens": ("chatflow", "memory", "proactive", "image", "world", "labs"),
    },
)

NONQUICK_MODES = ("chain_of_thought", "constitutional_ai")


def _visible_text(value) -> str:
    if isinstance(value, dict):
        return str(value.get("content") or value.get("response") or value.get("text") or "")
    return str(value or "")


def _assert_contract_surface(out: dict, expected_action: str) -> None:
    assert isinstance(out, dict)
    assert out.get("action") == expected_action

    text = _visible_text(out).strip()
    assert text

    low = text.lower()
    for bad in (
        "raw_packet",
        "failure_surface",
        "trace_missing",
        "targeted_assertion_failures",
    ):
        assert bad not in low


@pytest.fixture(scope="module")
def phase71_engine():
    return CognitiveEngine()


@pytest.mark.parametrize("case", SURFACES, ids=[c["name"] for c in SURFACES])
def test_phase71_route_contracts(case):
    routed = route(case["prompt"])
    assert routed.get("action") == case["action"]

    if case["name"] == "memory_count":
        assert (routed.get("args") or {}).get("memory_scope") == "count_only"


@pytest.mark.parametrize("case", SURFACES, ids=[c["name"] for c in SURFACES])
def test_phase71_executor_contracts(case):
    routed = route(case["prompt"])
    out = execute(routed.get("action"), routed.get("args") or {})
    _assert_contract_surface(out, case["action"])


@pytest.mark.parametrize("case", SURFACES, ids=[c["name"] for c in SURFACES])
@pytest.mark.parametrize("mode", NONQUICK_MODES)
def test_phase71_nonquick_grounded_contracts(case, mode, phase71_engine):
    quick = phase71_engine.process(case["prompt"], reasoning_mode="quick")
    nonquick = phase71_engine.process(case["prompt"], reasoning_mode=mode)

    _assert_contract_surface(nonquick, case["action"])

    report = nonquick.get("report") or {}
    if "quick_direct_allowed" in report:
        assert report.get("quick_direct_allowed") is False
    if "direct_telemetry_returned" in report:
        assert report.get("direct_telemetry_returned") is not True

    if report.get("synthesis_validated") is True:
        low = _visible_text(nonquick).lower()
        assert sum(1 for t in case["tokens"] if t in low) >= 1

        q_text = _visible_text(quick).strip()
        nq_text = _visible_text(nonquick).strip()
        if q_text and nq_text:
            assert q_text != nq_text


def test_phase71_executor_uses_canonical_middleware_table():
    from eli.execution import executor_enhanced as mod

    assert getattr(mod, "_ELI_EXECUTOR_CANONICAL_MIDDLEWARE_TABLE_V1", False) is True
    assert hasattr(mod, "_ELI_EXECUTOR_MIDDLEWARE_TABLE")


def test_phase71_router_uses_explicit_priority_pipeline():
    from eli.execution import router_enhanced as mod

    assert getattr(mod, "_ELI_ROUTE_PRIORITY_PIPELINE_V1", False) is True
    assert hasattr(mod, "_ELI_ROUTE_PRIORITY_STAGES")


def test_phase71_grounding_gate_uses_immutable_policy_engine():
    from eli.runtime import deterministic_grounding_gate as gate

    assert getattr(gate, "_ELI_DETERMINISTIC_GROUNDING_POLICY_ENGINE_V1", False) is True
    assert hasattr(gate, "_ELI_DG_POLICY_ENGINE")
