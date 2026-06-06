"""Custom-agent integration: a created agent is loaded on boot, tagged _custom
(so dispatch reaches it), and trust is recorded for persistence.

Deterministic; loads a temp agent file via the trust-bypass path and restores
the global agent list afterwards.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

import eli.cognition.agent_bus as AB


_AGENT_SRC = '''
from __future__ import annotations
from typing import Any, Dict
from eli.cognition.agent_bus import _BaseAgent, AgentResult


class TempTestAgent(_BaseAgent):
    name = "temp_test_agent"
    timeout_s = 5.0
    _triggers_info = "frobnicate widget"

    def run(self, user_input: str, intent: Dict[str, Any], session_id: str, user_id: str) -> AgentResult:
        low = user_input.lower()
        if "frobnicate" not in low:
            return AgentResult(agent=self.name, ok=True, confidence=0.0, data={"skipped": True})
        return AgentResult(agent=self.name, ok=True, confidence=0.7,
                           data={"memory_context": "frobnicated"})


def _register():
    from eli.cognition.agent_bus import _ALL_AGENTS
    if not any(a.name == "temp_test_agent" for a in _ALL_AGENTS):
        _ALL_AGENTS.append(TempTestAgent())


_register()
'''


@pytest.fixture
def custom_agent_dir(tmp_path, monkeypatch):
    d = tmp_path / "custom"
    d.mkdir()
    (d / "temp_test_agent.py").write_text(_AGENT_SRC, encoding="utf-8")
    monkeypatch.setenv("ELI_CUSTOM_AGENTS_DIR", str(d))
    monkeypatch.setenv("ELI_TRUST_ALL_AGENTS", "1")  # bypass trust for the load test
    snapshot = list(AB._ALL_AGENTS)
    yield d
    # restore global agent list
    AB._ALL_AGENTS[:] = snapshot


def test_custom_agent_loads_and_is_tagged(custom_agent_dir):
    AB._load_custom_agents()
    agent = next((a for a in AB._ALL_AGENTS if a.name == "temp_test_agent"), None)
    assert agent is not None, "custom agent was not loaded on boot"
    assert getattr(agent, "_custom", False) is True, "custom agent must be tagged _custom for dispatch"


def test_custom_agent_included_in_dispatch_selection(custom_agent_dir):
    AB._load_custom_agents()
    # Simulate the dispatch selection: a built-in selection that does NOT name the
    # custom agent must still include it because it's tagged _custom.
    selected_names = {"memory", "knowledge_graph"}
    custom_names = {
        a.name for a in AB._ALL_AGENTS
        if getattr(a, "_custom", False) and getattr(a, "_enabled", True)
    }
    plan_names = set(selected_names) | custom_names
    assert "temp_test_agent" in plan_names


def test_trust_round_trip(tmp_path, monkeypatch):
    # _trust_custom_agent records a sha into config_dir/trusted_agents.json.
    import types
    fake_cfg = tmp_path / "config"
    fake_cfg.mkdir()
    # _trust_custom_agent + the registry read both call eli.core.paths.get_paths;
    # point config_dir at a temp dir so the real config isn't touched.
    import eli.core.paths as P
    monkeypatch.setattr(P, "get_paths", lambda: types.SimpleNamespace(config_dir=fake_cfg))

    f = tmp_path / "myagent.py"
    f.write_text("# agent\n", encoding="utf-8")
    AB._trust_custom_agent(f)
    reg = AB._get_trusted_agents_registry()
    assert "myagent.py" in reg
