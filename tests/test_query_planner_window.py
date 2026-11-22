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


def test_couple_of_days_with_or_without_of():
    """"Do you remember our conversations over the past couple days?" went unread and got a raw dump."""
    from eli.cognition.query_planner import parse_window
    assert parse_window("Do you remember our conversations over the past couple days?", NOW) == parse_window("the past couple of days", NOW)
    assert parse_window("the past couple days") is not None


_MONDAY_NIGHT = datetime(2026, 11, 2, 23, 51)        # a Monday


@pytest.mark.parametrize("said,wrong", [
    ("Just the hum of the GPU and a fresh Monday looming in six hours.", True),
    ("It's Sunday night, nothing on.", True),
    ("Tomorrow is Monday, so rest up.", True),
    ("Tuesday is in about ten minutes.", False),
    ("It's Monday night (23:52), and Tuesday is just around the corner.", False),
    ("It's not Sunday, it's Monday.", False),
    ("Tomorrow's Tuesday.", False),
    ("Friday is looming for the deadline.", False),           # a day still to come, said of one
    ("Monday's meeting went fine.", False),
])
def test_a_weekday_placed_against_now_is_held_to_the_clock(said, wrong):
    from eli.cognition.query_planner import wrong_day_now
    assert bool(wrong_day_now(said, _MONDAY_NIGHT)) is wrong, wrong_day_now(said, _MONDAY_NIGHT)


def test_last_night_is_still_that_night_a_little_after_midnight():
    from eli.cognition.query_planner import wrong_day_now
    assert wrong_day_now("It's Monday night still, technically.", datetime(2026, 11, 3, 0, 20)) == ""
    assert wrong_day_now("It's Monday.", datetime(2026, 11, 4, 12, 0))


def test_a_month_in_supplied_facts_is_not_a_window_on_history():
    """The facts a message supplies date themselves: the question is about them, not about what the
    user did that month, and an empty activity log for the month was given as the answer."""
    from eli.cognition.query_planner import parse_window
    assert parse_window("Information supplied: Project Q-7 started in May. What is the passphrase for Project Q-7? "
                        "If the answer is not provided, say UNKNOWN only.") is None
    assert parse_window("what did I work on in May?") is not None


@pytest.mark.parametrize("text,about_it", [
    ("What is the last thing you remember/what we talked about?", True),
    ("so when was our last conversation before this?", True),
    ("what did we talk about last time?", True),
    ("what did we talk about yesterday?", False),        # a period of its own
    ("the last conversation was great.", False),         # a statement, not a question
    ("play the last song", False),
])
def test_a_question_about_the_last_conversation_is_known(text, about_it):
    from eli.cognition.query_planner import asks_about_last_conversation
    assert asks_about_last_conversation(text) is about_it


def test_the_last_conversation_is_the_one_before_this_one_in_the_log(memory_instance):
    """Live: asked "what is the last thing you remember / what we talked about?", ELI answered from the
    busiest old day (21 October, 298 turns) and said nothing had happened since, with three later
    conversations in the log. The period is the conversation before this one, read from the log."""
    import sqlite3
    from types import SimpleNamespace
    from eli.cognition.orchestrator import _previous_conversation
    mem = memory_instance
    mem.add_conversation_turn("user", "a first message so the tables exist", session_id="s-now")
    day = 86400.0
    t0 = time.time() - 20 * day
    rows = [("s-busy", t0 + i) for i in range(40)] + [("s-last", t0 + 8 * day), ("s-last", t0 + 8 * day + 600)]
    con = sqlite3.connect(str(mem.db_path))
    try:
        for session, ts in rows:
            con.execute("INSERT INTO conversation_turns (session_id, user_id, role, content, ts, timestamp) "
                        "VALUES (?, 'u', 'user', 'something said', ?, ?)", (session, ts, ts))
        con.commit()
    finally:
        con.close()
    window = mem.previous_conversation_window("s-now")
    assert window == (t0 + 8 * day, t0 + 8 * day + 601)
    engine = SimpleNamespace(memory=mem, session_id="s-now")
    assert _previous_conversation(engine, "so when was our last conversation before this?") == window
    assert _previous_conversation(engine, "what did we talk about yesterday?") is None
