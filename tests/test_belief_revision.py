"""ELI holds a position, and it takes evidence — not assertion — to move it.

The naive design is "the user said something different, so overwrite it". That is
what `_supersede_single_valued` does for its four hardcoded types, and it is the
mechanism that produces a yes-man: it makes ASSERTION equal to EVIDENCE, so
whoever spoke last is right. An assistant that cannot disagree is one whose
agreement carries no information.

The failure in the other direction is just as bad and easier to ship by accident:
weights so conservative that nothing can ever change ELI's mind. An early cut of
this had `CONCEDE_MARGIN = 1.35`, which corroboration alone could not reach, and a
corroboration curve that saturated at three observations — so four corrections and
ninety scored identically and CONCEDE was unreachable.

These tests pin the ladder in both directions.
"""
from __future__ import annotations

import time

import pytest

from eli.cognition.belief import (
    CONCEDE, HOLD, QUESTION, Belief, assess_claim, concede, corroborate,
)


NOW = time.time()


def _held(**kw):
    d = dict(statement="User is an independent physicist",
             provenance="user_explicit", corroboration=5, last_seen=NOW)
    d.update(kw)
    return Belief(**d)


def _claim(**kw):
    d = dict(statement="User is an engineer", provenance="user_explicit",
             corroboration=1, last_seen=NOW)
    d.update(kw)
    return Belief(**d)


# ── standing its ground ──────────────────────────────────────────────────────

def test_a_passing_mention_does_not_overturn_a_corroborated_belief():
    v = assess_claim(_held(), _claim(provenance="user_passing"), NOW)
    assert v.action == HOLD
    assert not v.agrees


def test_elis_own_inference_never_outranks_the_user_on_their_own_life():
    """ELI guessing about the user is the weakest evidence in the room."""
    v = assess_claim(_held(), _claim(provenance="inferred"), NOW)
    assert v.action == HOLD


def test_holding_explains_what_it_is_standing_on():
    """A refusal with no reasoning is indistinguishable from stubbornness."""
    v = assess_claim(_held(), _claim(provenance="user_passing"), NOW)
    assert v.reasons
    assert any("held" in r.lower() or "supported" in r.lower() for r in v.reasons)


# ── being movable ────────────────────────────────────────────────────────────

def test_a_direct_correction_at_least_opens_the_question():
    """The user is authoritative about themselves. Scoring this HOLD is not a
    colleague standing firm, it is someone who will not listen."""
    assert assess_claim(_held(), _claim(), NOW).action == QUESTION


def test_a_stale_belief_yields_to_a_fresh_one():
    stale = _held(statement="User lives in Cork", corroboration=2,
                  last_seen=NOW - 400 * 86400)
    fresh = _claim(statement="User lives in Dublin")
    assert assess_claim(stale, fresh, NOW).action == CONCEDE


def test_nothing_held_means_simply_adopt_it():
    v = assess_claim(None, _claim(), NOW)
    assert v.action == CONCEDE and v.standing is None


def test_conceding_is_reachable_at_all():
    """CONCEDE_MARGIN must sit inside the range the weights can actually produce.
    A margin corroboration cannot reach makes ELI unable to change its mind —
    the opposite failure to the yes-man, and just as useless."""
    best = _claim(corroboration=200)
    worst = _held(corroboration=1, provenance="inferred", last_seen=NOW - 500 * 86400)
    assert assess_claim(worst, best, NOW).action == CONCEDE


# ── the weights themselves ───────────────────────────────────────────────────

def test_corroboration_never_fully_saturates():
    """It must keep ordering all the way up, or sustained correction is
    indistinguishable from a single repeat."""
    a = _claim(corroboration=4).weight(NOW)
    b = _claim(corroboration=12).weight(NOW)
    c = _claim(corroboration=60).weight(NOW)
    assert a < b < c


def test_more_corroboration_is_worth_less_each_time():
    w = [_claim(corroboration=n).weight(NOW) for n in (1, 2, 3, 4, 5)]
    gains = [w[i + 1] - w[i] for i in range(len(w) - 1)]
    assert all(gains[i] > gains[i + 1] for i in range(len(gains) - 1)), gains


def test_provenance_is_ordered_as_intended():
    order = ["inferred", "observed", "document", "user_passing", "user_explicit"]
    weights = [_claim(provenance=p).weight(NOW) for p in order]
    assert weights == sorted(weights)


def test_evidence_ages_but_does_not_expire():
    """'I was born in Dublin' does not stop being true because it is old."""
    old = _claim(last_seen=NOW - 3000 * 86400).weight(NOW)
    new = _claim(last_seen=NOW).weight(NOW)
    assert old < new
    assert old > new * 0.45, "an old fact must not decay to nothing"


# ── updating ─────────────────────────────────────────────────────────────────

def test_corroboration_strengthens_and_refreshes():
    b = _claim(corroboration=2, last_seen=NOW - 10 * 86400, confidence=0.8)
    before = b.weight(NOW)
    corroborate(b, provenance="user_explicit", now=NOW)
    assert b.corroboration == 3
    assert b.weight(NOW) > before


def test_provenance_can_be_upgraded_but_not_downgraded():
    b = _claim(provenance="inferred")
    corroborate(b, provenance="user_explicit", now=NOW)
    assert b.provenance == "user_explicit"
    corroborate(b, provenance="user_passing", now=NOW)
    assert b.provenance == "user_explicit", "a passing mention must not weaken it"


def test_conceding_records_what_changed_and_why():
    """'I thought X until you corrected me in March' is a thing a colleague can
    say and a mirror cannot — and it is the only way a wrong revision is ever
    caught."""
    standing, challenger = _held(), _claim()
    concede(standing, challenger, reason="You corrected this directly.", now=NOW)
    assert standing.superseded_by == challenger.statement
    assert standing.revised_at == NOW
    assert "corrected" in standing.revision_reason


def test_the_verdict_carries_everything_needed_to_explain_itself():
    """The persona layer phrases this in ELI's own words — a canned 'I disagree
    because...' string would be the same yes-man problem in different clothes."""
    d = assess_claim(_held(), _claim(provenance="user_passing"), NOW).as_dict()
    assert set(d) >= {"action", "standing", "challenger", "standing_weight",
                      "challenger_weight", "ratio", "reasons"}
    assert d["reasons"]
