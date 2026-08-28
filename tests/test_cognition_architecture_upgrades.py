"""Tests for enterprise cognition architecture upgrades (v2.3.36)."""
from __future__ import annotations

import pytest


def test_pipeline_trace_stage_names():
    from eli.kernel.pipeline_trace import STAGE_NAMES, stage_label, map_orch_trace_key
    assert STAGE_NAMES[6] == "AGENT_BUS"
    assert STAGE_NAMES[12] == "LEARNING_STATE_UPDATE"
    assert stage_label(12) == "LEARNING_STATE_UPDATE"
    assert map_orch_trace_key("stage_9") == 7
    assert map_orch_trace_key("agent_bus_specialists") == 6


def test_orchestrator_planner_mode_maps_quick_to_fast():
    from eli.cognition.reasoning_modes import orchestrator_planner_mode, mode_orchestrator_depth
    assert orchestrator_planner_mode("quick") == "fast"
    assert orchestrator_planner_mode("Normal") == "balanced"
    assert orchestrator_planner_mode("Expert") == "deep"
    assert mode_orchestrator_depth("quick") == "light"
    assert mode_orchestrator_depth("research") == "full"


def test_mode_chat_agent_profile_quick_is_lean():
    from eli.cognition.reasoning_modes import mode_chat_agent_profile
    quick = mode_chat_agent_profile("quick", code_query=False)
    assert quick == {"memory", "system", "orchestrator"}
    quick_code = mode_chat_agent_profile("quick", code_query=True)
    assert "file_code" in quick_code


def test_sequential_retrieve_alias():
    from eli.cognition.orchestrator import OrchestratorMemoryAgent

    class _Eng:
        memory = None

    agent = OrchestratorMemoryAgent(_Eng())
    plan = {"need_keyword": False, "need_semantic": False, "need_rag": False, "need_kg": False}
    from eli.cognition.orchestrator import LongTermMemoryRefs
    ltm = LongTermMemoryRefs(sqlite_ready=True, vector_ready=False, rag_ready=False)
    assert agent.sequential_retrieve("hi", "hi", plan, ltm) == ([], [], [], [])
    assert agent.parallel_retrieve("hi", "hi", plan, ltm) == ([], [], [], [])


def test_vector_store_tombstone_skips_search(monkeypatch):
    pytest.importorskip("faiss")
    pytest.importorskip("numpy")
    from eli.memory import vector_store as vs_mod

    monkeypatch.setattr(vs_mod, "FAISS_AVAILABLE", True)

    class _FakeIndex:
        ntotal = 1

        def add(self, vec):
            pass

        def search(self, vec, k):
            import numpy as np
            return np.array([[0.1]]), np.array([[0]])

    class _FakeEmbedder:
        def embed(self, text):
            return [0.1] * vs_mod.EMBED_DIM

    store = vs_mod.VectorStore.__new__(vs_mod.VectorStore)
    store._lock = __import__("threading").RLock()
    store._embed_lock = store._lock
    store._embedder = _FakeEmbedder()
    store._index = _FakeIndex()
    store._meta = [{"text": "deleted fact", "id": 42}]
    store._tombstone_ids = {42}
    store._adds_since_save = 0
    store._save_generation = 0
    store._index_path = "/tmp/test.faiss"
    store._meta_path = "/tmp/test.json"

    hits = store.search("deleted fact", top_k=5)
    assert hits == []


def test_retrieval_turn_cache():
    from eli.memory.retrieval import retrieve_for_turn, invalidate_turn_cache

    class _Mem:
        def recall_memory(self, q, limit=10):
            return [{"text": f"hit for {q}", "id": 1}]

        def search_conversations(self, q, user_id=None, limit=10):
            return []

        def get_recent_conversation(self, limit=10, user_id=None):
            return []

        def get_session_summaries(self, user_id=None, limit=4):
            return []

    mem = _Mem()
    invalidate_turn_cache()
    r1 = retrieve_for_turn(mem, "hello", session_id="s1", user_id="u1")
    r2 = retrieve_for_turn(mem, "hello", session_id="s1", user_id="u1")
    assert r1.semantic_hits == r2.semantic_hits
    invalidate_turn_cache("s1")


def test_dispatch_specialists_skips_memory(monkeypatch):
    from eli.cognition import agent_bus as ab

    captured = {}

    class _FakeBus:
        def dispatch(self, user_input, intent, session_id="", user_id="", reasoning_mode=None):
            captured["intent"] = dict(intent)
            return type("R", (), {"agents_used": [], "memory_context": ""})()

    monkeypatch.setattr(ab, "get_bus", lambda: _FakeBus())
    ab.dispatch_specialists("hi", {"action": "CHAT"}, skip_memory=True, reasoning_mode="quick")
    assert captured["intent"].get("_skip_memory_agent") is True
