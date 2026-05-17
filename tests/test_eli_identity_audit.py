from __future__ import annotations

from eli.execution.executor_enhanced import execute
from eli.execution.router_enhanced import route
from eli.runtime.control_contracts import CONTROL_ACTIONS, is_control_action
from eli.runtime.eli_identity_audit import build_eli_identity_audit


def test_identity_audit_is_grounded_control_action():
    assert "ELI_IDENTITY_AUDIT" in CONTROL_ACTIONS
    assert is_control_action("eli_identity_audit")


def test_identity_audit_route_and_executor_contract():
    routed = route("what exactly is ELI and what should ELI be classified as")
    assert routed.get("action") == "ELI_IDENTITY_AUDIT"
    assert (routed.get("meta") or {}).get("allow_chat_without_evidence") is False

    out = execute(routed.get("action"), routed.get("args") or {})
    assert isinstance(out, dict)
    assert out.get("action") == "ELI_IDENTITY_AUDIT"
    assert out.get("evidence_source") == "eli_identity_audit_local_verified_matrix_v1"
    assert out.get("content")


def test_identity_audit_contains_verified_classification_matrix():
    report = build_eli_identity_audit("classify eli")
    cls = report.get("classification") or {}
    assert "local persistent agentic cognitive-runtime" in cls.get("current_classification", "")
    assert "not verified AGI" in (cls.get("not_classified_as") or [])

    matrix = report.get("capability_matrix") or []
    assert len(matrix) >= 8
    assert any(row.get("surface") == "Reasoning modes" for row in matrix)
    assert any(row.get("surface") == "Embodied world model" for row in matrix)

    modes = report.get("reasoning_modes") or []
    assert {m.get("mode") for m in modes} >= {
        "quick",
        "chain_of_thought",
        "self_consistency",
        "tree_of_thoughts",
        "constitutional_ai",
    }
    for mode in modes:
        assert mode.get("instructions")
        assert mode.get("tasks")
        assert (mode.get("generation_overrides") or {}).get("max_tokens")

