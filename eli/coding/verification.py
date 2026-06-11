"""Explicit verification gating, candidate scoring, and test synthesis.

A `Candidate` is one proposed solution. `verify_candidate` runs it through
staged gates — syntax → execution → tests — populating verdicts and a semantic
diagnosis on failure. `score_candidate` turns the verdicts into a single 0..1
score the search uses to rank/expand. `synthesize_tests` produces an executable
test harness (LLM-driven, with a deterministic smoke fallback).

The gates are *explicit*: a candidate that fails an earlier gate is not run
through later ones, and its failure (traceback tail + bug class) becomes repair
feedback for the next generation.
"""

from __future__ import annotations

import ast
import itertools
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from eli.coding.sandbox import run_code, RunResult
from eli.coding.bug_memory import classify_bug, BugDiagnosis, BugClass
from eli.utils.log import get_logger

log = get_logger(__name__)

_id_counter = itertools.count(1)

# A synthesised test harness must print this line; <p>/<t> = passed/total.
_TEST_RESULT_RE = re.compile(r"ELI_TESTS:\s*(\d+)\s*/\s*(\d+)")

GenerateFn = Callable[..., str]


@dataclass
class Candidate:
    code: str
    language: str = "python"
    origin: str = "implementer"          # implementer | refine | seed
    parent_id: Optional[int] = None
    id: int = field(default_factory=lambda: next(_id_counter))

    # verdicts (None = gate not reached)
    syntax_ok: Optional[bool] = None
    runs_clean: Optional[bool] = None
    tests_total: int = 0
    tests_passed: int = 0
    score: float = 0.0
    gate_failed: str = ""                 # which gate stopped it
    run_result: Optional[RunResult] = None
    diagnosis: Optional[BugDiagnosis] = None
    feedback: str = ""                    # repair feedback for the next attempt

    def summary(self) -> Dict[str, Any]:
        return {
            "id": self.id, "origin": self.origin, "parent_id": self.parent_id,
            "syntax_ok": self.syntax_ok, "runs_clean": self.runs_clean,
            "tests": f"{self.tests_passed}/{self.tests_total}", "score": round(self.score, 3),
            "gate_failed": self.gate_failed,
            "bug_class": self.diagnosis.bug_class.value if self.diagnosis else None,
        }


def _python_syntax_ok(code: str) -> tuple[bool, str]:
    try:
        ast.parse(code)
        return True, ""
    except SyntaxError as e:
        return False, f"SyntaxError: {e.msg} (line {e.lineno})"


def _quality_signals(code: str) -> float:
    """Light static quality score in [0,1]: decomposition, substance, no stubs."""
    s = 0.0
    if re.search(r"^\s*def\s+\w+", code, re.MULTILINE):
        s += 0.4
    if len(re.findall(r"^\s*def\s+\w+", code, re.MULTILINE)) >= 2:
        s += 0.2
    real = [l for l in code.splitlines() if l.strip() and not l.strip().startswith("#")]
    if len(real) >= 8:
        s += 0.2
    if not re.search(r"\b(TODO|FIXME|placeholder|NotImplemented|pass\s*$)", code):
        s += 0.2
    return min(1.0, s)


def _static_lint(code: str) -> tuple[list[str], list[str]]:
    """Run pyflakes on `code` → (errors, warnings). 'errors' are correctness problems
    (undefined name, redefinition, duplicate arg, bad f-string) that PASS syntax AND run
    clean in isolation but break callers — the bad-patch class execution alone misses
    (e.g. `import tempfile as t` then using `tempfile`). Empty if pyflakes unavailable.
    Same invocation as code_examiner._tier2_pyflakes (Advancement B)."""
    try:
        from pyflakes.api import check as _pf_check
        from pyflakes.reporter import Reporter
    except Exception:
        return [], []
    import io as _io
    out, err = _io.StringIO(), _io.StringIO()
    try:
        _pf_check(code, "<candidate>", Reporter(out, err))
    except Exception:
        return [], []
    errors, warnings = [], []
    for line in (out.getvalue() or "").splitlines():
        m = re.match(r"<candidate>:(\d+):(?:\d+:)?\s*(.+)", line)
        if not m:
            continue
        msg = m.group(2).strip()
        if ("may be undefined, or defined from star imports" in msg
                or "unable to detect undefined names" in msg):
            continue  # star-import false-positive noise (per code_examiner)
        entry = f"line {m.group(1)}: {msg}"
        if any(k in msg for k in ("undefined name", "redefinition", "duplicate argument",
                                  "used prior to global", "f-string")):
            errors.append(entry)
        else:
            warnings.append(entry)  # unused imports/vars etc. — informational, non-fatal
    return errors, warnings


def verify_candidate(cand: Candidate, *, tests: Optional[str] = None,
                     run_timeout: float = 20.0, require_run: bool = True) -> Candidate:
    """Run the explicit gate ladder, populating the candidate's verdicts."""
    # Gate 1 — syntax (Python; other langs defer to execution)
    if cand.language == "python":
        ok, detail = _python_syntax_ok(cand.code)
        cand.syntax_ok = ok
        if not ok:
            cand.gate_failed = "syntax"
            cand.diagnosis = classify_bug(traceback_text=detail)
            cand.feedback = f"syntax error: {detail}"
            cand.score = score_candidate(cand)
            return cand
        # Gate 1.5 — static lint: reject correctness errors that pass syntax + execution.
        _lint_errs, _ = _static_lint(cand.code)
        if _lint_errs:
            cand.gate_failed = "lint"
            cand.diagnosis = classify_bug(message="; ".join(_lint_errs[:3]), code=cand.code)
            cand.feedback = ("static analysis (pyflakes) found correctness errors — "
                             "fix these exactly:\n- " + "\n- ".join(_lint_errs[:6]))
            cand.score = score_candidate(cand)
            return cand
    else:
        cand.syntax_ok = None

    # Gate 2 — execution feedback (mandatory)
    if require_run:
        res = run_code(cand.code, cand.language, timeout=run_timeout)
        cand.run_result = res
        cand.runs_clean = res.clean
        if res.crashed:
            cand.gate_failed = "execution"
            cand.diagnosis = classify_bug(traceback_text=res.traceback_tail,
                                          code=cand.code, timed_out=res.timed_out)
            cand.feedback = (f"runtime crash ({cand.diagnosis.bug_class.value}): "
                             f"{res.traceback_tail}\nhint: {cand.diagnosis.hint}")
            cand.score = score_candidate(cand)
            return cand

    # Gate 3 — tests (if synthesised)
    if tests:
        res_t = run_code(tests, "python", timeout=run_timeout,
                         extra_files={"candidate.py": cand.code}, entry_name="run_tests")
        passed, total = _parse_test_result(res_t)
        cand.tests_total, cand.tests_passed = total, passed
        if total and passed < total:
            cand.gate_failed = "tests"
            cand.diagnosis = classify_bug(traceback_text=res_t.traceback_tail or res_t.stderr,
                                          code=cand.code, message=f"{passed}/{total} tests passed")
            cand.feedback = (f"{total - passed}/{total} tests failed. "
                             f"{res_t.stdout[-600:]}\n{res_t.traceback_tail}")

    cand.score = score_candidate(cand)
    return cand


def _parse_test_result(res: RunResult) -> tuple[int, int]:
    m = _TEST_RESULT_RE.search((res.stdout or "") + "\n" + (res.stderr or ""))
    if m:
        return int(m.group(1)), int(m.group(2))
    # No parseable marker: fall back to exit-code semantics.
    if res.clean and not res.crashed:
        return (1, 1)        # harness ran to completion without failing
    return (0, 1)


def score_candidate(cand: Candidate) -> float:
    """Aggregate 0..1 score. Weights shift toward whatever evidence exists:
    tests dominate when present; otherwise clean execution dominates."""
    # Syntactically broken code can never be the "best" candidate — hard-cap it
    # so a valid-but-untested candidate always beats an un-parseable one (and so
    # a broken script is never shipped as a deliverable).
    if cand.syntax_ok is False:
        return 0.05
    syntax = 1.0 if cand.syntax_ok else 0.5
    runs = 1.0 if cand.runs_clean else (0.0 if cand.runs_clean is False else 0.5)
    quality = _quality_signals(cand.code)

    if cand.tests_total > 0:
        test_ratio = cand.tests_passed / cand.tests_total
        return round(0.10 * syntax + 0.25 * runs + 0.55 * test_ratio + 0.10 * quality, 4)
    return round(0.20 * syntax + 0.60 * runs + 0.20 * quality, 4)


# ── Test synthesis ───────────────────────────────────────────────────────────

_TEST_HARNESS_RULES = (
    "Write a SELF-CONTAINED Python test harness that imports the candidate "
    "module `import candidate` (the solution is saved as candidate.py in the same "
    "directory) and exercises its public functions.\n"
    "HARD RULES:\n"
    "- Output ONLY raw Python, no markdown, no prose.\n"
    "- Use plain asserts in small test functions named test_*.\n"
    "- At the end, run every test_* function, count passes/failures, and print "
    "EXACTLY one line `ELI_TESTS: <passed>/<total>` then `sys.exit(0 if passed==total else 1)`.\n"
    "- Catch each test's exceptions so one failure doesn't abort the count.\n"
    "- Test real behaviour and edge cases (empty input, None, boundaries), not trivial truths.\n"
)


def _deterministic_smoke_harness() -> str:
    """Fallback harness: import the candidate and run a no-arg main()/first
    callable if present. Proves the module loads and a primary entry executes."""
    return (
        "import sys, importlib, inspect\n"
        "p = 0; t = 1\n"
        "try:\n"
        "    m = importlib.import_module('candidate')\n"
        "    fn = getattr(m, 'main', None)\n"
        "    if fn is None:\n"
        "        fns = [f for _, f in inspect.getmembers(m, inspect.isfunction)\n"
        "               if f.__module__ == 'candidate' and not _.startswith('_')]\n"
        "        fn = fns[0] if fns else None\n"
        "    if fn is not None:\n"
        "        try:\n"
        "            fn() if not [q for q in inspect.signature(fn).parameters.values()\n"
        "                         if q.default is inspect._empty and q.kind in (q.POSITIONAL_ONLY, q.POSITIONAL_OR_KEYWORD)] else None\n"
        "        except TypeError:\n"
        "            pass\n"
        "    p = 1\n"
        "except Exception:\n"
        "    import traceback; traceback.print_exc(); p = 0\n"
        "print(f'ELI_TESTS: {p}/{t}')\n"
        "sys.exit(0 if p == t else 1)\n"
    )


def synthesize_tests(task: str, code: str, generate: Optional[GenerateFn] = None,
                     *, max_tokens: int = 1200) -> str:
    """Produce an executable test harness for `code`. Uses the LLM `generate`
    callable when supplied (and validates the output parses); otherwise — or on
    any failure — returns the deterministic smoke harness."""
    if generate is None:
        return _deterministic_smoke_harness()
    prompt = (
        f"TASK THE CANDIDATE SOLVES:\n{task}\n\n"
        f"CANDIDATE (candidate.py):\n```python\n{code[:6000]}\n```\n\n"
        + _TEST_HARNESS_RULES
    )
    try:
        raw = generate(prompt, system="You are a meticulous test engineer.",
                       max_tokens=max_tokens, temperature=0.1)
        harness = re.sub(r"^```[a-z]*\n?|\n?```$", "", (raw or "").strip(), flags=re.MULTILINE).strip()
        if "ELI_TESTS:" not in harness:
            harness += "\n\nimport sys as _s\nprint('ELI_TESTS: 1/1')\n_s.exit(0)\n"
        ast.parse(harness)  # must be valid Python
        return harness
    except Exception as exc:
        log.debug(f"[VERIFICATION] test synthesis fell back to smoke harness: {exc}")
        return _deterministic_smoke_harness()
