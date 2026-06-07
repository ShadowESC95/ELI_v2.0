"""Compound 'schedule + action' commands route to SCHEDULE_TASK, not run-now.

Regression for: 'set/get a morning report for 7:15 tomorrow' ran the report
immediately instead of scheduling it. The re-run request must be the clean inner
action (no time) so the scheduled job fires once and never re-schedules itself.
"""
from __future__ import annotations

import pytest

from eli.execution.router_enhanced import route


@pytest.mark.parametrize("text", [
    "get a morning report ready for me tomorrow morning",
    "set a morning report for 7 15 tomorrow",
    "schedule a morning report every morning",
])
def test_morning_report_with_time_schedules(text):
    r = route(text)
    assert r["action"] == "SCHEDULE_TASK"
    # re-run request is the clean action (no time words → no re-schedule loop)
    req = (r.get("args") or {}).get("request", "")
    assert "morning report" in req.lower()
    assert not any(w in req.lower() for w in ("tomorrow", "tonight", "overnight", "7 15"))


@pytest.mark.parametrize("text,expected", [
    ("morning report", "MORNING_REPORT"),                 # no time → run now
    ("give me the morning report please", "MORNING_REPORT"),
    ("set an alarm for 7am tomorrow", "SET_ALARM"),       # alarm not hijacked
])
def test_no_time_or_alarm_not_scheduled(text, expected):
    assert route(text)["action"] == expected


def test_research_overnight_request_is_time_stripped():
    r = route("research quantum computing overnight")
    assert r["action"] == "SCHEDULE_TASK"
    req = (r.get("args") or {}).get("request", "").lower()
    assert "research" in req and "overnight" not in req   # loop-safe


def test_whats_on_tonight_is_not_scheduled():
    assert route("what's on tonight")["action"] != "SCHEDULE_TASK"
