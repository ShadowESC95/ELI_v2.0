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
