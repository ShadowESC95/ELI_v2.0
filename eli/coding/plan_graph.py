"""Subtask DAG for the coding engine — structured decomposition with dependencies.

For tasks with genuinely separable components, the planner emits a *graph* of
subtasks (not just a linear list): each node is a sub-problem with `depends_on`
edges. The agent solves nodes in topological order, feeding each node the code of
its already-built dependencies, then composes the node solutions into one module
for final verification. Built on the shared `eli.core.dag` engine, so the coding
engine and the agent bus run on the *same* DAG primitive.

Simple tasks decompose to a single node — in which case the caller uses the plain
single-shot tree search (no DAG overhead).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from eli.core.dag import DAG, build_dag
from eli.utils.log import get_logger

log = get_logger(__name__)

GenerateFn = Callable[..., str]


@dataclass
class DagSolveResult:
    used_dag: bool
    combined_code: str
    order: List[str]
    dag: Dict[str, Any]
    node_scores: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"used_dag": self.used_dag, "order": self.order,
                "dag": self.dag, "node_scores": self.node_scores}


def decompose_dag(task: str, generate: Optional[GenerateFn], *,
                  language: str = "python", max_nodes: int = 6) -> Tuple[DAG, Dict[str, str]]:
    """Return (DAG, {node_id: subtask_text}). Single-node graph when the task has
    no separable components or no model is available."""
    single = build_dag({"root": []})
    if generate is None:
        return single, {"root": task}
    prompt = (
        f"You are a senior {language} architect. If — and ONLY if — this task has "
        "genuinely separable components, decompose it into a small dependency graph "
        "of subtasks. If it's a single cohesive function/script, return ONE node.\n\n"
        f"TASK:\n{task}\n\n"
        "Respond with ONLY JSON: {\"nodes\": [{\"id\": \"short_id\", \"task\": "
        "\"what to build\", \"depends_on\": [\"other_id\", ...]}]}. "
        f"At most {max_nodes} nodes. Dependencies must reference earlier node ids and form a DAG (no cycles)."
    )
    try:
        raw = generate(prompt, system="You decompose software into dependency graphs.",
                       max_tokens=900, temperature=0.2) or ""
        m = re.search(r"\{[\s\S]+\}", raw)
        if not m:
            return single, {"root": task}
        nodes = json.loads(m.group(0)).get("nodes") or []
        if len(nodes) <= 1:
            return single, {"root": task}
        ids = [str(n.get("id") or f"n{i}").strip() for i, n in enumerate(nodes)]
        id_set = set(ids)
        deps: Dict[str, List[str]] = {}
        node_tasks: Dict[str, str] = {}
        for i, n in enumerate(nodes):
            nid = ids[i]
            node_tasks[nid] = str(n.get("task") or task).strip()
            deps[nid] = [str(d).strip() for d in (n.get("depends_on") or []) if str(d).strip() in id_set]
        g = build_dag(deps)
        g.validate()  # raises on cycle/dangling → caught below
        return g, node_tasks
    except Exception as exc:
        log.debug(f"[PLAN_GRAPH] decomposition failed, single node: {exc}")
        return single, {"root": task}


# Only TOP-LEVEL imports (no leading indentation) are hoistable. An indented
# import is function-local and must stay in the body — hoisting it to module top
# (a) is semantically wrong and (b) would carry its indentation into the header,
# producing an IndentationError. This was a real shipped bug.
_TOP_IMPORT_RE = re.compile(r"^(?:import\s+\S|from\s+\S+\s+import\s)")


def compose(order: List[str], solutions: Dict[str, str]) -> str:
    """Concatenate node solutions in topological order, hoisting+deduping
    top-level imports to reduce clashes. Naive but functional v1 composition."""
    imports: List[str] = []
    seen_imports = set()
    bodies: List[str] = []
    for nid in order:
        code = solutions.get(nid, "")
        if not code:
            continue
        body_lines = []
        for line in code.splitlines():
            # Hoist only un-indented, non-relative imports; everything else
            # (including indented in-function imports) stays in the body verbatim.
            if _TOP_IMPORT_RE.match(line) and not line.startswith("from ."):
                key = line.strip()
                if key not in seen_imports:
                    seen_imports.add(key)
                    imports.append(key)
            else:
                body_lines.append(line)
        bodies.append(f"# ── component: {nid} ──\n" + "\n".join(body_lines).strip())
    header = "\n".join(imports)
    return (header + "\n\n" if header else "") + "\n\n".join(bodies) + "\n"


def solve_dag(task: str, generate: Optional[GenerateFn], *, language: str,
              single_solver: Callable[[str], Any], max_nodes: int = 6,
              min_nodes: int = 2) -> Optional[DagSolveResult]:
    """Decompose into a subtask DAG and solve in topological order, passing each
    node its dependencies' code. Returns None when the task is a single node (the
    caller should then use the plain single-shot path).

    `single_solver(node_task) -> object with .code (and optionally .score)`
    solves one node WITHOUT recursing into the DAG (no infinite recursion).
    """
    g, node_tasks = decompose_dag(task, generate, language=language, max_nodes=max_nodes)
    order = g.topological_order()
    if len(order) < min_nodes:
        return None

    solutions: Dict[str, str] = {}
    node_scores: Dict[str, float] = {}
    for nid in order:
        node = g.get(nid)
        dep_code = "\n\n".join(
            f"# already-built component `{d}`:\n{solutions[d]}"
            for d in (node.depends_on if node else []) if d in solutions
        )
        subtask = node_tasks.get(nid, task)
        # Always anchor each node to the ORIGINAL task. Without this the node only
        # sees its abstract subtask label (e.g. "Define constants and mass") and
        # drifts into generic boilerplate that ignores the real requirements —
        # observed: a Schwarzschild-radius request producing GRAVITY=9.81 /
        # EARTH_RADIUS / mass=50.0 instead of the requested mass & density.
        node_task = (
            f"OVERALL GOAL (the complete program must satisfy this):\n{task}\n\n"
            f"Implement ONLY this part of the overall goal, staying faithful to the "
            f"goal's specific values, units, names, and intent:\n{subtask}"
        )
        if dep_code:
            node_task += ("\n\nBuild on these already-implemented components "
                          "(call them; do not reimplement):\n" + dep_code[:5000])
        try:
            res = single_solver(node_task)
            solutions[nid] = getattr(res, "code", "") or ""
            node_scores[nid] = float(getattr(res, "score", 0.0) or 0.0)
        except Exception as exc:
            log.debug(f"[PLAN_GRAPH] node {nid} solve failed: {exc}")
            solutions[nid] = ""
            node_scores[nid] = 0.0

    combined = compose(order, solutions)
    return DagSolveResult(used_dag=True, combined_code=combined, order=order,
                          dag=g.to_dict(), node_scores=node_scores)
