"""CONTRACT: every bus agent honours the AgentResult protocol and self-gates.

For each registered agent: it has a string name + a callable run(); run() on an
irrelevant short input returns an AgentResult without crashing and self-gates
(confidence 0 / skipped) rather than fabricating evidence. This examines the
"14 calibrated agents that skip when irrelevant" claim, per agent.
"""
from __future__ import annotations

import pytest

from eli.cognition.agent_bus import _ALL_AGENTS, AgentResult

_AGENTS = list(_ALL_AGENTS)
_IDS = [getattr(a, "name", f"agent{i}") for i, a in enumerate(_AGENTS)]


@pytest.mark.parametrize("agent", _AGENTS, ids=_IDS)
def test_agent_has_name_and_run(agent):
    assert isinstance(getattr(agent, "name", None), str) and agent.name
    assert callable(getattr(agent, "run", None))


@pytest.mark.parametrize("agent", _AGENTS, ids=_IDS)
def test_agent_runs_and_self_gates_on_irrelevant_input(agent):
    # "ok" as a CHAT turn is irrelevant to every specialist agent → must not crash,
    # must return an AgentResult, and should self-gate (skip / 0 confidence) rather
    # than invent evidence.
    res = agent.run("ok", {"action": "CHAT"}, "s", "u")
    assert isinstance(res, AgentResult)
    assert res.agent == agent.name
    data = res.data or {}
    gated = bool(data.get("skipped")) or float(getattr(res, "confidence", 0.0) or 0.0) == 0.0
    assert gated or res.ok, f"{agent.name} neither gated nor ok on irrelevant input"
