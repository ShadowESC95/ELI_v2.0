"""Work that finishes late must be used, not thrown away.

Live on a CPU-offloaded 27B: the memory agent produced 6,279 chars of context
1.4s past its (hardware-scaled) ~121s deadline. _collect_layer recorded a
timeout for it WITHOUT checking whether the future had since completed, so the
bus logged mem=0ch and the reply was generated with memory_chars=0 at
grounding 0.30 (low) -- after two full minutes of retrieval had already been
paid for.
"""
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
