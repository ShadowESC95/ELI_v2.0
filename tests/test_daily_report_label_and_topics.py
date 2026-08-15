"""The daily report must be named for the hour, and its topics must be subjects.

From a live 2.1.87 session, the whole header contradicted itself:

    Morning report — Saturday 15 August 2026, 18:16 (activity over the last 24h)
    • Top topics: doing, evening, afternoon, head, mean

Two defects in one line. "Morning report" was a hardcoded string printed beside the
18:16 it had just computed. And the topics were raw word frequencies filtered by a
hand-maintained stopword list — so conversational filler and the greetings it came
from were presented back as the subjects of the day.

The topic fix is structural rather than another round of stopwords: small talk is
skipped wholesale (a greeting is where "evening", "afternoon" and "head" came from),
and a word must appear in at least two DISTINCT messages, so one message saying a
word twice is not a topic raised twice.
"""
import time

import pytest

from eli.runtime.reflection import part_of_day, report_label


def _at(hour, minute=0):
    return time.mktime((2026, 8, 15, hour, minute, 0, 5, 227, -1))


@pytest.mark.parametrize("hour,expected", [
    (0, "morning"), (7, "morning"), (11, "morning"),
    (12, "afternoon"), (14, "afternoon"), (16, "afternoon"),
    (17, "evening"), (18, "evening"), (23, "evening"),
])
def test_part_of_day_follows_the_clock(hour, expected):
    assert part_of_day(_at(hour)) == expected


def test_the_reported_18_16_case():
    """The exact header that exposed this."""
    assert report_label(_at(18, 16)) == "Evening report"


@pytest.mark.parametrize("hour,expected", [
    (9, "Morning report"), (14, "Afternoon report"), (23, "Evening report"),
])
def test_report_label_is_named_for_when_it_runs(hour, expected):
    assert report_label(_at(hour)) == expected


def test_the_daemon_greeting_uses_the_same_boundaries():
    """Greeting and title must not be able to disagree about the time of day."""
    for hour in (0, 11, 12, 16, 17, 23):
        greeting = f"Good {part_of_day(_at(hour))}"
        assert greeting.split()[1] in report_label(_at(hour)).lower()


# ── topics ──────────────────────────────────────────────────────────────────
# The real user messages from the session that produced the bad topic line.
SESSION = [
    "Hey buddy, how's the ould head doing, now?",
    "don't sell yourself short, you have a much better memory than 3 hours. "
    "You remember me ? yourself?",
    "Running just on cpu? I do not think that is entirely accurate, no ?",
    'wht does this mean "init: embeddings required but some input tokens were '
    'not marked as outputs -> overriding " ?',
    "All good my end. Sorry i just clered your chat, do you remember wht we were discussing?",
    "Fuck it we will start fresh again. You have a morning/daily report for me?",
    "Good afternoon, Eli. How are you, today?",
    "wht does this mean about the embeddings and tokens?",
]


def _topics(messages):
    """Drive the shipped reflection over a fixed message set."""
    from eli.runtime import reflection as R
    import time as _t

    now = _t.time()
    turns = [{"role": "user", "content": m, "timestamp": now} for m in messages]

    class _Mem:
        def get_recent_conversation(self, limit=500, **kw):
            return turns
        def get_habit_events(self, **kw):
            return []
        def search_memories(self, *a, **kw):
            return []
        def get_all_memories(self, *a, **kw):
            return []

    import unittest.mock as _mock
    with _mock.patch.object(R, "get_memory", lambda *a, **k: _Mem()):
        insights = R.reflect_on_period(hours=24).get("insights", [])
    for line in insights:
        if line.startswith("Top topics: "):
            return [w.strip() for w in line[len("Top topics: "):].split(",")]
    return []


def test_conversational_filler_is_no_longer_reported_as_a_topic():
    topics = _topics(SESSION)
    for filler in ("doing", "evening", "afternoon", "mean", "sorry", "remember"):
        assert filler not in topics, f"{filler!r} is not a subject anyone discussed"


def test_real_subjects_survive():
    topics = _topics(SESSION)
    assert "embeddings" in topics
    assert "tokens" in topics


def test_one_message_repeating_a_word_is_not_two_mentions():
    """Document frequency, not raw count: the old rule counted occurrences."""
    assert _topics(["the parser parser parser is broken and confusing"]) == []


def test_a_word_raised_across_two_messages_is_a_topic():
    topics = _topics(["the parser is broken", "can you look at the parser again"])
    assert "parser" in topics


def test_a_pure_greeting_contributes_nothing():
    assert _topics(["Good evening", "morning", "hey"]) == []
