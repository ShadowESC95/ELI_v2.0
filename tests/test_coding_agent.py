"""Deterministic tests for the ELI coding agent (eli/coding).

No model required — the LLM is injected as a stub generator, so the full
plan → search → verify → repair → bug-memory loop is exercised against real
sandbox execution.
"""

import tempfile
from pathlib import Path

import pytest

from eli.coding.sandbox import run_code
from eli.coding.bug_memory import classify_bug, BugClass, BugMemory
from eli.coding.verification import Candidate, verify_candidate, score_candidate
from eli.coding.agent import CodeAgent


# ── sandbox ───────────────────────────────────────────────────────────────────

def test_sandbox_clean_run():
    r = run_code("print(sum(range(10)))", "python", timeout=8)
    assert r.clean and not r.crashed and r.returncode == 0


def test_sandbox_real_crash_detected():
    r = run_code("x = [1, 2]\nprint(x[9])", "python", timeout=8)
    assert r.crashed and "IndexError" in r.traceback_tail


def test_sandbox_timeout_is_tolerated():
    r = run_code("import time\nwhile True:\n    time.sleep(0.2)", "python", timeout=2)
    assert r.clean and r.timed_out and not r.crashed


def test_sandbox_missing_optional_dep_tolerated():
    r = run_code("import a_module_that_is_not_installed_xyz", "python", timeout=8)
    assert r.clean and not r.crashed


# ── bug classification ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("tb,expected", [
    ("Traceback (most recent call last):\n  File \"x\", line 1, in f\n    o.v\n"
     "AttributeError: 'NoneType' object has no attribute 'v'", BugClass.NULL_DEREF),
    ("Traceback (most recent call last):\n  File \"x\", line 1\n    a[9]\nIndexError: list index out of range",
     BugClass.INDEX_OOB),
    ("Traceback (most recent call last):\n  File \"x\", line 1\n    d['k']\nKeyError: 'k'", BugClass.KEY_MISSING),
])
def test_bug_classification(tb, expected):
    dg = classify_bug(traceback_text=tb)
    assert dg.bug_class == expected and dg.confidence >= 0.8 and dg.signature


def test_bug_memory_record_and_recall():
    with tempfile.TemporaryDirectory() as td:
        bm = BugMemory(db_path=Path(td) / "bm.sqlite3")
        dg = classify_bug(traceback_text="AttributeError: 'NoneType' object has no attribute 'v'")
        bm.record_fix(dg, "guard None before attribute access", fix_diff="if o is None: return")
        recalled = bm.recall(dg)
        assert recalled and recalled[0].fix_summary.startswith("guard None")
        assert bm.stats()["total_fixes"] == 1


# ── verification + scoring ──────────────────────────────────────────────────────

def test_verify_syntax_gate():
    c = verify_candidate(Candidate(code="def f(:\n  pass"))
    assert c.syntax_ok is False and c.gate_failed == "syntax"


def test_verify_clean_scores_higher_than_crash():
    good = verify_candidate(Candidate(code="def main():\n    return 1\nmain()\n"))
    bad = verify_candidate(Candidate(code="raise ValueError('boom')\n"))
    assert good.score > bad.score and good.runs_clean and bad.runs_clean is False


# ── full agent loop (stub generator) ────────────────────────────────────────────

def _stub(prompt, system="", max_tokens=1000, temperature=0.2, **k):
    p = prompt.lower()
    if "only json" in p:
        return '{"approach":"sum two ints","steps":["def add(a,b)","return a+b"]}'
    if "test harness" in p:
        return ("import candidate, sys\np=0;t=2\n"
                "try:\n    assert candidate.add(2,3)==5; p+=1\nexcept Exception: pass\n"
                "try:\n    assert candidate.add(-1,1)==0; p+=1\nexcept Exception: pass\n"
                "print(f'ELI_TESTS: {p}/{t}')\nsys.exit(0 if p==t else 1)\n")
    if "rejected" in p or "previous attempt feedback" in p:
        return ("def add(a, b):\n    return a + b\n\ndef main():\n    print(add(2, 3))\n\n"
                "if __name__ == '__main__':\n    main()\n")
    return ("def add(a, b):\n    return a - b\n\ndef main():\n    print(add(2, 3))\n\n"
            "if __name__ == '__main__':\n    main()\n")


def test_search_early_exits_on_plateau():
    """Tree search must stop refining when scores stop improving, so an ill-posed
    task can't burn the whole iteration budget."""
    from eli.coding.search import tree_search
    from eli.coding.planner import Plan
    calls = {"n": 0}

    def gen(prompt, system="", **k):
        calls["n"] += 1
        if "test harness" in prompt.lower():
            return "import candidate, sys\nprint('ELI_TESTS: 0/1')\nsys.exit(1)\n"
        return "def f():\n    return 1 / 0\n"  # always crashes → never improves

    r = tree_search("do x", gen, plan=Plan(approach="x", steps=["x"]), language="python",
                    tests=None, beam=2, max_iterations=8, no_improve_patience=2, run_timeout=6)
    assert r.iterations < 8
    assert any(s.get("step") == "early_exit" for s in r.trace)


def test_agent_repairs_via_search_and_records_fix():
    with tempfile.TemporaryDirectory() as td:
        bm = BugMemory(db_path=Path(td) / "bm.sqlite3")
        r = CodeAgent(generate=_stub, bug_memory=bm).solve(
            "Write add(a, b) returning the sum.", beam=2, max_iterations=4)
        assert r.solved, f"expected solved, got score {r.score}"
        assert "a + b" in r.code and "a - b" not in r.code
        assert r.score >= 0.95
        assert bm.stats()["total_fixes"] >= 1   # the repair was remembered
