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
