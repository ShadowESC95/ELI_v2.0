"""Memory, RAG and KG limits come from the (tier-scaled) tunables, everywhere.

Audit 2026-10-03, after the user asked for every recall cap raised: the
tunables existed, but much of the pipeline never read them.
- The orchestrator (every non-phatic CHAT turn) put a fixed 8 reranked hits,
  8 recent turns and 6 verified memories in the prompt.
- plan_retrieval read get_tunable(), which skips the model-tier scaling, and
  research/expert used a fixed 20/20/15, below the balanced default.
- Its plans never set recent/summary/hop-2/merge limits, so unified retrieval
  fell back to a fixed 12/4/6/24.
- The KG matched a fixed 4-6 entities with 5 relations each, and the
  orchestrator's KG lookup capped itself near 960 chars whatever
  cog.kg_max_chars said.
"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from eli.core import cognition_tunables as T


def _plan(mode, scale=1.0):
    from eli.cognition.orchestrator import PlannerAgent
    planner = PlannerAgent.__new__(PlannerAgent)
    with patch("eli.core.model_tier.tier_scale", return_value=scale):
        return planner.plan_retrieval("tell me about my project", {"action": "CHAT"}, "",
                                      SimpleNamespace(recent_turns=[]), reasoning_mode=mode)


def test_deep_modes_never_gather_less_than_balanced():
    balanced, deep = _plan("normal"), _plan("research")
    for key in ("keyword_limit", "semantic_limit", "rag_limit", "kg_limit", "hop2_limit", "merge_cap"):
        assert deep[key] >= balanced[key], key


def test_every_plan_sets_the_limits_downstream_code_reads():
    for mode in ("quick", "normal", "research"):
        plan = _plan(mode)
        for key in ("keyword_limit", "kg_limit", "recent_limit", "summary_limit", "hop2_limit", "merge_cap"):
            assert plan.get(key), (mode, key)


def test_plans_follow_the_model_tier():
    small, large = _plan("normal", 1.0), _plan("normal", 2.5)
    assert large["semantic_limit"] == pytest.approx(small["semantic_limit"] * 2.5, abs=1)
    assert large["kg_limit"] == pytest.approx(small["kg_limit"] * 2.5, abs=1)


def test_history_depth_follows_the_tier_but_not_the_mode():
    assert _plan("research")["recent_limit"] == _plan("normal")["recent_limit"]


def test_unified_retrieval_fallbacks_are_the_tunables():
    from eli.memory import unified_retrieval as U
    seen = {}

    def fake_retrieve(mem, q, **kw):
        seen.update(kw)
        return U.TurnRetrievalResult()

    engine = SimpleNamespace(memory=object(), user_id="u", session_id="s")
    with patch.object(U, "retrieve_for_turn", fake_retrieve), \
            patch("eli.core.model_tier.tier_scale", return_value=1.0):
        U.orchestrator_retrieve(engine, "what did we decide", "", {})
    snap = T.snapshot()
    assert seen["recent_limit"] == snap["cog.mem_recent_turns"]
    assert seen["summary_limit"] == snap["cog.mem_summaries_recall"]
    assert seen["hop2_limit"] == snap["cog.mem_hop2_recall"]
    assert seen["merge_cap"] == snap["cog.mem_merge_cap"]


def test_kg_context_lists_as_many_entities_and_relations_as_the_tunables_allow(tmp_path):
    from eli.memory.knowledge_graph import KnowledgeGraph
    kg = KnowledgeGraph(db_path=tmp_path / "kg.sqlite3")
    for i in range(12):
        kg.add_relation("Atlas", f"uses_part_{i}", f"Part{i}", source="user")
    with patch("eli.core.model_tier.tier_scale", return_value=1.0):
        text = kg.context_for_prompt("Atlas", max_chars=20000)
    assert text.count("—[uses_part_") == T.snapshot()["cog.kg_relations"]  # was 5
    narrow = kg.context_for_prompt("Atlas", max_chars=20000, max_relations=3)
    assert narrow.count("—[uses_part_") == 3


def test_orchestrator_kg_lookup_uses_the_kg_character_budget():
    from eli.cognition.orchestrator import OrchestratorMemoryAgent
    calls = {}

    class _KG:
        def context_for_prompt(self, q, max_chars=0, **kw):
            calls.update(max_chars=max_chars, **kw)
            return "[Atlas]: a project"

    agent = OrchestratorMemoryAgent.__new__(OrchestratorMemoryAgent)
    with patch("eli.memory.knowledge_graph.get_knowledge_graph", return_value=_KG()), \
            patch("eli.core.model_tier.tier_scale", return_value=1.0):
        agent.kg_search("Atlas", 8)
    assert calls["max_chars"] == T.snapshot()["cog.kg_max_chars"]  # was min(2000, 8 * 120)
    assert calls["max_entities"] == 8


def test_context_assembly_shows_the_tunable_number_of_reranked_hits_and_turns():
    from eli.kernel.engine import CognitiveEngine
    eng = CognitiveEngine.__new__(CognitiveEngine)
    wm = SimpleNamespace(assembled_context="", reranked_hits=[
        {"text": f"evidence row {i}", "source": "vector", "score": 0.5} for i in range(60)])
    stm = SimpleNamespace(recent_turns=[
        {"role": "user", "content": f"turn {i}"} for i in range(60)])
    with patch("eli.core.model_tier.tier_scale", return_value=1.0), \
            patch.object(CognitiveEngine, "_build_grounded_evidence_context", return_value=""):
        ctx, _prompt = eng.assemble_precise_context("q", working_memory=wm, short_term_memory=stm)
    snap = T.snapshot()
    assert ctx.count("evidence row") == snap["cog.rerank_top_k"]   # was 8
    assert ctx.count("User: turn") == snap["cog.mem_recent_turns"]  # was 8


def test_orchestrator_verified_block_uses_the_semantic_shown_tunable():
    from eli.cognition import orchestrator as O
    with patch("eli.core.model_tier.tier_scale", return_value=1.0):
        assert O._verified_shown_limit() == T.snapshot()["cog.mem_semantic_shown"]  # was 6
        assert O._recent_turns_limit() == T.snapshot()["cog.mem_recent_turns"]      # was 12


def test_new_limits_are_tier_scaled():
    for key in ("cog.kg_entities", "cog.kg_relations", "cog.mem_exact_token_recall",
                "cog.mem_archive_recall", "cog.mem_observations"):
        assert key in T._GATHER_COUNT_KEYS, key
