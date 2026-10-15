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
    # how long the last reply took is answered from its audit row, not from a RAM report
    assert_route("it took you 20 minutes to generate that answer?", "ROUTING_FAULT_EXPLAIN")


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


def test_a_slow_reply_is_answered_from_its_record_and_ram_with_ram(monkeypatch):
    """'that took over a minute??' got the inference-RAM report, twice. A remark that the last reply
    was slow goes to the last-turn rule (ROUTING_FAULT_EXPLAIN): the audit rows, with model time, and
    where the model runs. RAM questions keep the RAM report; how to speed up gets the runtime settings."""
    assert_route("that took over a minute?? i didn't ask if anything was carried out", "ROUTING_FAULT_EXPLAIN")
    assert route("how much ram are you using?")["args"]["diagnostic_focus"] == "inference_ram"
    assert route("how can we decrease latency?")["args"]["diagnostic_focus"] == "inference_runtime"
    for not_about_eli in ("you take a seat", "it took a lot of work to build the shed", "this movie is so slow"):
        assert route(not_about_eli)["action"] != "ROUTING_FAULT_EXPLAIN", not_about_eli

    from eli.cognition import self_claims
    from eli.runtime import deterministic_grounding_gate as g
    from eli.runtime.personal_memory_deep_response import build_routing_fault_explanation
    monkeypatch.setattr(self_claims, "turn_record_lines", lambda *a, **k: [
        "[today 20:42] “Hey Eli, how are you doing this evening?” -> CHAT (quick, 71 s): ok; model ran 1 time "
        "on 5,898 prompt characters, 69 s of model time"])
    monkeypatch.setattr(g, "_inference_runtime_lines", lambda: "Inference runtime (live, from the loaded model):")
    out = build_routing_fault_explanation("that took over a minute??")
    assert "69 s of model time" in out and "Inference runtime" in out
    assert "inference RAM" not in out and "re-run through the live router" not in out
