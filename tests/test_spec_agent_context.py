"""Custom spec agents inject evidence into LLM context like built-in agents."""
from __future__ import annotations

import threading
import time

import pytest

from eli.cognition.agent_bus import AgentResult, DispatchResult
from eli.cognition.agent_spec import (
    AgentSpec, SuccessCheck, Trigger, save_spec,
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


class _LoadedModel:
    """Stands in for gguf_inference behind the real broker; records each generation's budget."""

    def __init__(self):
        self.budgets = []

    def is_loaded(self):
        return True

    def is_background_inference(self):
        return False

    def set_background_inference(self, flag):
        pass

    def is_shutting_down(self):
        return False

    def generate(self, prompt, system="", max_tokens=0, temperature=0.0, top_p=0.0, stream=False):
        self.budgets.append(max_tokens)
        yield "High tide is at noon."


def test_a_spec_agent_in_the_users_turn_is_heard_and_one_outside_it_stays_background(monkeypatch):
    """It called the model as background work from inside the user's turn. The broker returns ""
    to background work while a turn has just used the model, which in a conversation is always,
    and caps it at 256 tokens, so a custom agent added nothing to the reply."""
    import eli.cognition.agent_bus as AB
    from eli.cognition import inference_broker as ib
    from eli.kernel import request_context as rc

    model = _LoadedModel()
    broker = ib.InferenceBroker.__new__(ib.InferenceBroker)
    broker._lock, broker._gguf, broker._load_error = threading.Lock(), model, None
    monkeypatch.setattr(ib, "get_inference_broker", lambda: broker)
    monkeypatch.setattr(ib, "_last_foreground_ts", time.monotonic())     # a turn has just started
    monkeypatch.setattr(ib, "_last_foreground_duration", 0.0)
    agent = AB.SpecAgent(AgentSpec(
        id="tide_helper", name="Tide Helper",
        objective="Answer questions about tide times from the user's saved tables.",
        system_prompt="You read tide tables and answer with the time of the next high or low tide.",
        triggers=[Trigger(kind="keyword", value="tide")],
        success_criteria=[SuccessCheck(kind="non_empty")], max_tokens=600, enabled=True))

    token = rc.turn_facts_var.set({"user_input": "when is high tide", "autonomous": False})
    try:
        in_turn = agent.run("when is high tide", {"action": "CHAT"}, "s1", "u1")
    finally:
        rc.turn_facts_var.reset(token)
    assert in_turn.ok and in_turn.data["content"] == "High tide is at noon."
    assert model.budgets == [600]          # its own budget, not the background cap

    outside = agent.run("when is high tide", {"action": "CHAT"}, "s1", "u1")
    assert not outside.ok and model.budgets == [600]   # deferred: a turn just used the model
