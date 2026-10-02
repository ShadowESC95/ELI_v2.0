"""Phase 2 of the identity/provenance plan (2026-10-02): PlannerAgent.plan_retrieval()
picks a fixed channel set up front (fast/balanced/deep) and sequential_retrieve()
never re-checked that choice against what actually came back — a fast-mode turn
that skipped semantic/rag/kg and got a thin keyword result stayed thin for the
rest of the pipeline, even when more evidence was one cheap channel away.

Mirrors memory/retrieval.py's own _THIN_EVIDENCE precedent (same threshold,
same "ran dry, pull in more" idea) instead of inventing a second, divergent
gating constant.

Confirmed while implementing (not assumed): mem.recall_memory() (reached via
retrieve_for_turn) has no need_semantic parameter at all and runs the vector/
FAISS search unconditionally — orchestrator_retrieve's need_semantic only
decides whether to KEEP those hits or discard them. Fast mode's own comment
("skip FAISS embedding, saves one LLM call") does not actually happen on this
path. So the fix for the semantic channel is "stop discarding hits already
computed," not "make a second, genuinely new call" — verified here by
asserting the fallback reuses orchestrator_retrieve's return rather than
calling semantic_search() again.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from eli.cognition.orchestrator import LongTermMemoryRefs, OrchestratorMemoryAgent


def _agent():
    engine = MagicMock()
    engine.session_id = "s1"
    engine.user_id = "u1"
    return OrchestratorMemoryAgent(engine)


def _ltm(rag_ready=True):
    return LongTermMemoryRefs(sqlite_ready=True, vector_ready=True, rag_ready=rag_ready)


def _hits(n, tag="x"):
    return [{"text": f"{tag}-{i}"} for i in range(n)]


def test_thin_keyword_result_pulls_in_already_computed_semantic_hits():
    """Fast mode: need_semantic=False. orchestrator_retrieve still computes
    semantic hits internally (confirmed) — the gap fallback must reuse them,
    not call semantic_search() again."""
    agent = _agent()
    plan = {"need_keyword": True, "need_semantic": False, "need_rag": False,
            "need_kg": False, "prefer_identity": False}

    with patch("eli.memory.unified_retrieval.orchestrator_retrieve",
              return_value=(_hits(1, "kw"), _hits(5, "sem"), MagicMock(elapsed_ms=10))) as mock_retrieve:
        agent.semantic_search = MagicMock(return_value=_hits(99, "wasted"))
        keyword_hits, semantic_hits, rag_hits, kg_hits = agent.sequential_retrieve(
            "query", "hyde", plan, _ltm())

    assert len(keyword_hits) == 1
    assert semantic_hits == _hits(5, "sem")  # reused, not re-fetched
    agent.semantic_search.assert_not_called()
    # The fetch plan sent to orchestrator_retrieve requested semantic even
    # though the mode plan said no — that's what makes the hits available.
    _, _, _, fetch_plan = mock_retrieve.call_args.args
    assert fetch_plan["need_semantic"] is True


def test_a_rich_keyword_result_does_not_trigger_the_fallback():
    agent = _agent()
    plan = {"need_keyword": True, "need_semantic": False, "need_rag": False,
            "need_kg": False, "prefer_identity": False}

    with patch("eli.memory.unified_retrieval.orchestrator_retrieve",
              return_value=(_hits(6, "kw"), _hits(6, "sem"), MagicMock(elapsed_ms=10))):
        agent.document_rag_search = MagicMock()
        agent.kg_search = MagicMock()
        keyword_hits, semantic_hits, rag_hits, kg_hits = agent.sequential_retrieve(
            "query", "hyde", plan, _ltm())

    assert len(keyword_hits) == 6
    assert semantic_hits == []  # mode plan said no, and there was no gap to fill
    agent.document_rag_search.assert_not_called()
    agent.kg_search.assert_not_called()


def test_thin_result_enables_rag_when_ready_and_not_already_requested():
    agent = _agent()
    plan = {"need_keyword": True, "need_semantic": True, "need_rag": False,
            "need_kg": False, "prefer_identity": False, "rag_limit": 8}

    with patch("eli.memory.unified_retrieval.orchestrator_retrieve",
              return_value=(_hits(1, "kw"), _hits(1, "sem"), MagicMock(elapsed_ms=10))):
        agent.document_rag_search = MagicMock(return_value=_hits(4, "rag"))
        keyword_hits, semantic_hits, rag_hits, kg_hits = agent.sequential_retrieve(
            "query", "hyde", plan, _ltm(rag_ready=True))

    assert rag_hits == _hits(4, "rag")
    agent.document_rag_search.assert_called_once_with("query", 8)


def test_thin_result_does_not_enable_rag_when_not_ready():
    agent = _agent()
    plan = {"need_keyword": True, "need_semantic": True, "need_rag": False,
            "need_kg": False, "prefer_identity": False}

    with patch("eli.memory.unified_retrieval.orchestrator_retrieve",
              return_value=(_hits(1, "kw"), _hits(1, "sem"), MagicMock(elapsed_ms=10))):
        agent.document_rag_search = MagicMock()
        agent.sequential_retrieve("query", "hyde", plan, _ltm(rag_ready=False))

    agent.document_rag_search.assert_not_called()


def test_thin_result_enables_kg_when_not_already_requested():
    agent = _agent()
    plan = {"need_keyword": True, "need_semantic": True, "need_rag": True,
            "need_kg": False, "prefer_identity": False, "kg_limit": 8}

    with patch("eli.memory.unified_retrieval.orchestrator_retrieve",
              return_value=(_hits(1, "kw"), [], MagicMock(elapsed_ms=10))):
        agent.document_rag_search = MagicMock(return_value=[])
        agent.kg_search = MagicMock(return_value=_hits(2, "kg"))
        keyword_hits, semantic_hits, rag_hits, kg_hits = agent.sequential_retrieve(
            "query", "hyde", plan, _ltm(rag_ready=True))

    assert kg_hits == _hits(2, "kg")
    agent.kg_search.assert_called_once_with("query", 8)


def test_a_channel_that_already_ran_and_came_back_thin_is_not_rerun():
    """need_rag=True but document_rag_search itself returned nothing — the
    gap fallback must not call it again; a second call would just repeat the
    same empty result."""
    agent = _agent()
    plan = {"need_keyword": True, "need_semantic": False, "need_rag": True,
            "need_kg": False, "prefer_identity": False, "rag_limit": 8}

    with patch("eli.memory.unified_retrieval.orchestrator_retrieve",
              return_value=(_hits(1, "kw"), [], MagicMock(elapsed_ms=10))):
        agent.document_rag_search = MagicMock(return_value=[])
        agent.sequential_retrieve("query", "hyde", plan, _ltm(rag_ready=True))

    agent.document_rag_search.assert_called_once()  # the normal, planned call


def test_falling_back_to_keyword_and_semantic_search_on_unified_failure_is_unaffected():
    """The pre-existing exception fallback path (unified retrieve errors) is
    untouched by this change — need_semantic still gates semantic_search()
    normally there, since there is no 'already computed' result to reuse."""
    agent = _agent()
    plan = {"need_keyword": True, "need_semantic": True, "need_rag": False,
            "need_kg": False, "prefer_identity": False, "keyword_limit": 12,
            "semantic_limit": 12}

    with patch("eli.memory.unified_retrieval.orchestrator_retrieve",
              side_effect=RuntimeError("boom")):
        agent.keyword_search = MagicMock(return_value=_hits(2, "kw"))
        agent.semantic_search = MagicMock(return_value=_hits(2, "sem"))
        keyword_hits, semantic_hits, rag_hits, kg_hits = agent.sequential_retrieve(
            "query", "hyde", plan, _ltm())

    assert keyword_hits == _hits(2, "kw")
    assert semantic_hits == _hits(2, "sem")
