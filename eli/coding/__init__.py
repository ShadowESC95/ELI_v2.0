"""ELI coding agent — frontier-grade code generation, analysis & repair.

A self-contained, additive subsystem implementing:
  - structured decomposition (planner / implementer separation)   [planner.py]
  - a mandatory execution-feedback loop                            [sandbox.py]
  - tree/beam search over solutions with UCB-style exploration     [search.py]
  - explicit verification gating + candidate scoring               [verification.py]
  - automated test synthesis                                       [verification.py]
  - patch-based incremental refinement                             [search.py]
  - semantic bug classification                                    [bug_memory.py]
  - long-term memory of bugs and fixes                             [bug_memory.py]

The public entry point is `solve()` / `CodeAgent`. LLM-driven steps take an
injected `generate` callable so the whole pipeline is testable without a model.
"""

from __future__ import annotations

from eli.coding.sandbox import run_code, smoke_import, RunResult, sandbox_enabled
from eli.coding.bug_memory import classify_bug, BugMemory, BugClass
from eli.coding.verification import (
    Candidate, verify_candidate, score_candidate, synthesize_tests,
)

__all__ = [
    "run_code", "smoke_import", "RunResult", "sandbox_enabled",
    "classify_bug", "BugMemory", "BugClass",
    "Candidate", "verify_candidate", "score_candidate", "synthesize_tests",
    "CodeAgent", "solve",
]


def __getattr__(name):
    # Lazy import of the orchestrator so importing the package doesn't pull the
    # heavier search/planner graph unless actually used.
    if name in ("CodeAgent", "solve"):
        from eli.coding.agent import CodeAgent, solve
        return {"CodeAgent": CodeAgent, "solve": solve}[name]
    raise AttributeError(name)
