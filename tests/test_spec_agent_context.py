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


class _Llama:
    """Stands in for llama_cpp.Llama under the real gguf_inference path: one token per step,
    its stopping criteria read before each, as llama.cpp does."""

    def __init__(self, tokens, step):
        self.tokens, self.step, self.made = tokens, step, 0
        self.n_batch = 512

    def n_ctx(self):
        return 4096

    def tokenize(self, text, add_bos=True, special=False):
        return list(range(max(1, len(text) // 4)))

    def detokenize(self, ids):
        return b"tide " * len(ids)

    def __call__(self, prompt, max_tokens=16, stopping_criteria=None, stream=False, **kw):
        ids = []
        for i in range(min(self.tokens, max_tokens)):
            if stopping_criteria is not None and any(stop(ids, None) for stop in stopping_criteria):
                break
            time.sleep(self.step)
            ids.append(i)
            self.made += 1
        return {"choices": [{"text": "tide " * len(ids), "finish_reason": "length"}]}


def test_a_spec_agent_call_the_bus_gives_up_on_gives_the_model_back_to_the_reply(monkeypatch):
    """Its model call is the turn's own work, so it ran in the foreground, and past its timeout the
    bus stopped waiting while the call went on holding the model: the reply then waited for an
    answer nobody would read. Once the bus gives up, the call stops at its next token, and the
    broker does not ask again."""
    import eli.cognition.agent_bus as AB
    from eli.cognition import gguf_inference as gi
    from eli.cognition import inference_broker as ib
    from eli.kernel import request_context as rc

    step = 0.02
    llm = _Llama(tokens=150, step=step)
    monkeypatch.setattr(gi, "_llm", llm)
    broker = ib.InferenceBroker()
    monkeypatch.setattr(ib, "get_inference_broker", lambda: broker)
    agent = AB.SpecAgent(AgentSpec(
        id="tide_helper", name="Tide Helper",
        objective="Answer questions about tide times from the user's saved tables.",
        system_prompt="You read tide tables and answer with the time of the next high or low tide.",
        triggers=[Trigger(kind="keyword", value="tide")],
        success_criteria=[SuccessCheck(kind="non_empty")], max_tokens=600, timeout_s=0.3, enabled=True))
    bus = AB.AgentBus()
    token = rc.turn_facts_var.set({"user_input": "when is high tide", "autonomous": False})
    try:
        results = bus._run_agents_orchestrated([agent], "when is high tide", {"action": "CHAT"}, "s1", "u1")
        t0 = time.perf_counter()
        assert gi._LLM_CALL_LOCK.acquire(timeout=10)       # the reply's turn at the model
        lock_wait = time.perf_counter() - t0
        gi._LLM_CALL_LOCK.release()
    finally:
        rc.turn_facts_var.reset(token)
        bus._pool.shutdown(wait=False)
    assert not results[0].ok and "exceeded" in str(results[0].error)
    whole_call = llm.tokens * step
    assert lock_wait < whole_call / 3, f"the reply waited {lock_wait:.2f}s for a call nobody was waiting for"
    time.sleep(0.2)
    assert llm.made < llm.tokens, "the given-up call ran to the end of its budget"
