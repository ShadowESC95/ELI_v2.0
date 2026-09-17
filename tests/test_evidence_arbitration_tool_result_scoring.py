"""A tool-result record with no "ok" field is UNVERIFIED, not a success.

`_score_tool_result()` used to default a missing "ok" field to True, so a
record whose outcome was never recorded scored the same 0.86 confidence as a
genuinely confirmed success -- that number then flows straight into the
rendered evidence bundle text as if something had actually been verified.
For a product whose pitch is trustworthy, grounded local intelligence, "I
don't know if this worked" must not score the same as "this worked".
"""
from __future__ import annotations

from eli.runtime.evidence_arbitration import _score_tool_result


def test_confirmed_success_scores_high():
    item = _score_tool_result({"ok": True, "status": "ok", "action": "OPEN_APP"})
    assert item.score == 0.86


def test_confirmed_failure_scores_low():
    item = _score_tool_result({"ok": False, "status": "ok", "action": "OPEN_APP"})
    assert item.score == 0.30


def test_missing_ok_field_is_not_scored_as_success():
    item = _score_tool_result({"status": "ok", "action": "OPEN_APP"})
    assert item.score == 0.30, (
        "a record with no recorded outcome must not score the same as a "
        "confirmed success"
    )


def test_missing_ok_field_scores_the_same_as_a_confirmed_failure():
    unverified = _score_tool_result({"status": "ok", "action": "OPEN_APP"})
    failed = _score_tool_result({"ok": False, "status": "ok", "action": "OPEN_APP"})
    assert unverified.score == failed.score
