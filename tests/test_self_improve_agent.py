"""SELF_IMPROVE routed through the coding agent (decompose→solve→verify, propose-only)."""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

import eli.runtime.self_improvement as SI


@pytest.fixture(autouse=True)
def _jobs(monkeypatch):
    """Background submissions are recorded, not run: a real job would reach the coding agent
    after the test's patches are gone."""
    from eli.runtime import background_tasks
    submitted = []

    class _Queue:
        def submit(self, name, fn, *args, **kwargs):
            submitted.append(name)
            return len(submitted)

    monkeypatch.setattr(background_tasks, "get_background_tasks", lambda: _Queue())
    return submitted


def _fake_cr(solved=True, score=0.97):
    return MagicMock(solved=solved, score=score, plan={"approach": "targeted patch"},
                     message="solved", code="def f():\n    return 1\n")


def test_propose_via_agent_orchestrates_failures():
    eng = SI.get_self_improvement()
    fails = [{"error": 'File "eli/x.py" boom', "user_input": "do x"},
             {"error": "err2", "user_input": "do y"}]
    with patch.object(eng, "analyze_failures", return_value=fails):
        with patch("eli.coding.agent.CodeAgent.solve", return_value=_fake_cr()):
            r = eng.propose_via_agent(max_items=2)
    assert r["ok"] and r["count"] == 2
    assert all(p["verified"] for p in r["proposals"])
    # ran as a parallel DAG layer (orchestrated, not a sequential loop)
    assert r["orchestration"]["layers"] == [["fix_0", "fix_1"]]


def test_propose_via_agent_no_failures():
    eng = SI.get_self_improvement()
    with patch.object(eng, "analyze_failures", return_value=[]):
        r = eng.propose_via_agent()
    assert r["ok"] and r["proposals"] == [] and "no recent failures" in r.get("reason", "")


def test_build_fix_task_inlines_named_file():
    eng = SI.get_self_improvement()
    task = eng._build_fix_task({"error": 'File "eli/core/dag.py", line 1\nBoom', "user_input": "x"})
    assert "Fix the bug" in task and "eli/core/dag.py" in task


def test_self_improve_action_propose_mode_runs_inline_when_asked():
    from eli.execution.executor_enhanced import execute
    fails = [{"error": "boom", "user_input": "do x"}]
    eng = SI.get_self_improvement()
    with patch.object(eng, "analyze_failures", return_value=fails):
        with patch("eli.coding.agent.CodeAgent.solve", return_value=_fake_cr()):
            r = execute("SELF_IMPROVE", {"mode": "propose", "_no_background": True})
    assert r["ok"] and r.get("evidence_source") == "coding_agent"
    assert "fix proposals" in r["content"].lower()


def test_self_improve_action_propose_mode_is_backgrounded(_jobs):
    """propose mode returns at once with a job id, never runs inline: the coding agent fans out
    to tens of sequential 30-500 s model calls with nothing shown until it returns, and running
    it on the chat turn held the model for hours."""
    from eli.execution.executor_enhanced import execute
    r = execute("SELF_IMPROVE", {"mode": "propose"})
    assert r["ok"] and r.get("evidence_source") == "coding_agent"
    assert r.get("background") is True and r.get("job_id") == 1 and len(_jobs) == 1
    assert "background" in r["content"].lower()


def test_asking_for_it_now_keeps_it_in_the_turn(_jobs):
    from eli.execution.executor_enhanced import execute
    eng = SI.get_self_improvement()
    with patch.object(eng, "analyze_failures", return_value=[]):
        r = execute("SELF_IMPROVE", {"mode": "propose",
                                     "_raw_user_text": "propose fixes now, in the foreground"})
    assert not _jobs and r.get("background") is not True


def test_self_improve_detects_propose_intent_from_text():
    from eli.execution.executor_enhanced import execute
    eng = SI.get_self_improvement()
    with patch.object(eng, "analyze_failures", return_value=[]):
        # default mode=analyze, but the raw text asks to propose fixes → routes to propose
        r = execute("SELF_IMPROVE",
                    {"_raw_user_text": "improve your code: propose verified fixes for the failing tests"})
    assert r["ok"] and r.get("evidence_source") == "coding_agent"


def test_the_routes_hand_the_words_to_the_executor():
    """The executor reads "propose" / "self fix" / "in the foreground" from the user's words;
    the routes passed none, so "improve yourself and propose verified fixes" only analysed."""
    from eli.execution.router_enhanced import route
    for text in ("improve yourself and propose verified fixes", "generate patch"):
        r = route(text)
        assert r["action"] == "SELF_IMPROVE" and r["args"].get("_raw_user_text") == text
