from __future__ import annotations

from eli.execution.router_enhanced import route
from eli.execution.executor_enhanced import execute


def assert_route(prompt: str, expected_action: str):
    r = route(prompt)
    assert isinstance(r, dict)
    assert r.get("action") == expected_action, r
    assert isinstance(r.get("args", {}), dict)
    assert isinstance(r.get("meta", {}), dict)
    return r


def assert_standard_result(result, expected_action: str):
    assert isinstance(result, dict)
    assert result.get("ok") in {True, False}
    assert result.get("action") == expected_action
    assert isinstance(result.get("content"), str)
    assert isinstance(result.get("response"), str)
    assert result.get("content")
    assert result.get("response")


def test_self_report_recent_updates_route():
    r = assert_route("What updates and checks have you performed as of late?", "SELF_REPORT")
    assert r["args"]["self_report_scope"] == "recent_updates"
    assert r["meta"]["allow_chat_without_evidence"] is False
    assert r["meta"]["forbid_chat_fallback"] is True
    assert r["meta"]["forbid_fake_update_claims"] is True


def test_gui_audit_proof_route():
    r = assert_route(
        "Prove to me that you actually scanned the file provide data or timestamps etc",
        "GUI_RUNTIME_AUDIT",
    )
    assert r["args"]["proof_requested"] is True
    assert r["args"]["audit_depth"] == "proof"
    assert r["meta"]["allow_chat_without_evidence"] is False


def test_repeated_gui_audit_proof_route():
    r = assert_route(
        "YES, I WANT MORE DETAILS AND TIMESTAMPS AS PROOF THAT YOU READ THE FILE",
        "GUI_RUNTIME_AUDIT",
    )
    assert r["args"]["proof_requested"] is True


def test_latency_route():
    r = assert_route("it took you 20 minutes to generate that answer?", "EXPLAIN_COGNITION_RUNTIME")
    assert r["args"]["diagnostic_focus"] == "latency_timing"


def test_inference_runtime_route():
    r = assert_route(
        "what are the current inference issues and how can they be resolved without sacrificing reasoning?",
        "EXPLAIN_COGNITION_RUNTIME",
    )
    assert r["args"]["diagnostic_focus"] == "inference_runtime"


def test_memory_count_route():
    r = assert_route("How many memories do you have?", "MEMORY_STATUS")
    assert r["args"]["memory_scope"] == "count_only"


def test_recent_memory_route():
    r = assert_route("What memories have you been processing lately?", "MEMORY_STATUS")
    assert r["args"]["memory_scope"] == "recent_processing"


def test_runtime_status_executor_shape():
    result = execute("RUNTIME_STATUS", {
        "question": "Who are you and what are you actually running on right now?"
    })
    assert_standard_result(result, "RUNTIME_STATUS")


def test_self_report_executor_shape():
    result = execute("SELF_REPORT", {
        "question": "What updates and checks have you performed as of late?",
        "self_report_scope": "recent_updates",
    })
    assert_standard_result(result, "SELF_REPORT")


def test_gui_runtime_audit_executor_shape():
    result = execute("GUI_RUNTIME_AUDIT", {
        "question": "Audit GUI file",
        "proof_requested": True,
    })
    assert_standard_result(result, "GUI_RUNTIME_AUDIT")
