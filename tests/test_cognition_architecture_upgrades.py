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
    from eli.cognition.reasoning_modes import orchestrator_planner_mode, orchestrator_react_steps
    assert orchestrator_planner_mode("quick") == "fast"
    assert orchestrator_planner_mode("Normal") == "balanced"
    assert orchestrator_planner_mode("Expert") == "deep"
    # The ReAct depth comes from the same table, whatever name the mode arrives under.
    assert orchestrator_react_steps("quick") == orchestrator_react_steps("fast") == 1
    assert orchestrator_react_steps(None) == 1
    assert orchestrator_react_steps("normal") == orchestrator_react_steps("research") == 3


class _ReactEngine:
    """Just enough engine for AgentOrchestrator.run() to reach its non-CHAT ReAct loop."""

    def __init__(self, intent, decisions):
        from types import SimpleNamespace
        self.session_id, self.user_id = "s-react", "u-react"
        self.document_rag = None
        self.prompts = []
        self._intent = intent
        self._decisions = list(decisions)
        self.memory = SimpleNamespace(get_recent_conversation=lambda **k: [],
                                      add_observation=lambda *a, **k: None)
        self.inference_broker = SimpleNamespace(infer=self._infer)

    def _infer(self, prompt, **kw):
        self.prompts.append(prompt)
        return self._decisions.pop(0) if self._decisions else "ANSWER"

    def parse_intent(self, text, recent):
        return dict(self._intent)

    def verify_persona_lock(self):
        return True


def _run_react(monkeypatch, mode, decisions):
    from types import SimpleNamespace
    from eli.cognition import agent_bus as ab
    from eli.cognition.orchestrator import AgentOrchestrator
    from eli.runtime import grounded_remediation as gr

    monkeypatch.setattr(gr, "handle_confirmation", lambda text: None)
    monkeypatch.setattr(gr, "try_handle_query", lambda text: None)
    monkeypatch.setattr(ab, "get_bus", lambda: SimpleNamespace(
        dispatch=lambda *a, **k: ab.DispatchResult(intent_action="GET_WEATHER", intent_confidence=0.9)))
    engine = _ReactEngine({"action": "GET_WEATHER", "args": {"location": "Lisbon"}, "confidence": 0.9},
                          decisions)
    orch = AgentOrchestrator(engine)
    ran = []

    def _execute(intent, user_input):
        ran.append((intent["action"], dict(intent.get("args") or {})))
        return {"ok": True, "content": f"{intent['action']} done"}

    monkeypatch.setattr(orch.executor_agent, "execute", _execute)
    orch.run("what's the weather in Lisbon tomorrow", reasoning_mode=mode)
    return engine, ran


def test_quick_runs_the_routed_action_alone_with_no_react_decision(monkeypatch):
    """Its one-pass case looked for a mode named "fast", which the engine never passes."""
    engine, ran = _run_react(monkeypatch, "quick", ["TOOL:WEB_SEARCH Lisbon forecast"])
    assert [a for a, _ in ran] == ["GET_WEATHER"]
    assert engine.prompts == []


def test_the_next_tool_gets_the_arguments_written_for_it_not_the_last_ones(monkeypatch):
    engine, ran = _run_react(monkeypatch, "normal", ["TOOL:WEB_SEARCH Lisbon forecast for Saturday"])
    assert [a for a, _ in ran] == ["GET_WEATHER", "WEB_SEARCH"]
    assert ran[1][1] == {"query": "Lisbon forecast for Saturday"}       # as written, no "location"


def test_the_react_loop_never_starts_an_action_only_the_users_words_may_start(monkeypatch):
    for decision in ("TOOL:SHELL_EXEC rm -rf ~/notes", "TOOL:MEMORY_FORGET everything",
                     "TOOL:CONFIRM_CODE_FIX", "TOOL:NOT_AN_ACTION x"):
        engine, ran = _run_react(monkeypatch, "normal", [decision])
        assert [a for a, _ in ran] == ["GET_WEATHER"], decision


def test_the_next_tool_reads_json_arguments_too():
    from eli.cognition.orchestrator import _react_next_step
    assert _react_next_step('TOOL:WEB_SEARCH {"q": "tide times"}', "asked") == (
        "WEB_SEARCH", {"q": "tide times", "query": "tide times"})
    assert _react_next_step("TOOL: DATE.", "what day is it") == ("DATE", {"query": "what day is it"})
    assert _react_next_step("ANSWER", "x") is None


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
