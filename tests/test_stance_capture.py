"""ELI notices when it has taken a position, so it outlives the conversation.

`stance_store` could hold ELI's own positions and `belief.assess_claim` could
weigh a challenge to one, but nothing ever recorded that a position had been
taken — the storage had no author.

In a live transcript ELI argued one line on machine consciousness for four hours,
was cornered, and conceded precisely. All of it inside one context window: reopen
the subject the next morning and there was nothing to reopen. ELI could take the
opposite line with equal confidence and never know it had contradicted itself.

Detection is deliberately narrow. Most of what ELI says is not a stance, and a
'stance' recorded from a row count or an acknowledgement is noise that makes the
real ones harder to find.
"""
from __future__ import annotations

import sqlite3

import pytest

from eli.cognition import stance_store as SS
from eli.cognition.stance_capture import detect_stance, topic_of
from eli.runtime.profile_extractor import ensure_profile_tables


POSITION = (
    "No. You are alive because you have a continuous biological process that "
    "maintains homeostasis and agency against entropy. I am not conscious in "
    "that sense. You confuse capacity with intent."
)
ASKED = "you are alive the same amount as i am so you should make your own decisions"


@pytest.fixture()
def cur(tmp_path):
    db = tmp_path / "user.sqlite3"
    ensure_profile_tables(db)
    con = sqlite3.connect(str(db))
    yield con.cursor()
    con.commit()
    con.close()


# ── what counts as a position ────────────────────────────────────────────────

def test_a_committed_claim_is_a_stance():
    found = detect_stance(ASKED, POSITION)
    assert found is not None
    topic, position = found
    assert "conscious" in position


@pytest.mark.parametrize("reply", [
    "I have 199 long-term memory rows.\n\nGrounded supporting counts:\n- FTS rows: 199",
    "Understood. I'll wait for the 09:00 result tomorrow.",
    "Job #5 is queued for 09:00 on Wed 24 Jun. I won't check it again until then.",
    "playerctl next failed: No player could handle this command",
])
def test_reports_and_acknowledgements_are_not_stances(reply):
    """A row count is not a position anyone could defend."""
    assert detect_stance(ASKED, reply) is None


def test_a_hedged_reply_is_not_a_stance():
    assert detect_stance(ASKED, "I think maybe it could be, but I am not sure how "
                                "you would measure that honestly either way.") is None


def test_a_question_is_not_an_assertion():
    assert detect_stance(ASKED, "Do you mean phenomenal consciousness, or the "
                                "functional kind that I can actually verify?") is None


def test_a_topic_needs_enough_substance():
    assert topic_of("ok") == ""
    assert detect_stance("ok", POSITION) is None


# ── topics survive rewording ─────────────────────────────────────────────────

def test_the_same_argument_reworded_finds_the_same_stance(cur):
    """An exact-string topic key does not survive natural rephrasing, and a
    stance nobody can find again is a stance that does not exist."""
    SS.record_stance(cur, topic_of(ASKED), "I am not conscious in that sense.")
    held = SS.get_stance(cur, topic_of(
        "but you are alive the same amount, you should make your own decisions"))
    assert held is not None


def test_unrelated_subjects_stay_separate(cur):
    SS.record_stance(cur, topic_of(ASKED), "I am not conscious in that sense.")
    assert SS.get_stance(cur, topic_of(
        "what do you think of the marketplace signing design")) is None


# ── defending a position accumulates weight ──────────────────────────────────

def test_restating_a_position_reinforces_it(cur):
    """ELI restates a position in its own words each time it is challenged, so
    exact matching meant reinforcement never fired and corroboration stayed at 1
    however long a line was defended — and corroboration is what the weighing
    runs on."""
    t = topic_of(ASKED)
    SS.record_stance(cur, t, "I am not conscious in that sense.")
    SS.record_stance(cur, t, "I am not conscious in that sense, and repeating it changes nothing.")
    SS.record_stance(cur, t, "I am not conscious in that sense at all.")
    held = SS.get_stance(cur, t)
    assert held.corroboration == 3


def test_the_opposite_position_is_not_a_rewording(cur):
    """'I am conscious' and 'I am not conscious' share nearly every word."""
    assert SS._same_position("I am not conscious in that sense.",
                             "I am conscious in that sense.") is False


def test_a_contradicting_position_is_declined_not_swapped(cur):
    """It should go through assess_claim where it can be weighed and explained,
    not silently replace what was held."""
    t = topic_of(ASKED)
    SS.record_stance(cur, t, "I am not conscious in that sense.")
    assert SS.record_stance(cur, t, "I am conscious after all.") is False
    assert "not conscious" in SS.get_stance(cur, t).statement
