"""Run the eval harness as part of pytest.

This makes every model-free router eval case a real pytest test, so the eval
board runs automatically during normal `pytest` (and in any pre-commit/CI hook)
without having to invoke `tools/eval/run_eval.py` separately. Engine cases (which
need a loaded model) are excluded here — run those with the standalone harness:
    python tools/eval/run_eval.py --target engine
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("ELI_HEADLESS", "1")

_REPO = Path(__file__).resolve().parents[1]
_CASES = _REPO / "tools" / "eval" / "cases.yaml"


def _router_cases():
    """Load the router (model-free) cases at collection time. Returns [] on any
    import/parse error so a harness problem can't break the whole test session."""
    try:
        import sys
        if str(_REPO) not in sys.path:
            sys.path.insert(0, str(_REPO))
        from tools.eval.run_eval import _load_cases
        cases = _load_cases(_CASES)
        return [c for c in cases if str(c.get("target", "router")).lower() == "router"]
    except Exception:
        return []


_ROUTER_CASES = _router_cases()


@pytest.mark.skipif(not _ROUTER_CASES, reason="no router eval cases discovered")
@pytest.mark.parametrize("case", _ROUTER_CASES, ids=lambda c: str(c.get("id", "?")))
def test_eval_router_case(case):
    from tools.eval.run_eval import _run_case
    from tools.eval import assertions as A

    res = _run_case(case)
    if res.get("skipped"):
        pytest.skip(str(res.get("reason") or "skipped by driver"))

    failures = []
    for a in (case.get("assert") or []):
        ok, detail = A.check(a, res)
        if not ok:
            failures.append(detail)
    assert not failures, "; ".join(failures)


def test_eval_harness_has_cases():
    """Guard: the harness must actually discover cases (catches a broken
    cases.yaml or import path that would otherwise silently skip everything)."""
    assert _ROUTER_CASES, "router eval cases failed to load — check tools/eval/cases.yaml"
