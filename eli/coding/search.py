"""Tree/beam search over candidate solutions with UCB-style exploration.

Not single-shot: ELI generates a diverse beam of root candidates, verifies each
through the gate ladder, then iteratively *expands* the most promising imperfect
node — balancing exploitation (score) against exploration (visit count) via a
UCB1 rule. Expansion is patch-based incremental refinement: the implementer
rewrites the selected candidate using its failure feedback, augmented with any
matching prior fix from long-term bug memory. Successful repairs are written
back to bug memory as (bug → fix) pairs.
"""

from __future__ import annotations

import difflib
import math
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from eli.coding.planner import Plan, implement
from eli.coding.verification import Candidate, verify_candidate
from eli.coding.bug_memory import BugMemory
from eli.utils.log import get_logger

log = get_logger(__name__)

GenerateFn = Callable[..., str]


@dataclass
class SearchResult:
    best: Candidate
    nodes: List[Candidate]
    trace: List[Dict]
    iterations: int
    elapsed_s: float
    solved: bool

    def to_dict(self) -> Dict:
        return {
            "solved": self.solved, "iterations": self.iterations,
            "elapsed_s": round(self.elapsed_s, 2), "explored": len(self.nodes),
            "best": self.best.summary(), "trace": self.trace,
        }


def _unified_diff(old: str, new: str) -> str:
    return "".join(difflib.unified_diff(
        old.splitlines(keepends=True), new.splitlines(keepends=True),
        fromfile="before", tofile="after", n=2))[:8000]


def _augment_with_memory(cand: Candidate, bug_memory: Optional[BugMemory]) -> None:
    """If the candidate has a diagnosed bug, look up prior fixes for it and append
    them to the repair feedback (long-term memory feeding the loop)."""
    if not (bug_memory and cand.diagnosis and cand.feedback):
        return
    try:
        recalls = bug_memory.recall(cand.diagnosis, limit=2)
    except Exception:
        recalls = []
    if recalls:
        lines = [f"- ({r.bug_class}, seen {r.success_count}×) {r.fix_summary}" for r in recalls]
        cand.feedback += "\n\nKnown fixes for this bug class from prior experience:\n" + "\n".join(lines)


def _select_ucb(nodes: List[Candidate], visits: Dict[int, int], total: int,
                target: float, c: float) -> Optional[Candidate]:
    """UCB1 selection over expandable nodes (imperfect, has feedback to act on)."""
    expandable = [n for n in nodes if n.score < target and n.feedback]
    if not expandable:
        # fall back to refining the best imperfect node even without explicit feedback
        expandable = [n for n in nodes if n.score < target]
    if not expandable:
        return None
    best, best_ucb = None, -1.0
    for n in expandable:
        ni = max(1, visits.get(n.id, 1))
        ucb = n.score + c * math.sqrt(math.log(max(2, total)) / ni)
        if ucb > best_ucb:
            best, best_ucb = n, ucb
    return best


def tree_search(
    task: str,
    generate: GenerateFn,
    *,
    plan: Optional[Plan] = None,
    language: str = "python",
    tests: Optional[str] = None,
    beam: int = 3,
    max_iterations: int = 6,
    target_score: float = 0.95,
    explore_c: float = 0.7,
    run_timeout: float = 20.0,
    time_budget_s: float = 240.0,
    no_improve_patience: int = 3,
    bug_memory: Optional[BugMemory] = None,
    context: str = "",
) -> SearchResult:
    t0 = time.time()
    nodes: List[Candidate] = []
    visits: Dict[int, int] = {}
    trace: List[Dict] = []

    def _record_success(parent: Candidate, child: Candidate) -> None:
        """Write a (bug → fix) pair to long-term memory when a refinement turns a
        diagnosed failure into a clean, higher-scoring solution."""
        if not (bug_memory and parent.diagnosis):
            return
        if child.runs_clean and child.score > parent.score:
            try:
                bug_memory.record_fix(
                    parent.diagnosis,
                    fix_summary=f"refinement resolved {parent.diagnosis.bug_class.value}: {parent.diagnosis.hint}",
                    fix_diff=_unified_diff(parent.code, child.code),
                    language=language,
                )
            except Exception as exc:
                log.debug(f"[SEARCH] record_fix failed: {exc}")

    # ── Roots: a diverse beam (temperature ladder = U-style exploration) ─────
    for i in range(max(1, beam)):
        temp = round(0.15 + 0.25 * i, 2)
        code = implement(task, plan, generate, language=language, context=context, temperature=temp)
        cand = Candidate(code=code, language=language, origin="implementer")
        verify_candidate(cand, tests=tests, run_timeout=run_timeout)
        _augment_with_memory(cand, bug_memory)
        nodes.append(cand)
        visits[cand.id] = 1
        trace.append({"step": f"root#{i}", **cand.summary()})
        if cand.score >= target_score:
            return SearchResult(cand, nodes, trace, 0, time.time() - t0, solved=True)
        if time.time() - t0 > time_budget_s:
            break

    # ── Iterative expansion ──────────────────────────────────────────────────
    iterations = 0
    best_score = max((c.score for c in nodes), default=0.0)
    stale = 0
    for it in range(max_iterations):
        if time.time() - t0 > time_budget_s:
            break
        total = sum(visits.values())
        parent = _select_ucb(nodes, visits, total, target_score, explore_c)
        if parent is None:
            break
        visits[parent.id] = visits.get(parent.id, 1) + 1
        iterations += 1
        child_code = implement(task, plan, generate, language=language,
                               feedback=parent.feedback, prior_code=parent.code,
                               context=context, temperature=0.25)
        child = Candidate(code=child_code, language=language, origin="refine", parent_id=parent.id)
        verify_candidate(child, tests=tests, run_timeout=run_timeout)
        _augment_with_memory(child, bug_memory)
        _record_success(parent, child)
        nodes.append(child)
        visits[child.id] = 1
        trace.append({"step": f"refine#{it}<-{parent.id}", **child.summary()})
        if child.score >= target_score:
            return SearchResult(child, nodes, trace, iterations, time.time() - t0, solved=True)
        # Early-exit: stop burning calls when refinements stop improving (e.g. an
        # ill-posed task where every candidate scores ~0).
        if child.score > best_score + 1e-6:
            best_score = child.score
            stale = 0
        else:
            stale += 1
            if stale >= max(1, no_improve_patience):
                trace.append({"step": "early_exit", "reason": f"no score improvement in {stale} refinements"})
                break

    best = max(nodes, key=lambda c: c.score)
    return SearchResult(best, nodes, trace, iterations, time.time() - t0,
                        solved=best.score >= target_score)
