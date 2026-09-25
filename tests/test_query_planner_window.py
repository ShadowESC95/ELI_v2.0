"""The time window a question asks about, resolved deterministically."""
import time
from datetime import datetime

import pytest

from eli.cognition.query_planner import parse_window

NOW = datetime(2026, 9, 25, 14, 30).timestamp()      # a Friday
DAY = 86400


def _d(y, m, d, h=0):
    return datetime(y, m, d, h).timestamp()


def days_back(w):
    return round((NOW - w[0]) / DAY, 1)


def test_the_live_question():
    w = parse_window("What films or shows was i watching the past week or two?", NOW)
    assert w[1] == NOW and 14 <= days_back(w) <= 15


@pytest.mark.parametrize("text,lo", [
    ("what did i do in the past week", 7), ("the past two weeks", 14), ("last few days", 3),
    ("the past couple of weeks", 14), ("past month", 30), ("last 10 days", 10),
])
def test_past_spans(text, lo):
    w = parse_window(text, NOW)
    assert lo <= days_back(w) < lo + 1 and w[1] == NOW


def test_named_days():
    assert parse_window("what did i say yesterday", NOW) == (_d(2026, 9, 24), _d(2026, 9, 25))
    assert parse_window("earlier today", NOW) == (_d(2026, 9, 25), NOW)
    assert parse_window("what was i watching last night", NOW) == (_d(2026, 9, 24, 18), _d(2026, 9, 25, 5))
    assert parse_window("this morning", NOW) == (_d(2026, 9, 25), _d(2026, 9, 25, 12))


def test_calendar_periods():
    assert parse_window("last week", NOW) == (_d(2026, 9, 14), _d(2026, 9, 21))
    assert parse_window("this week", NOW) == (_d(2026, 9, 21), NOW)
    assert parse_window("last month", NOW) == (_d(2026, 8, 1), _d(2026, 9, 1))
    assert parse_window("in august", NOW) == (_d(2026, 8, 1), _d(2026, 9, 1))
    assert parse_window("in december", NOW) == (_d(2025, 12, 1), _d(2026, 1, 1))


def test_weekday_and_ago():
    assert parse_window("what did we do on monday", NOW) == (_d(2026, 9, 21), _d(2026, 9, 22))
    a, b = parse_window("three days ago", NOW)
    assert a < NOW - 3 * DAY < b


def test_recently_is_two_weeks():
    assert 13 <= days_back(parse_window("what have i been watching lately", NOW)) < 15


@pytest.mark.parametrize("text", ["what is my name", "open spotify", "who are you", ""])
def test_no_period_named(text):
    assert parse_window(text, NOW) is None
