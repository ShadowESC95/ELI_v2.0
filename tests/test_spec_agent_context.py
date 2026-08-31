"""Custom spec agents inject evidence into LLM context like built-in agents."""
from __future__ import annotations

import pytest

from eli.cognition.agent_bus import AgentResult, DispatchResult
from eli.cognition.agent_spec import (
    AgentSpec, SuccessCheck, Trigger, prefill_from_legacy_wizard, save_spec,
)


def test_custom_agent_content_reaches_context_block():
    dr = DispatchResult(intent_action="CHAT", intent_confidence=0.9)
    dr.agent_results.append(AgentResult(
        agent="grant_writer",
        ok=True,
        confidence=0.85,
        data={
            "content": "The programme targets fifteen electrolysis models.",
            "objective": "Draft funding-application text grounded in evidence.",
        },
    ))
    block = dr.to_context_block()
    assert "grant_writer" in block.lower() or "Custom agent" in block
    assert "fifteen electrolysis" in block


def test_code_agent_memory_context_reaches_context_block():
    dr = DispatchResult(intent_action="CHAT", intent_confidence=0.9)
    dr.agent_results.append(AgentResult(
        agent="weather_helper",
        ok=True,
        confidence=0.7,
        data={"memory_context": "Agent weather_helper matched: rain expected Tuesday."},
    ))
    block = dr.to_context_block()
    assert "rain expected Tuesday" in block


def test_legacy_wizard_prefill_produces_valid_spec():
    data = prefill_from_legacy_wizard(
        "WeatherAgent — forecast local conditions",
        "keywords: weather, rain, forecast",
        "brief bullet points",
    )
    assert data["id"] == "weatheragent"
    assert len(data["triggers"]) >= 1
    assert data["success_criteria"]
    assert len(data["objective"]) >= 25
    assert len(data["system_prompt"]) >= 40


@pytest.fixture
def isolated_specs(tmp_path, monkeypatch):
    monkeypatch.setenv("ELI_AGENT_SPECS_DIR", str(tmp_path / "specs"))
    from eli.core import paths
    for fn in ("data_dir", "config_dir", "cache_dir"):
        f = getattr(paths, fn, None)
        if hasattr(f, "cache_clear"):
            f.cache_clear()
    yield tmp_path


def test_spec_agent_reload_after_save(isolated_specs, monkeypatch):
    import eli.cognition.agent_bus as AB

    monkeypatch.setattr(AB, "_AGENT_LOAD_REPORT", [], raising=False)
    snapshot = [a for a in AB._ALL_AGENTS if not isinstance(a, AB.SpecAgent)]

    spec = AgentSpec(
        id="notes_helper",
        name="Notes Helper",
        objective="Summarise the user's notes into actionable bullet points.",
        system_prompt="You summarise notes into clear bullet points without inventing tasks.",
        triggers=[Trigger(kind="keyword", value="notes")],
        success_criteria=[SuccessCheck(kind="non_empty")],
        permissions=["model_access"],
        enabled=True,
    )
    assert save_spec(spec)["ok"]

    AB._ALL_AGENTS[:] = list(snapshot)
    AB.reload_custom_agents()
    loaded = next((a for a in AB._ALL_AGENTS if a.name == "notes_helper"), None)
    assert loaded is not None
    assert getattr(loaded, "_custom", False) is True
    assert loaded.spec.objective.startswith("Summarise")
