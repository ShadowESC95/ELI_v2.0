"""CodeAgent — the orchestrator that composes ELI's coding capabilities.

solve(task) runs the full frontier-grade loop:

    plan  →  seed implementation  →  synthesize tests  →
    tree search (beam + UCB refinement, mandatory execution feedback,
                 bug-memory recall on failures, fix recording on success)  →
    best verified candidate + full provenance.

The LLM is reached through an injected `generate` callable; the default is the
local inference broker, so this is model-agnostic and the whole pipeline is
unit-testable with a stub generator.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from eli.coding.planner import Plan, plan_task, implement
from eli.coding.verification import Candidate, verify_candidate, synthesize_tests
from eli.coding.search import tree_search, SearchResult
from eli.coding.bug_memory import BugMemory, get_bug_memory
from eli.utils.log import get_logger

log = get_logger(__name__)

GenerateFn = Callable[..., str]


def _broker_generate(prompt: str, *, system: str = "", max_tokens: int = 2000,
                     temperature: float = 0.2) -> str:
    """Default generator backed by ELI's local inference broker (model-agnostic)."""
    try:
        from eli.cognition.inference_broker import get_broker
        broker = get_broker()
    except Exception as exc:
        log.debug(f"[CODE_AGENT] broker unavailable: {exc}")
        return ""
    for kwargs in ({"system": system, "max_tokens": max_tokens, "temperature": temperature},
                   {"max_tokens": max_tokens, "temperature": temperature},
                   {}):
        try:
            return broker.infer(prompt, **kwargs) or ""
        except TypeError:
            continue
        except Exception as exc:
            log.debug(f"[CODE_AGENT] broker.infer failed: {exc}")
            return ""
    return ""


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except Exception:
        return default


@dataclass
class CodeResult:
    ok: bool
    solved: bool
    code: str
    language: str
    score: float
    plan: Dict[str, Any]
    tests: str
    search: Dict[str, Any]
    bug_class: Optional[str]
    message: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok, "solved": self.solved, "code": self.code,
            "language": self.language, "score": round(self.score, 3),
            "plan": self.plan, "search": self.search, "bug_class": self.bug_class,
            "message": self.message,
        }


class CodeAgent:
    def __init__(self, generate: Optional[GenerateFn] = None,
                 bug_memory: Optional[BugMemory] = None):
        self.generate = generate or _broker_generate
        try:
            self.bug_memory = bug_memory or get_bug_memory()
        except Exception:
            self.bug_memory = None

    def solve(self, task: str, *, language: str = "python", use_tests: bool = True,
              beam: Optional[int] = None, max_iterations: Optional[int] = None,
              run_timeout: float = 20.0, target_score: float = 0.95,
              use_dag: Optional[bool] = None) -> CodeResult:
        if not (task or "").strip():
            return CodeResult(False, False, "", language, 0.0, {}, "", {}, None,
                              "empty task")
        # Subtask-DAG path for decomposable tasks (shared eli.core.dag engine).
        if use_dag is None:
            use_dag = os.environ.get("ELI_CODING_DAG", "1").strip().lower() not in ("0", "false", "no", "off")
        if use_dag and language == "python":
            dag_cr = self._try_dag_solve(task, use_tests=use_tests, run_timeout=run_timeout,
                                         target_score=target_score)
            if dag_cr is not None and dag_cr.code.strip() and (dag_cr.solved or dag_cr.score >= 0.5):
                return dag_cr   # else fall through to single-shot
        return self._solve_single(task, language=language, use_tests=use_tests, beam=beam,
                                   max_iterations=max_iterations, run_timeout=run_timeout,
                                   target_score=target_score)

    def _try_dag_solve(self, task: str, *, use_tests: bool, run_timeout: float,
                       target_score: float) -> Optional[CodeResult]:
        """Decompose into a subtask DAG; solve nodes topologically; verify the
        composed module. Returns None when the task is a single node."""
        try:
            from eli.coding.plan_graph import solve_dag
            from eli.coding.verification import Candidate, verify_candidate
            def _node_solver(node_task: str):
                return self._solve_single(node_task, language="python", use_tests=False,
                                          beam=2, max_iterations=2, run_timeout=run_timeout,
                                          target_score=target_score)
            dag_res = solve_dag(task, self.generate, language="python", single_solver=_node_solver)
            if dag_res is None or not dag_res.combined_code.strip():
                return None
            cand = Candidate(code=dag_res.combined_code, language="python", origin="dag")
            tests = synthesize_tests(task, dag_res.combined_code, self.generate) if use_tests else ""
            verify_candidate(cand, tests=tests or None, run_timeout=run_timeout)
            if cand.syntax_ok is False:
                # Composition produced un-parseable code — don't ship it; let the
                # single-shot path try for one coherent module instead.
                log.debug("[CODE_AGENT] DAG composition failed syntax; falling back to single-shot")
                return None
            return CodeResult(
                ok=bool(cand.code.strip()), solved=cand.score >= target_score, code=cand.code,
                language="python", score=cand.score,
                plan={"approach": "subtask DAG", "steps": dag_res.order},
                tests=tests, search={"mode": "dag", **dag_res.to_dict(), "best": cand.summary()},
                bug_class=(cand.diagnosis.bug_class.value if cand.diagnosis else None),
                message=f"DAG solve over {len(dag_res.order)} nodes (score {cand.score:.2f})",
            )
        except Exception as exc:
            log.debug(f"[CODE_AGENT] DAG solve failed, using single-shot: {exc}")
            return None

    def _solve_single(self, task: str, *, language: str = "python", use_tests: bool = True,
                      beam: Optional[int] = None, max_iterations: Optional[int] = None,
                      run_timeout: float = 20.0, target_score: float = 0.95) -> CodeResult:
        beam = beam if beam is not None else _env_int("ELI_CODING_BEAM", 3)
        max_iterations = (max_iterations if max_iterations is not None
                          else _env_int("ELI_CODING_MAX_ITERS", 6))

        # 0) Repo context — relevant EXISTING project code (named files' imports + the
        #    defs of symbols the task names) so the agent writes against real APIs/patterns
        #    instead of guessing (Advancement C; deterministic, offline, bounded).
        try:
            from eli.coding.repo_context import gather_repo_context
            ctx = gather_repo_context(task)
        except Exception:
            ctx = ""

        # 1) Plan (structured decomposition; reasoning-native budget — see plan_task)
        plan = plan_task(task, self.generate, language=language, context=ctx)

        # 2) Seed implementation — used as concrete context for test synthesis
        seed_code = implement(task, plan, self.generate, language=language,
                              context=ctx, temperature=0.2)

        # 3) Synthesize tests (only meaningful for Python execution gating)
        tests = ""
        if use_tests and language == "python" and seed_code.strip():
            tests = synthesize_tests(task, seed_code, self.generate)

        # 4) Tree search with mandatory execution feedback + bug memory
        result: SearchResult = tree_search(
            task, self.generate, plan=plan, language=language, tests=tests or None,
            beam=beam, max_iterations=max_iterations, target_score=target_score,
            run_timeout=run_timeout, bug_memory=self.bug_memory, context=ctx,
        )
        best = result.best
        msg = (f"solved (score {best.score:.2f})" if result.solved
               else f"best effort (score {best.score:.2f}, gate: {best.gate_failed or 'none'})")
        return CodeResult(
            ok=bool(best.code.strip()), solved=result.solved, code=best.code,
            language=language, score=best.score, plan={"approach": plan.approach, "steps": plan.steps},
            tests=tests, search=result.to_dict(),
            bug_class=(best.diagnosis.bug_class.value if best.diagnosis else None),
            message=msg,
        )


def solve(task: str, **kwargs) -> Dict[str, Any]:
    """Convenience entry: run the default agent and return a plain dict."""
    return CodeAgent().solve(task, **kwargs).to_dict()
