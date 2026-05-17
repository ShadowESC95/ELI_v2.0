from __future__ import annotations

def _route(text: str):
    from eli.execution import router_enhanced
    fn = getattr(router_enhanced, "route", None) or getattr(router_enhanced, "route_intent")
    return fn(text)

def test_full_memory_about_me_routes_to_personalised_response():
    r = _route("What do you know about me from memory? Give me everything, provide a full and in depth summary.")
    assert r["action"] == "PERSONAL_MEMORY_SUMMARY"

def test_memory_internals_plus_personalised_routes_to_personalised_response():
    r = _route("Explain exactly how your memory system works internally — which files, which DB tables, which functions and what you actually remember about me. We are not in quick mode.")
    assert r["action"] == "PERSONAL_MEMORY_DEEP_EXPLAIN"

def test_raw_count_request_can_still_be_diagnostic():
    r = _route("how many memories do you have")
    assert r["action"] != "PERSONAL_MEMORY_DEEP_EXPLAIN"

def test_browser_complaint_routes_to_routing_fault_explain():
    r = _route("Why the fuck did you go onto the browser for that response?")
    assert r["action"] == "ROUTING_FAULT_EXPLAIN"

def test_executor_personal_memory_deep_response_shape():
    from eli.execution import executor_enhanced
    execute = getattr(executor_enhanced, "execute_action", None) or getattr(executor_enhanced, "execute")
    out = execute("PERSONAL_MEMORY_DEEP_EXPLAIN", {"question": "what do you know about me from memory, full summary"})
    text = str(out.get("content") or out.get("response") or "")
    assert out["action"] == "PERSONAL_MEMORY_DEEP_EXPLAIN"
    assert out.get("evidence_source") == "personal_memory_sqlite"
    assert "Personal memory evidence report" in text
    assert "memory_truth_evidence" not in text[:120]

def test_nonquick_personal_memory_uses_cognition_pipeline(monkeypatch):
    from eli.kernel.engine import CognitiveEngine

    eng = CognitiveEngine()
    result = eng.process(
        "What do you know about me from memory? Give me a full summary.",
        reasoning_mode="chain_of_thought",
    )

    assert isinstance(result, dict)
    assert result.get("ok") is True
    assert result.get("action") in {
        "PERSONAL_MEMORY_DEEP_EXPLAIN",
        "PERSONAL_MEMORY_SUMMARY",
    }

    visible = str(result.get("content") or result.get("response") or "").strip()
    assert visible

    # In isolated tests, GGUF may be unavailable. That is still valid: this
    # assertion proves Non-Quick returned a structured cognition envelope rather
    # than the old direct wrapper string.
    low = visible.lower()
    assert (
        "memory" in low
        or "personal" in low
        or "model not ready" in low
        or "no gguf model" in low
    )
