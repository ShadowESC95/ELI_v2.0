"""Stage 1 reasoning-mode rename + per-mode agent time budgets."""
from __future__ import annotations
from unittest.mock import patch
import pytest
import eli.core.config as C
from eli.cognition.reasoning_modes import canonical_mode, mode_display, mode_budget_multiplier


@pytest.mark.parametrize("name,key,display", [
    ("quick", "quick", "Quick"),
    ("normal", "chain_of_thought", "Normal"),
    ("advanced", "self_consistency", "Advanced"),
    ("research", "tree_of_thoughts", "Research"),
    ("expert", "constitutional_ai", "Expert"),
])
def test_rename_maps_and_displays(name, key, display):
    assert canonical_mode(name) == key
    assert mode_display(name) == display


def test_legacy_mode_names_still_work():
    assert canonical_mode("cot") == "chain_of_thought"
    assert canonical_mode("tot") == "tree_of_thoughts"
    assert canonical_mode("constitutional ai") == "constitutional_ai"


def test_mode_budget_multipliers_default():
    assert mode_budget_multiplier("quick") == 1.0
    assert mode_budget_multiplier("normal") == 1.0
    assert mode_budget_multiplier("advanced") == 1.5
    assert mode_budget_multiplier("research") == 2.0
    assert mode_budget_multiplier("expert") == 2.5


def test_mode_budget_is_tunable():
    try:
        C.set("cog.mode_budget_research", 300)
        assert mode_budget_multiplier("research") == 3.0
    finally:
        C.delete("cog.mode_budget_research")
    assert mode_budget_multiplier("research") == 2.0  # back to default


def test_dispatch_threads_multiplier_to_layer():
    from eli.cognition import agent_bus as AB
    seen = {}
    orig = AB.AgentBus._collect_layer
    def spy(self, agents, ui, intent, sid, uid):
        seen['mult'] = (intent or {}).get('_mode_budget_mult', 1.0)
        return orig(self, agents, ui, intent, sid, uid)
    with patch.object(AB.AgentBus, '_collect_layer', spy):
        bus = AB.get_bus()
        bus.dispatch("tell me about my research in depth", {"action": "CHAT"}, "s", "u", reasoning_mode="expert")
    assert seen.get('mult') == 2.5
    with patch.object(AB.AgentBus, '_collect_layer', spy):
        AB.get_bus().dispatch("tell me about my research in depth", {"action": "CHAT"}, "s", "u", reasoning_mode="quick")
    assert seen.get('mult') == 1.0  # quick unchanged


# ── Stage 2: confidence-driven iterative deepening + mode escalation ─────────
def test_quick_mode_never_deepens():
    """Quick stays fast — escalate() returns None even on a low-grounding factual turn."""
    from unittest.mock import MagicMock
    import eli.runtime.grounding_escalation as GE
    class _B:
        grounding_confidence = 0.2
        def to_context_block(self): return "x"
    eng = MagicMock(); eng.session_id = "s"; eng.user_id = "u"
    assert GE.escalate(eng, "what is my research framework called",
                       {"action": "CHAT"}, _B(), reasoning_mode="quick") is None


def test_deeper_mode_iterates_and_escalates():
    from unittest.mock import MagicMock, patch
    import eli.runtime.grounding_escalation as GE
    class _B:
        def __init__(self, g): self.grounding_confidence = g
        def to_context_block(self): return "EVIDENCE"
    calls = []
    def fake_redispatch(engine, ui, intent, reasoning_mode=None, gather_mult=1.0):
        calls.append(reasoning_mode)
        return _B(0.6 if len(calls) == 1 else 0.9)  # crosses 0.75 on 2nd pass
    eng = MagicMock(); eng.session_id = "s"; eng.user_id = "u"
    eng._synthesize_answer = lambda *a, **k: "Grounded answer."
    with patch.object(GE, "_redispatch_broad", fake_redispatch):
        r = GE.escalate(eng, "what is my research framework called",
                        {"action": "CHAT"}, _B(0.2), reasoning_mode="research")
    assert r is not None and r.get("ok")
    assert calls and all(m == "constitutional_ai" for m in calls)  # research → expert budget


def test_mode_targets_and_iters_table():
    import eli.runtime.grounding_escalation as GE
    assert GE._mode_max_iters("quick") == 0
    assert GE._mode_max_iters("expert") == 4
    assert GE._mode_target("quick") == 0.45
    assert GE._mode_target("research") == 0.75
    assert GE._next_mode("normal") == "self_consistency"  # one tier up
    assert GE._next_mode("expert") == "constitutional_ai"  # caps at top


# ── Stage 3a: per-turn gather multiplier scales memory counts ────────────────
def test_gather_multiplier_scales_memory_counts():
    from unittest.mock import patch
    from eli.cognition.agent_bus import BusMemoryAgent
    class _FM:
        db_path = "/tmp/x.sqlite3"
        def recall_memory(self, q, limit=8): return [{"id": str(i), "text": f"fact {i} research"} for i in range(limit)]
        def search_conversations(self, q, user_id=None, limit=5): return []
        def get_recent_conversation(self, limit=6, user_id=None): return []
        def get_session_summaries(self, user_id=None, limit=3): return []
    q = "tell me everything about my research and projects in depth"
    def _shown(gm):
        with patch("eli.memory.get_memory", return_value=_FM()):
            r = BusMemoryAgent().run(q, {"action": "CHAT", "_gather_mult": gm}, "s", "u")
        return (r.data or {}).get("memory_context", "").count("fact ")
    assert _shown(2.0) > _shown(1.0)  # deeper iteration gathers more


# ── Stage 3b: background-deepening gating ────────────────────────────────────
def test_background_deepen_gating():
    from unittest.mock import MagicMock, patch
    import eli.runtime.background_deepening as BD
    class _B:
        def __init__(self, g): self.grounding_confidence = g
    eng = MagicMock(); eng.session_id = "s"; eng.user_id = "u"
    class _BT:
        def submit(self, name, fn, *a, **k): return 1
    with patch("eli.runtime.background_tasks.get_background_tasks", return_value=_BT()):
        BD._INFLIGHT.clear(); BD._DONE.clear()
        assert BD.schedule(eng, "what is my research framework called", {"action": "CHAT"}, _B(0.2), "quick") is True
        BD._INFLIGHT.clear()
        assert BD.schedule(eng, "what is my research framework called", {"action": "CHAT"}, _B(0.9), "quick") is False  # high grounding
        BD._INFLIGHT.clear()
        assert BD.schedule(eng, "haha thanks pal", {"action": "CHAT"}, _B(0.1), "quick") is False  # banter
        BD._INFLIGHT.clear()
        assert BD.schedule(eng, "what is my research framework called", {"action": "CHAT"}, _B(0.2), "research") is False  # deeper mode


def test_background_deepen_kill_switch(monkeypatch):
    import eli.runtime.background_deepening as BD
    from unittest.mock import MagicMock
    monkeypatch.setenv("ELI_BACKGROUND_DEEPEN", "0")
    eng = MagicMock()
    class _B: grounding_confidence = 0.1
    BD._INFLIGHT.clear()
    assert BD.schedule(eng, "what is my research framework called", {"action": "CHAT"}, _B(), "quick") is False
