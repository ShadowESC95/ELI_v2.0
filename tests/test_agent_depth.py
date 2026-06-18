"""Agent knowledge-gathering depth: multi-hop memory deepen (#2) + broadened
status-agent triggers (#3). Deterministic — no model."""
from __future__ import annotations
from unittest.mock import patch
import pytest
from eli.cognition.agent_bus import (
    _memory_seed_terms, BusMemoryAgent, CapabilityAgent, VoiceAgent,
)


# ── #2: seed-term extraction + multi-hop deepen ──────────────────────────────
def test_seed_terms_salient_only():
    t = _memory_seed_terms("User references a custom field-theory framework in research work")
    assert "framework" in t and "research" in t
    assert "user" not in [x.lower() for x in t]  # stopword dropped
    assert _memory_seed_terms("what do you know") == []


class _FakeMem:
    db_path = "/tmp/x.sqlite3"
    def __init__(self):
        self.calls = []
    def recall_memory(self, q, limit=8):
        self.calls.append(q)
        if len(self.calls) == 1:
            return [{"id": "1", "text": "User researches quantum gravity simulations"}]
        # hop-2 (seeded by terms from hop-1) returns NEW connected facts
        return [{"id": "2", "text": "User runs FRB dispersion simulations"},
                {"id": "1", "text": "User researches quantum gravity simulations"}]  # dup
    def search_conversations(self, q, user_id=None, limit=5): return []
    def get_recent_conversation(self, limit=6, user_id=None): return []
    def get_session_summaries(self, user_id=None, limit=3): return []


def test_memory_agent_multi_hop_deepens_thin_recall():
    fake = _FakeMem()
    with patch("eli.memory.get_memory", return_value=fake):
        r = BusMemoryAgent().run("tell me about my research", {"action": "CHAT"}, "s", "u")
    # second hop fired (thin first hop) and added the connected fact, de-duped
    assert len(fake.calls) == 2
    ctx = (r.data or {}).get("memory_context", "")
    assert "FRB dispersion" in ctx          # deepened fact surfaced
    assert ctx.count("quantum gravity simulations") == 1  # dup not double-counted


# ── #3: broadened triggers fire on questions, not on commands ────────────────
@pytest.mark.parametrize("q,fires", [
    ("are you able to edit files", True),
    ("what do you do", True),
    ("do you support pdfs", True),
    ("can you pause spotify", False),   # command, not capability question
    ("hello", False),
])
def test_capability_trigger_breadth(q, fires):
    skipped = (CapabilityAgent().run(q, {"action": "CHAT"}, "s", "u").data or {}).get("skipped", False)
    assert (not skipped) == fires


@pytest.mark.parametrize("q,fires", [
    ("is my microphone working", True),
    ("what's the wake word", True),
    ("are you listening", True),
    ("play music", False),
    ("hi", False),
])
def test_voice_trigger_breadth(q, fires):
    skipped = (VoiceAgent().run(q, {"action": "CHAT"}, "s", "u").data or {}).get("skipped", False)
    assert (not skipped) == fires
