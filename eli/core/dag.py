"""Generic directed-acyclic-graph engine — shared scheduling primitive.

Project-wide foundation for dependency-aware execution. Used by:
  - the agent bus (agents as nodes, run in topological layers so a downstream
    agent can consume an upstream agent's output)
  - the coding engine (subtasks as nodes, solved in dependency order)
  - anywhere else that needs ordered/parallel scheduling with cycle safety.

Pure and deterministic — no LLM, no I/O — so it is fully unit-testable and
cheap. The "DAG metrics/params/algorithm" live here: topological order (Kahn),
parallel layering, cycle detection, ancestor/descendant closure, and
critical-path depth.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Set


class DAGError(Exception):
    """Base error for DAG construction/validation."""


class DAGCycleError(DAGError):
    """Raised when the graph contains a cycle (so it isn't a DAG)."""


@dataclass
class DAGNode:
    id: str
    payload: Any = None
    depends_on: Set[str] = field(default_factory=set)   # ids this node needs first

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "depends_on": sorted(self.depends_on)}


class DAG:
    """A directed acyclic graph of identified nodes with `depends_on` edges.

    Edge semantics: if B depends_on A, then A must complete before B (A → B).
    """

    def __init__(self) -> None:
        self._nodes: Dict[str, DAGNode] = {}

    # ── construction ─────────────────────────────────────────────────────────
    def add_node(self, node_id: str, payload: Any = None,
                 depends_on: Optional[Iterable[str]] = None) -> DAGNode:
        node_id = str(node_id)
        if node_id in self._nodes:
            # merge dependencies / payload rather than clobbering
            if payload is not None:
                self._nodes[node_id].payload = payload
            if depends_on:
                self._nodes[node_id].depends_on |= {str(d) for d in depends_on}
            return self._nodes[node_id]
        n = DAGNode(id=node_id, payload=payload, depends_on={str(d) for d in (depends_on or ())})
        self._nodes[node_id] = n
        return n

    def add_edge(self, frm: str, to: str) -> None:
        """`frm` must complete before `to` (i.e. `to` depends_on `frm`)."""
        frm, to = str(frm), str(to)
        if frm == to:
            raise DAGError(f"self-loop on node {frm!r}")
        self.add_node(frm)
        self.add_node(to)
        self._nodes[to].depends_on.add(frm)

    # ── access ───────────────────────────────────────────────────────────────
    def __contains__(self, node_id: str) -> bool:
        return str(node_id) in self._nodes

    def __len__(self) -> int:
        return len(self._nodes)

    def nodes(self) -> List[DAGNode]:
        return list(self._nodes.values())

    def node_ids(self) -> List[str]:
        return list(self._nodes.keys())

    def get(self, node_id: str) -> Optional[DAGNode]:
        return self._nodes.get(str(node_id))

    # ── validation ─────────────────────────────────────────────────────────--
    def missing_dependencies(self) -> Dict[str, Set[str]]:
        """Map node → deps that reference ids not in the graph."""
        out: Dict[str, Set[str]] = {}
        for n in self._nodes.values():
            missing = {d for d in n.depends_on if d not in self._nodes}
            if missing:
                out[n.id] = missing
        return out

    def validate(self, *, strict_edges: bool = True) -> None:
        """Raise on dangling edges (when strict) or on a cycle."""
        if strict_edges:
            miss = self.missing_dependencies()
            if miss:
                raise DAGError(f"edges reference unknown nodes: {miss}")
        self.topological_order()  # raises DAGCycleError on a cycle

    # ── algorithms ─────────────────────────────────────────────────────────--
    def _indegree(self) -> Dict[str, int]:
        # Only count deps that exist in the graph (tolerate dangling unless validated).
        indeg = {nid: 0 for nid in self._nodes}
        for n in self._nodes.values():
            for d in n.depends_on:
                if d in self._nodes:
                    indeg[n.id] += 1
        return indeg

    def _dependents(self) -> Dict[str, List[str]]:
        dep: Dict[str, List[str]] = {nid: [] for nid in self._nodes}
        for n in self._nodes.values():
            for d in n.depends_on:
                if d in self._nodes:
                    dep[d].append(n.id)
        return dep

    def topological_order(self) -> List[str]:
        """Kahn's algorithm. Deterministic (sorted ties). Raises on a cycle."""
        indeg = self._indegree()
        dependents = self._dependents()
        ready = deque(sorted([nid for nid, d in indeg.items() if d == 0]))
        order: List[str] = []
        while ready:
            nid = ready.popleft()
            order.append(nid)
            for m in sorted(dependents[nid]):
                indeg[m] -= 1
                if indeg[m] == 0:
                    ready.append(m)
            ready = deque(sorted(ready))
        if len(order) != len(self._nodes):
            stuck = sorted(set(self._nodes) - set(order))
            raise DAGCycleError(f"cycle detected; unresolved nodes: {stuck}")
        return order

    def topological_layers(self) -> List[List[str]]:
        """Group nodes into layers runnable in parallel: layer k holds all nodes
        whose dependencies are all in layers < k. Deterministic (sorted)."""
        indeg = self._indegree()
        dependents = self._dependents()
        layers: List[List[str]] = []
        remaining = set(self._nodes)
        current = sorted([nid for nid in remaining if indeg[nid] == 0])
        while current:
            layers.append(current)
            nxt_ready: Set[str] = set()
            for nid in current:
                remaining.discard(nid)
                for m in dependents[nid]:
                    indeg[m] -= 1
                    if indeg[m] == 0:
                        nxt_ready.add(m)
            current = sorted(nxt_ready)
        if remaining:
            raise DAGCycleError(f"cycle detected; unresolved nodes: {sorted(remaining)}")
        return layers

    def ancestors(self, node_id: str) -> Set[str]:
        """All nodes that must complete before `node_id` (transitive deps)."""
        node_id = str(node_id)
        seen: Set[str] = set()
        stack = list(self._nodes[node_id].depends_on) if node_id in self._nodes else []
        while stack:
            d = stack.pop()
            if d in seen or d not in self._nodes:
                continue
            seen.add(d)
            stack.extend(self._nodes[d].depends_on)
        return seen

    def descendants(self, node_id: str) -> Set[str]:
        """All nodes that (transitively) depend on `node_id`."""
        node_id = str(node_id)
        dependents = self._dependents()
        seen: Set[str] = set()
        stack = list(dependents.get(node_id, []))
        while stack:
            d = stack.pop()
            if d in seen:
                continue
            seen.add(d)
            stack.extend(dependents.get(d, []))
        return seen

    def critical_path_length(self) -> int:
        """Longest dependency chain (number of nodes) — the minimum number of
        sequential layers; a parallelism/scheduling metric."""
        return len(self.topological_layers())

    def to_dict(self) -> Dict[str, Any]:
        try:
            layers = self.topological_layers()
            acyclic = True
        except DAGCycleError:
            layers, acyclic = [], False
        return {
            "nodes": [n.to_dict() for n in self._nodes.values()],
            "acyclic": acyclic,
            "layers": layers,
            "critical_path": len(layers),
        }


def build_dag(dependencies: Dict[str, Iterable[str]]) -> DAG:
    """Convenience: build a DAG from {node: [deps...]} (deps restricted to the
    keys present, so callers can pass a global map and a node subset safely)."""
    g = DAG()
    keys = set(dependencies)
    for nid in dependencies:
        g.add_node(nid)
    for nid, deps in dependencies.items():
        for d in deps:
            if d in keys:
                g.add_edge(d, nid)
    return g


# ════════════════════════════════════════════════════════════════════════════
# Execution orchestrator — turns the scheduling DAG above into a runnable graph.
#
# Frontier features, all opt-in per task and behaviour-preserving by default:
#   • parallel execution of independent nodes per topological layer (threads)
#   • dependency result-passing (each node sees its upstream outputs + a shared bag)
#   • conditional nodes (`when` predicate) — skip a branch dynamically
#   • per-node retries with exponential backoff, and a fallback function
#   • per-node total timeout (best-effort; threads can't be force-killed)
#   • memoisation via a pluggable cache keyed by `cache_key`
#   • priority scheduling within a ready layer
#   • fail-fast and a global time budget; automatic skip of nodes whose upstream
#     did not produce a result
#   • a full, deterministic RunReport (per-node status/timing + critical path) for
#     observability — this is what makes the orchestration explainable to ELI.
#
# Pure-Python, stdlib only; the orchestrator itself does no LLM/IO — the node
# callables do. Deterministic report regardless of worker count.
# ════════════════════════════════════════════════════════════════════════════
import time as _time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FTimeout
from dataclasses import dataclass as _dc, field as _fld
from typing import Callable as _Callable

NodeFn = _Callable[["NodeContext"], Any]
Predicate = _Callable[["NodeContext"], bool]


@_dc
class NodeContext:
    """Passed to every node fn. `results` holds completed upstream outputs;
    `shared` is a mutable bag visible to all nodes; `attempt` is 0-based."""
    task_id: str
    results: Dict[str, Any] = _fld(default_factory=dict)
    shared: Dict[str, Any] = _fld(default_factory=dict)
    attempt: int = 0


@_dc
class Task:
    """A runnable DAG node. `run(ctx)->result`; everything else is optional policy."""
    id: str
    run: Optional[NodeFn] = None
    depends_on: Set[str] = _fld(default_factory=set)
    priority: int = 0                      # higher runs first within a ready layer
    retries: int = 0                       # extra attempts after the first
    retry_backoff: float = 0.0             # base seconds for exponential backoff
    timeout: Optional[float] = None        # total per-node budget (seconds)
    fallback: Optional[NodeFn] = None      # run if all attempts fail
    when: Optional[Predicate] = None       # conditional skip if it returns False
    cache_key: Optional[str] = None        # memoisation key (with a cache supplied)
    critical: bool = True                  # if it fails, the overall run is not ok


@_dc
class NodeOutcome:
    id: str
    status: str                            # ok | cached | skipped | failed | timeout
    result: Any = None
    error: Optional[str] = None
    attempts: int = 0
    seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return self.status in ("ok", "cached")


@_dc
class RunReport:
    outcomes: Dict[str, "NodeOutcome"]
    order: List[str]
    layers: List[List[str]]
    seconds: float
    ok: bool

    def result(self, node_id: str) -> Any:
        o = self.outcomes.get(str(node_id))
        return o.result if o else None

    @property
    def failed(self) -> List[str]:
        return [i for i, o in self.outcomes.items() if o.status in ("failed", "timeout")]

    @property
    def skipped(self) -> List[str]:
        return [i for i, o in self.outcomes.items() if o.status == "skipped"]

    @property
    def critical_path(self) -> int:
        return len(self.layers)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "seconds": round(self.seconds, 4),
            "order": self.order,
            "layers": self.layers,
            "critical_path": self.critical_path,
            "failed": self.failed,
            "skipped": self.skipped,
            "nodes": {i: {"status": o.status, "attempts": o.attempts,
                          "seconds": round(o.seconds, 4),
                          "error": o.error} for i, o in self.outcomes.items()},
        }


class Orchestrator:
    """Executes a set of Tasks on their dependency DAG with the frontier policies
    above. `max_workers=1` ⇒ fully sequential + deterministic (used in tests);
    higher ⇒ true intra-layer parallelism."""

    def __init__(self, *, max_workers: Optional[int] = None,
                 cache: Optional[Dict[str, Any]] = None,
                 on_event: Optional[_Callable[[str, "NodeOutcome"], None]] = None,
                 fail_fast: bool = False,
                 time_budget: Optional[float] = None) -> None:
        self.max_workers = max_workers
        self.cache = cache
        self.on_event = on_event
        self.fail_fast = fail_fast
        self.time_budget = time_budget

    # ── per-node execution (retries → fallback → cache), run inside a worker ──
    def _run_one(self, task: "Task", results_snapshot: Dict[str, Any],
                 shared: Dict[str, Any]) -> "NodeOutcome":
        t0 = _time.perf_counter()
        if task.cache_key and self.cache is not None and task.cache_key in self.cache:
            return NodeOutcome(task.id, "cached", self.cache[task.cache_key],
                               attempts=0, seconds=_time.perf_counter() - t0)
        if task.run is None:  # pass-through / join node
            return NodeOutcome(task.id, "ok", None, attempts=0,
                               seconds=_time.perf_counter() - t0)
        last_err: Optional[BaseException] = None
        attempts = 0
        for attempt in range(task.retries + 1):
            attempts = attempt + 1
            ctx = NodeContext(task.id, dict(results_snapshot), shared, attempt)
            try:
                res = task.run(ctx)
                if task.cache_key and self.cache is not None:
                    self.cache[task.cache_key] = res
                return NodeOutcome(task.id, "ok", res, attempts=attempts,
                                   seconds=_time.perf_counter() - t0)
            except Exception as e:  # noqa: BLE001 — policy boundary
                last_err = e
                if attempt < task.retries and task.retry_backoff > 0:
                    _time.sleep(task.retry_backoff * (2 ** attempt))
        if task.fallback is not None:
            try:
                ctx = NodeContext(task.id, dict(results_snapshot), shared, attempts)
                res = task.fallback(ctx)
                return NodeOutcome(task.id, "ok", res, attempts=attempts,
                                   seconds=_time.perf_counter() - t0)
            except Exception as e:  # noqa: BLE001
                last_err = e
        return NodeOutcome(task.id, "failed", None, error=str(last_err),
                           attempts=attempts, seconds=_time.perf_counter() - t0)

    def run(self, tasks: Iterable["Task"],
            context: Optional[Dict[str, Any]] = None) -> "RunReport":
        task_map: Dict[str, Task] = {str(t.id): t for t in tasks}
        dag = build_dag({tid: ({str(d) for d in t.depends_on} & set(task_map))
                         for tid, t in task_map.items()})
        order = dag.topological_order()           # raises DAGCycleError on a cycle
        layers = dag.topological_layers()
        shared: Dict[str, Any] = dict(context or {})
        results: Dict[str, Any] = {}
        outcomes: Dict[str, NodeOutcome] = {}
        run_start = _time.perf_counter()
        had_failure = False

        def _emit(o: NodeOutcome) -> None:
            outcomes[o.id] = o
            if o.ok:
                results[o.id] = o.result
            if self.on_event:
                try:
                    self.on_event(o.id, o)
                except Exception:
                    pass

        def _skip(tid: str, reason: str) -> None:
            _emit(NodeOutcome(tid, "skipped", error=reason, attempts=0, seconds=0.0))

        for layer in layers:
            runnable: List[Task] = []
            for tid in layer:
                task = task_map[tid]
                if self.fail_fast and had_failure:
                    _skip(tid, "fail-fast: an earlier node failed"); continue
                if self.time_budget is not None and \
                        (_time.perf_counter() - run_start) > self.time_budget:
                    _skip(tid, "time budget exceeded"); continue
                bad_dep = next((d for d in task.depends_on
                                if str(d) in task_map and not outcomes.get(str(d), NodeOutcome(str(d), "skipped")).ok),
                               None)
                if bad_dep is not None:
                    _skip(tid, f"upstream '{bad_dep}' did not complete"); continue
                if task.when is not None:
                    try:
                        if not task.when(NodeContext(tid, dict(results), shared)):
                            _skip(tid, "condition (when) was false"); continue
                    except Exception as e:  # noqa: BLE001
                        _skip(tid, f"when() error: {e}"); continue
                runnable.append(task)

            if not runnable:
                continue
            runnable.sort(key=lambda t: (-t.priority, t.id))   # priority within layer
            snapshot = dict(results)
            workers = self.max_workers or min(len(runnable), 8)
            if workers <= 1 or len(runnable) == 1:
                for task in runnable:
                    o = self._run_one(task, snapshot, shared)
                    _emit(o)
                    had_failure = had_failure or (o.status in ("failed", "timeout") and task.critical)
            else:
                with ThreadPoolExecutor(max_workers=workers) as ex:
                    futs = {ex.submit(self._run_one, t, snapshot, shared): t for t in runnable}
                    for fut, task in futs.items():
                        try:
                            o = fut.result(timeout=task.timeout)
                        except _FTimeout:
                            o = NodeOutcome(task.id, "timeout",
                                            error=f"exceeded {task.timeout}s", attempts=1)
                        _emit(o)
                        had_failure = had_failure or (o.status in ("failed", "timeout") and task.critical)

        ok = not any(o.status in ("failed", "timeout") and task_map[i].critical
                     for i, o in outcomes.items())
        return RunReport(outcomes=outcomes, order=order, layers=layers,
                         seconds=_time.perf_counter() - run_start, ok=ok)


def run_graph(tasks: Iterable["Task"], *, max_workers: Optional[int] = None,
              context: Optional[Dict[str, Any]] = None, **kw: Any) -> "RunReport":
    """One-shot convenience: build an Orchestrator and run `tasks`."""
    return Orchestrator(max_workers=max_workers, **kw).run(tasks, context=context)


__all__ = [
    "DAG", "DAGNode", "DAGError", "DAGCycleError", "build_dag",
    "Task", "NodeContext", "NodeOutcome", "RunReport", "Orchestrator", "run_graph",
]
