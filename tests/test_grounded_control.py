"""grounded_control — the contract that decides when evidence is complete enough to
SKIP asking the user to clarify (anti-annoyance guard). Pure logic.
"""
from __future__ import annotations

from eli.contracts import grounded_control as gc


def test_unknown_action_never_complete():
    assert gc.evidence_complete_for_action("CHAT", {"x": "ok content"}) is False


def test_generic_ok_evidence_is_complete():
    lv = {"result": {"ok": True, "content": "here is the report"}}
    assert gc.evidence_complete_for_action("MEMORY_RECALL", lv) is True


def test_error_evidence_is_incomplete():
    lv = {"result": {"ok": True, "content": "x", "traceback": "boom"}}
    assert gc.evidence_complete_for_action("MEMORY_RECALL", lv) is False


def test_bad_clarification_detection():
    assert gc.looks_like_bad_clarification("Could you please clarify?") is True
    assert gc.looks_like_bad_clarification("please clarify") is False      # no '?'
    assert gc.looks_like_bad_clarification("what time is it?") is False    # not a bad pattern
    assert gc.looks_like_bad_clarification("") is False


def test_suppress_clarification_guards():
    assert gc.should_suppress_clarification("not a mapping") is False
    assert gc.should_suppress_clarification({"action": "CHAT"}) is False
