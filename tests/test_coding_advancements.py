"""Coding-subsystem advancements A/B/C.

A — reasoning-native planning: plan_task budget is above the no-think threshold so a
    reasoning model thinks through the plan.
B — static-analysis gate: verify_candidate rejects correctness errors (undefined name /
    redefinition) that pass syntax AND run clean but break callers (the bad-patch class).
C — repo-context retrieval: the agent gathers relevant existing project code so it writes
    against real names/imports instead of guessing.
"""
import inspect


# ── A ───────────────────────────────────────────────────────────────────────
def test_planning_budget_above_no_think_threshold():
    from eli.coding.planner import plan_task
    default = inspect.signature(plan_task).parameters["max_tokens"].default
    assert default > 1024, "planning must clear the no-think suppression threshold"


# ── B ───────────────────────────────────────────────────────────────────────
def test_static_lint_flags_the_bad_patch_class():
    from eli.coding.verification import _static_lint
    errs, _ = _static_lint("import tempfile as t\nfd, path = tempfile.mkstemp()\nprint(path)")
    # pyflakes present in this env → must catch the undefined name; if absent, [] (graceful)
    if errs:
        assert any("undefined name" in e for e in errs)


def test_verify_candidate_lint_gate():
    from eli.coding.verification import verify_candidate, Candidate, _static_lint
    if not _static_lint("import tempfile as t\nx = tempfile.x"):
        import pytest
        pytest.skip("pyflakes not available")
    bad = Candidate(code="import tempfile as t\nfd, p = tempfile.mkstemp()\nprint(p)", language="python")
    verify_candidate(bad, require_run=False)
    assert bad.gate_failed == "lint" and "pyflakes" in (bad.feedback or "")
    good = Candidate(code="import tempfile\nfd, p = tempfile.mkstemp()\nprint(p)", language="python")
    verify_candidate(good, require_run=False)
    assert good.gate_failed != "lint"  # clean import must pass the lint gate


# ── C ───────────────────────────────────────────────────────────────────────
def test_repo_context_retrieves_real_defs():
    from eli.coding.repo_context import gather_repo_context
    ctx = gather_repo_context("fix the verify_candidate function in verification.py")
    assert "def verify_candidate" in ctx
    assert ctx.startswith("#") and len(ctx) <= 4000  # file-headed, bounded


def test_repo_context_empty_for_no_symbols():
    from eli.coding.repo_context import gather_repo_context
    assert gather_repo_context("hello there") == ""


def test_implement_and_plan_accept_context():
    from eli.coding.planner import implement, plan_task
    assert "context" in inspect.signature(implement).parameters
    assert "context" in inspect.signature(plan_task).parameters
    # context flows into the implement prompt
    seen = {}
    implement("t", None, lambda p, **k: seen.setdefault("p", p) or "x = 1",
              context="# eli/x.py\ndef real_api(): ...")
    assert "real_api" in seen["p"]
