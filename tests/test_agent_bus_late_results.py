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


class _SlowAction:
    """The executor's side of an action that takes longer than the bus waits for it."""

    def __init__(self, seconds):
        self.seconds, self.runs, self.ended = seconds, [], threading.Event()

    def __call__(self, action, args=None, *a, **k):
        self.runs.append((str(action).upper(), dict(args or {})))
        time.sleep(self.seconds)
        self.ended.set()
        return {"ok": True, "action": str(action).upper(), "content": "Timer set for 25 minutes.",
                "response": "Timer set for 25 minutes."}


@pytest.fixture()
def told(monkeypatch):
    """What the job manager tells whoever listens when a job ends (the person, through
    background_tasks._tell_the_person), from a manager of the test's own."""
    from eli.runtime import background_tasks as bt
    jobs = bt.BackgroundTasks()
    monkeypatch.setattr(bt, "get_background_tasks", lambda: jobs)
    heard = []
    jobs.add_listener(heard.append)
    return jobs, heard


# The layered fallback waits for a layer until its longest timeout plus a second.
@pytest.mark.parametrize("path,seconds", [("_run_agents_orchestrated", 0.8), ("_run_agents_layered", 1.8)])
def test_an_action_the_bus_stops_waiting_for_goes_on_as_a_job_and_its_end_is_reported(
        monkeypatch, told, path, seconds):
    """The system agent carries out the action itself. Past its timeout the bus recorded an empty
    failure while the action went on and finished unseen: the turn was answered with "my reply
    came out garbled" for a timer that was then set, and a second ask set it twice. The bus now
    hands the running action to a job: the turn's record says it is still running as that job, it
    runs once, and when it ends its result is the job's and the person is told."""
    from eli.cognition.agent_bus import SystemAgent
    from eli.execution import executor_enhanced

    jobs, heard = told
    slow = _SlowAction(seconds)
    monkeypatch.setattr(executor_enhanced, "execute", slow)
    agent = SystemAgent()
    agent.timeout_s = 0.2
    intent = {"action": "SET_TIMER", "args": {"duration": 1500}}
    bus = AgentBus()
    try:
        t0 = time.perf_counter()
        results = {r.agent: r for r in getattr(bus, path)([agent], "set a timer for 25 minutes",
                                                          intent, "s1", "u1")}
        waited = time.perf_counter() - t0
    finally:
        bus._pool.shutdown(wait=False)
    record = results["system"].data
    assert waited < slow.seconds, f"the bus waited {waited:.1f}s for the action"
    assert record.get("still_running") is True and record["action"] == "SET_TIMER"
    job = jobs.get(record["job"])
    assert job["status"] == "running" and f"job {record['job']}" in record["content"]
    assert slow.ended.wait(5)
    deadline = time.time() + 5
    while not heard and time.time() < deadline:
        time.sleep(0.02)
    assert [j["id"] for j in heard] == [record["job"]]
    assert heard[0]["status"] == "done" and heard[0]["result"]["content"] == "Timer set for 25 minutes."
    assert slow.runs == [("SET_TIMER", {"duration": 1500})], "the action ran more than once"


def test_a_turn_whose_action_is_still_running_says_so_and_never_runs_it_again(monkeypatch, told):
    """What the user is told is what is true: the action is still running as a job. The empty
    failed record the bus used to leave was logged as a failure, re-planned into another action
    for the same goal (doing it twice) and answered with a garbled-reply apology."""
    from eli.cognition import agent_bus
    from eli.execution import executor_enhanced
    from eli.kernel import engine as engine_mod

    jobs, heard = told
    slow = _SlowAction(0.8)
    monkeypatch.setattr(executor_enhanced, "execute", slow)
    monkeypatch.setattr(engine_mod, "execute_action", slow)
    for a in agent_bus._ALL_AGENTS:
        if a.name in ("system", "plugin"):
            monkeypatch.setattr(a, "timeout_s", 0.2)
    replans = []
    monkeypatch.setattr(engine_mod.CognitiveEngine, "_eli_tool_failure_replan",
                        lambda self, *a, **k: replans.append(a) or a[-1])
    eng = engine_mod.CognitiveEngine()
    out = eng.process("set a timer for 25 minutes")
    assert out.get("action") == "SET_TIMER"
    jid = next(j["id"] for j in jobs.list())
    assert f"job {jid}" in out["content"] and "not finished" in out["content"], out["content"]
    assert slow.ended.wait(5)
    deadline = time.time() + 5
    while not heard and time.time() < deadline:
        time.sleep(0.02)
    assert heard and heard[0]["status"] == "done"
    assert slow.runs == [("SET_TIMER", {"duration": 1500})], "the action ran more than once"
    assert replans == [], "a still-running action was re-planned"
