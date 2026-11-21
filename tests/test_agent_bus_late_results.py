"""Work that finishes while the bus is still waiting must be used, not thrown away;
an agent past its timeout on the default path must not hold the turn.

Live on a CPU-offloaded 27B: the memory agent produced 6,279 chars of context
1.4s past its (hardware-scaled) ~121s deadline. _collect_layer (the layered
fallback, which waits for a layer until its longest timeout plus a second)
recorded a timeout for it WITHOUT checking whether the future had since
completed, so the bus logged mem=0ch and the reply was generated with
memory_chars=0 at grounding 0.30 (low) -- after two full minutes of retrieval
had already been paid for.
"""
import threading
import time

import pytest

from eli.cognition.agent_bus import AgentBus, AgentResult


class _LateAgent:
    """Finishes just after its own deadline."""
    name = "memory"
    timeout_s = 0.2

    def run(self, user_input, intent, session_id, user_id):
        time.sleep(0.6)
        return AgentResult(agent=self.name, ok=True, confidence=0.9,
                           data={"memory_context": "REAL CONTEXT"})


class _HungAgent:
    """Never finishes inside the test; must still be recorded as a timeout."""
    name = "knowledge_graph"
    timeout_s = 0.2

    def run(self, user_input, intent, session_id, user_id):
        time.sleep(30)
        return AgentResult(agent=self.name, ok=True, confidence=0.9, data={})


def _collect(bus, agents):
    return bus._collect_layer(agents, "hi", {"action": "CHAT"}, "s1", "u1")


def test_late_but_finished_result_is_used_not_discarded():
    bus = AgentBus()
    try:
        results = {r.agent: r for r in _collect(bus, [_LateAgent()])}
    finally:
        bus._pool.shutdown(wait=False)
    r = results["memory"]
    assert r.ok, f"late-but-complete result was discarded: error={r.error!r}"
    assert r.data.get("memory_context") == "REAL CONTEXT", (
        "the agent's real context was replaced by an empty timeout record")


def test_a_genuinely_hung_agent_still_times_out():
    """The fix must not turn the deadline into a wait."""
    bus = AgentBus()
    t0 = time.perf_counter()
    try:
        results = {r.agent: r for r in _collect(bus, [_HungAgent()])}
    finally:
        bus._pool.shutdown(wait=False)
    elapsed = time.perf_counter() - t0
    assert results["knowledge_graph"].error == "timeout"
    assert elapsed < 10, f"collection waited {elapsed:.1f}s — the fix must never block"


def test_the_default_path_gives_up_on_a_hung_agent_and_the_turn_goes_on():
    """On the DAG path (the bus's default) a hung agent held its layer, and the turn, until it
    returned, and its late result was kept. Past its timeout it is given up on now, and the
    agent that depends on it (knowledge_graph waits for memory) still runs."""
    release = threading.Event()

    class _Stuck:
        name = "memory"
        timeout_s = 0.2

        def run(self, user_input, intent, session_id, user_id):
            release.wait(10)
            return AgentResult(agent=self.name, ok=True, confidence=0.9,
                               data={"memory_context": "LATE CONTEXT"})

    class _Downstream:
        name = "knowledge_graph"
        timeout_s = 2.0

        def run(self, user_input, intent, session_id, user_id):
            return AgentResult(agent=self.name, ok=True, confidence=0.5,
                               data={"saw": sorted((intent or {}).get("_upstream") or {})})

    bus = AgentBus()
    t0 = time.perf_counter()
    try:
        results = {r.agent: r for r in bus._run_agents_orchestrated(
            [_Stuck(), _Downstream()], "hi", {"action": "CHAT"}, "s1", "u1")}
        elapsed = time.perf_counter() - t0
    finally:
        release.set()
        bus._pool.shutdown(wait=False)
    assert elapsed < 5, f"the turn waited {elapsed:.1f}s on an agent with a 0.2s timeout"
    assert not results["memory"].ok and "exceeded" in str(results["memory"].error)
    assert results["knowledge_graph"].ok and results["knowledge_graph"].data["saw"] == []
