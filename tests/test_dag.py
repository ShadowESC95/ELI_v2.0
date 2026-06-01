"""Tests for the project-wide DAG engine, the DAG-layered agent bus, and the
coding subtask DAG. All deterministic — no model required."""

import os

import pytest

from eli.core.dag import DAG, DAGCycleError, build_dag


# ── generic DAG engine ──────────────────────────────────────────────────────

def test_linear_chain_layers():
    g = build_dag({"A": [], "B": ["A"], "C": ["B"]})
    assert g.topological_order() == ["A", "B", "C"]
    assert g.topological_layers() == [["A"], ["B"], ["C"]]
    assert g.critical_path_length() == 3


def test_diamond_layers_and_closure():
    g = build_dag({"A": [], "B": ["A"], "C": ["A"], "D": ["B", "C"]})
    assert g.topological_layers() == [["A"], ["B", "C"], ["D"]]
    assert g.ancestors("D") == {"A", "B", "C"}
    assert g.descendants("A") == {"B", "C", "D"}


def test_independent_nodes_single_layer():
    # The agent-bus default case: no edges ⇒ one parallel layer.
    g = build_dag({"x": [], "y": [], "z": []})
    assert g.topological_layers() == [["x", "y", "z"]]


def test_cycle_detected():
    g = DAG()
    g.add_edge("A", "B")
    g.add_edge("B", "A")
    with pytest.raises(DAGCycleError):
        g.topological_order()
    with pytest.raises(DAGCycleError):
        g.topological_layers()


def test_build_dag_ignores_out_of_subset_deps():
    # build_dag must drop deps not in the provided node set (global-map safety).
    g = build_dag({"memory": [], "knowledge_graph": ["memory", "not_selected"]})
    assert g.topological_layers() == [["memory"], ["knowledge_graph"]]


# ── DAG-layered agent bus ───────────────────────────────────────────────────

def test_agent_bus_layered_dispatch_and_upstream():
    os.environ.setdefault("ELI_TRUST_ALL_AGENTS", "1")
    from eli.cognition.agent_bus import AgentBus, _BaseAgent, AgentResult, _agent_execution_layers

    order = []

    class FakeMemory(_BaseAgent):
        name = "memory"; timeout_s = 3.0
        def run(self, u, intent, s, uid):
            order.append("memory")
            return AgentResult(agent="memory", ok=True, confidence=0.5,
                               data={"results": [{"text": "user works on physics"}]})

    class FakeKG(_BaseAgent):
        name = "knowledge_graph"; timeout_s = 3.0
        saw = None
        def run(self, u, intent, s, uid):
            order.append("knowledge_graph")
            FakeKG.saw = (intent or {}).get("_upstream", {}).get("memory")
            return AgentResult(agent="knowledge_graph", ok=True, confidence=0.4, data={"memory_context": "kg"})

    # memory in layer 0, knowledge_graph (depends on memory) in layer 1
    assert _agent_execution_layers(["memory", "knowledge_graph"]) == [["memory"], ["knowledge_graph"]]

    bus = AgentBus(max_workers=4)
    try:
        res = bus._run_agents_layered([FakeMemory(), FakeKG()], "who am i",
                                      {"action": "CHAT"}, "sess", "user")
        names = [r.agent for r in res]
        assert set(names) == {"memory", "knowledge_graph"}
        assert order.index("memory") < order.index("knowledge_graph")
        assert FakeKG.saw and "results" in FakeKG.saw     # upstream propagated
    finally:
        bus.shutdown()


def test_agent_layers_independent_is_single_layer():
    from eli.cognition.agent_bus import _agent_execution_layers
    assert _agent_execution_layers(["reflection", "habit", "voice"]) == [["habit", "reflection", "voice"]]


# ── coding subtask DAG ──────────────────────────────────────────────────────

def test_coding_plan_graph_topo_solve_and_compose():
    from eli.coding.plan_graph import solve_dag

    def gen(prompt, system="", **k):
        p = prompt.lower()
        if "dependency graph" in p or "decompose software" in p:
            return ('{"nodes":[{"id":"helper","task":"implement square(x)","depends_on":[]},'
                    '{"id":"main","task":"run() using square","depends_on":["helper"]}]}')
        return ""

    class R:
        def __init__(self, code, score=0.9):
            self.code = code; self.score = score

    seen = []
    def solver(node_task):
        seen.append(node_task)
        if "already-built component" in node_task:
            return R("def run():\n    return square(5)\n")
        return R("def square(x):\n    return x * x\n")

    res = solve_dag("Build square(x) and a runner", gen, language="python", single_solver=solver)
    assert res is not None and res.used_dag
    assert res.order == ["helper", "main"]
    assert "def square" in res.combined_code and "def run" in res.combined_code
    assert any("already-built component" in s for s in seen)


def test_compose_keeps_indented_imports_in_body():
    """Regression: a function-local (indented) import must NOT be hoisted to the
    module top (that produced an IndentationError in a shipped script). The
    composed module must parse."""
    import ast
    from eli.coding.plan_graph import compose
    solutions = {
        "1": "import time\n\ndef a():\n    return time.time()\n",
        "2": "def b():\n        from itertools import product\n        return list(product([1], [2]))\n",
    }
    out = compose(["1", "2"], solutions)
    ast.parse(out)  # must not raise IndentationError
    assert "\nimport time" in ("\n" + out)          # top-level import hoisted
    assert "        from itertools import product" in out  # local import stays indented in body


def test_broken_candidate_never_wins():
    from eli.coding.verification import Candidate, score_candidate
    broken = Candidate(code="    x = 1"); broken.syntax_ok = False
    valid = Candidate(code="def f():\n    return 1\n"); valid.syntax_ok = True
    assert score_candidate(broken) <= 0.05 < score_candidate(valid)


def test_coding_single_node_returns_none():
    from eli.coding.plan_graph import solve_dag

    def gen(prompt, system="", **k):
        return '{"nodes":[{"id":"root","task":"add(a,b)","depends_on":[]}]}'

    class R:
        code = "def add(a,b): return a+b"
        score = 0.9

    assert solve_dag("add two numbers", gen, language="python", single_solver=lambda t: R()) is None
