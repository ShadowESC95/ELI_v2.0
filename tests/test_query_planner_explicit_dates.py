"""Explicit dates, ranges, months and years in a question become a time window."""
from datetime import datetime

import pytest

from eli.cognition.query_planner import parse_window

NOW = datetime(2026, 9, 25, 12).timestamp()


def _days(text):
    w = parse_window(text, NOW)
    return None if w is None else (datetime.fromtimestamp(w[0]).date().isoformat(), datetime.fromtimestamp(w[1]).date().isoformat())


@pytest.mark.parametrize("text,expected", [
    ("what did we discuss on 2026-03-03", ("2026-03-03", "2026-03-04")),
    ("what happened on 3 March", ("2026-03-03", "2026-03-04")),
    ("on March 3rd 2025 what did I say", ("2025-03-03", "2025-03-04")),
    ("between 1 May and 10 May", ("2026-05-01", "2026-05-11")),
    ("what was I doing in June 2025", ("2025-06-01", "2025-07-01")),
    ("during 2024", ("2024-01-01", "2025-01-01")),
    ("what did I say yesterday", ("2026-09-24", "2026-09-25")),
])
def test_windows(text, expected):
    assert _days(text) == expected


@pytest.mark.parametrize("text", ["market 5 percent fell", "may I ask three things", "call me at 5 pm", "what is the plan"])
def test_ordinary_text_names_no_period(text):
    assert _days(text) is None


def test_a_date_without_a_year_is_its_latest_past_occurrence():
    assert _days("what happened on 30 December")[0] == "2025-12-30"
