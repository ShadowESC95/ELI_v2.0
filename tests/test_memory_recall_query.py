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
    out = llm_intent.parse_with_llm("Do you remember what we were talking about last week?")
    assert out["action"] == "MEMORY_RECALL"
    assert str(out["args"].get("query") or "").strip()


def test_router_recalls_conversation_by_phrase():
    text = "Do you remember what we were talking about last week?"
    out = route_intent(text)
    assert out["action"] == "MEMORY_RECALL"
    assert str(out["args"].get("query") or "").strip() == text
