"""MEMORY_RECALL must never dispatch with an empty query."""
from __future__ import annotations

from eli.cognition import llm_intent
from eli.execution.router_enhanced import route_intent


def test_llm_intent_memory_recall_fills_empty_query(monkeypatch):
    raw = {
        "action": "MEMORY_RECALL",
        "args": {},
        "confidence": 0.85,
    }
    import json

    class _FakeGGUF:
        @staticmethod
        def chat_completion(*_a, **_k):
            return json.dumps(raw)

    monkeypatch.setattr(llm_intent, "gguf_inference", _FakeGGUF)
    monkeypatch.setattr(llm_intent, "_GRAMMAR_CACHE", {})
    monkeypatch.setattr(llm_intent, "_cache", {})
    out = llm_intent.parse_with_llm("Do you remember what we were talking about with the boiler?")
    assert out["action"] == "MEMORY_RECALL"
    assert str(out["args"].get("query") or "").strip()


def test_a_period_question_goes_to_chat_which_reads_that_period(monkeypatch):
    """Live 2026-10-03: "Give me your exact memory and timestamps over the past 3 days" was
    guessed as MEMORY_RECALL, a topic search with no dates, and answered from 25 September."""
    import json

    class _FakeGGUF:
        @staticmethod
        def chat_completion(*_a, **_k):
            return json.dumps({"action": "MEMORY_RECALL", "args": {"query": "past 3 days"}, "confidence": 0.9})

    monkeypatch.setattr(llm_intent, "gguf_inference", _FakeGGUF)
    monkeypatch.setattr(llm_intent, "_GRAMMAR_CACHE", {})
    monkeypatch.setattr(llm_intent, "_cache", {})
    out = llm_intent.parse_with_llm("Give me your exact memory and timestamps over the past 3 days")
    assert out["action"] == "CHAT"
    assert route_intent("Do you remember what we were talking about last week?")["action"] == "CHAT"


def test_router_recalls_conversation_by_phrase():
    text = "Do you remember what we were talking about?"
    out = route_intent(text)
    assert out["action"] == "MEMORY_RECALL"
    assert str(out["args"].get("query") or "").strip() == text


def test_how_the_memory_is_doing_gets_the_health_report_not_a_recall():
    """Live 2026-10-09: "and the memory- how is that doing?" fell to the model's intent guess,
    which recalled "memory status" and dumped eighteen stored messages, private ones included."""
    from eli.execution.router_enhanced import route
    for text in ("All good my end, and the memory- how is that doing?", "how is your memory doing?",
                 "how's the memory holding up", "is your memory working now?"):
        out = route(text)
        assert out["action"] == "MEMORY_STATUS" and out["args"]["memory_scope"] == "health", text
    assert route("what do you remember about lisbon?")["action"] == "MEMORY_RECALL"
    assert route("how is your memory of the trip to lisbon?")["action"] != "MEMORY_STATUS"


def test_the_health_report_is_the_short_one(monkeypatch):
    from eli.execution.executor_enhanced import execute
    from eli.memory import memory_truth
    monkeypatch.setattr(memory_truth, "memory_truth_report", lambda: {
        "summary": {"user_memories": 3, "user_memory_fts": 3, "user_conversation_turns": 9,
                    "user_conversations": 2}, "databases": {}, "vectors": {}})
    out = execute("MEMORY_STATUS", {"memory_scope": "health"})
    assert out["content"].startswith("Memory system") and "all stores reachable" in out["content"]
    assert "sqlite3" not in out["content"]


def test_every_recalled_memory_says_when_it_is_from(monkeypatch):
    """Asked "when was that?" after a recall, ELI made a time up: nothing it showed had a date."""
    import time as _time
    from eli.execution.executor_enhanced import execute
    from eli.memory import memory as memory_mod
    when = _time.mktime((2026, 9, 28, 21, 15, 0, 0, 0, -1))

    class _Mem:
        def search_memory(self, q, limit=20):
            return [{"id": 1, "ts": when, "text": "i am collecting a friend in lisbon"},
                    {"id": "kg:context", "ts": 0, "text": "[Lisbon] (place)"}]
    monkeypatch.setattr(memory_mod, "get_memory", lambda *a, **k: _Mem())
    out = execute("MEMORY_RECALL", {"query": "lisbon"})["content"]
    assert "[Mon 28 Sep 21:15" in out and "i am collecting a friend in lisbon" in out
    assert "[Lisbon] (place)" in out and "[] [Lisbon]" not in out
