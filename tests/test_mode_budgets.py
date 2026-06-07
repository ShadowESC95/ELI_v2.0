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
    def fake_redispatch(engine, ui, intent, reasoning_mode=None):
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
