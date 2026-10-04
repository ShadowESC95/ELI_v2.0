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
