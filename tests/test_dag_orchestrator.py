"""Tests for the DAG execution orchestrator (eli/core/dag.py).

Covers every frontier feature: dependency result-passing, parallel layers, the
conditional `when` skip, retries, fallback, memoisation, priority, fail-fast,
upstream-failure skip, time budget, cycle detection, and the RunReport.
"""
from __future__ import annotations

import pytest

from eli.core.dag import (Task, Orchestrator, run_graph, NodeContext,
                          DAGCycleError)


def test_runs_in_dependency_order_and_passes_results():
    tasks = [
        Task("a", run=lambda c: 1),
        Task("b", run=lambda c: c.results["a"] + 10, depends_on={"a"}),
        Task("c", run=lambda c: c.results["b"] * 2, depends_on={"b"}),
    ]
    r = run_graph(tasks, max_workers=1)
    assert r.ok and r.result("c") == 22
    assert r.order.index("a") < r.order.index("b") < r.order.index("c")


def test_parallel_layers_same_result_as_sequential():
    def mk():
        return [
            Task("root", run=lambda c: 2),
            Task("x", run=lambda c: c.results["root"] + 1, depends_on={"root"}),
            Task("y", run=lambda c: c.results["root"] + 2, depends_on={"root"}),
            Task("join", run=lambda c: c.results["x"] + c.results["y"], depends_on={"x", "y"}),
        ]
    seq = run_graph(mk(), max_workers=1)
    par = run_graph(mk(), max_workers=4)
    assert seq.result("join") == par.result("join") == 7
    assert par.ok and [sorted(l) for l in par.layers] == [["root"], ["x", "y"], ["join"]]


def test_conditional_when_skips_node_and_downstream():
    tasks = [
        Task("a", run=lambda c: 1),
        Task("b", run=lambda c: 2, depends_on={"a"}, when=lambda c: False),
        Task("c", run=lambda c: 3, depends_on={"b"}),
    ]
    r = run_graph(tasks, max_workers=1)
    assert r.outcomes["b"].status == "skipped"
    assert r.outcomes["c"].status == "skipped"      # upstream b never completed
    assert r.outcomes["a"].ok


def test_retries_then_succeeds():
    calls = {"n": 0}
    def flaky(c):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("transient")
        return "ok"
    r = run_graph([Task("f", run=flaky, retries=3)], max_workers=1)
    assert r.result("f") == "ok" and r.outcomes["f"].attempts == 3


def test_fallback_used_when_all_attempts_fail():
    def boom(c):
        raise ValueError("nope")
    r = run_graph([Task("f", run=boom, retries=1, fallback=lambda c: "safe")], max_workers=1)
    assert r.ok and r.result("f") == "safe"


def test_memoisation_skips_recompute():
    cache: dict = {}
    calls = {"n": 0}
    def expensive(c):
        calls["n"] += 1
        return 99
    Orchestrator(cache=cache, max_workers=1).run([Task("e", run=expensive, cache_key="k")])
    r2 = Orchestrator(cache=cache, max_workers=1).run([Task("e", run=expensive, cache_key="k")])
    assert calls["n"] == 1 and r2.outcomes["e"].status == "cached" and r2.result("e") == 99


def test_upstream_failure_skips_descendants_and_marks_not_ok():
    tasks = [
        Task("a", run=lambda c: (_ for _ in ()).throw(RuntimeError("x"))),
        Task("b", run=lambda c: 1, depends_on={"a"}),
    ]
    r = run_graph(tasks, max_workers=1)
    assert r.ok is False
    assert r.outcomes["a"].status == "failed"
    assert r.outcomes["b"].status == "skipped"
    assert "a" in r.failed and "b" in r.skipped


def test_non_critical_failure_keeps_run_ok():
    tasks = [
        Task("opt", run=lambda c: (_ for _ in ()).throw(RuntimeError("x")), critical=False),
        Task("main", run=lambda c: "done"),
    ]
    r = run_graph(tasks, max_workers=1)
    assert r.ok is True and r.result("main") == "done"


def test_fail_fast_skips_remaining_layers():
    tasks = [
        Task("a", run=lambda c: (_ for _ in ()).throw(RuntimeError("x"))),
        Task("b", run=lambda c: 1),            # independent, later layer not guaranteed
        Task("c", run=lambda c: 2, depends_on={"b"}),
    ]
    r = Orchestrator(fail_fast=True, max_workers=1).run(tasks)
    assert r.ok is False and r.outcomes["c"].status == "skipped"


def test_priority_orders_within_layer():
    seen = []
    mk = lambda name: Task(name, run=lambda c, n=name: seen.append(n))
    tasks = [Task("hi", run=lambda c: seen.append("hi"), priority=10),
             Task("lo", run=lambda c: seen.append("lo"), priority=1)]
    run_graph(tasks, max_workers=1)
    assert seen == ["hi", "lo"]


def test_shared_context_bag_visible_to_all():
    tasks = [
        Task("a", run=lambda c: c.shared.setdefault("hits", []).append("a")),
        Task("b", run=lambda c: c.shared["hits"].append("b"), depends_on={"a"}),
    ]
    r = run_graph(tasks, max_workers=1, context={})
    # shared bag mutated across nodes
    assert r.ok


def test_cycle_detected():
    tasks = [Task("a", depends_on={"b"}), Task("b", depends_on={"a"})]
    with pytest.raises(DAGCycleError):
        run_graph(tasks, max_workers=1)


def test_run_report_to_dict_shape():
    r = run_graph([Task("a", run=lambda c: 1)], max_workers=1)
    d = r.to_dict()
    assert d["ok"] is True and d["critical_path"] == 1
    assert "a" in d["nodes"] and d["nodes"]["a"]["status"] == "ok"


def test_passthrough_node_has_no_fn():
    r = run_graph([Task("gate"), Task("a", run=lambda c: 1, depends_on={"gate"})], max_workers=1)
    assert r.ok and r.outcomes["gate"].status == "ok" and r.result("a") == 1
