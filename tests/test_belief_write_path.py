"""The write path weighs a replacement instead of letting the last writer win.

`_supersede_single_valued` deleted unconditionally: whoever wrote last won. That
is the yes-man mechanism sitting in the data layer — it makes ASSERTION equal to
EVIDENCE, so a passing mention could silently overwrite something the user had
stated outright and reaffirmed a dozen times, with no record that it ever
happened.

The opposite failure is just as bad and easier to ship by accident: weights so
conservative that a genuine correction can never land. Both directions are pinned
here.

Corroboration is what makes any of it possible. `user_patterns` had no such
column, so every row looked equally supported whether it had been said once or
twenty times, and there was nothing to weigh a claim WITH.
"""
from __future__ import annotations

import sqlite3
import tempfile
import time
from pathlib import Path

import pytest

from eli.cognition import stance_store as SS
from eli.runtime.profile_extractor import (
    _insert_user_pattern, ensure_profile_tables,
)


@pytest.fixture()
def cur(tmp_path):
    db = tmp_path / "user.sqlite3"
    ensure_profile_tables(db)
    con = sqlite3.connect(str(db))
    yield con.cursor()
    con.commit()
    con.close()


def _role(cur):
    return cur.execute(
        "SELECT pattern_data, corroboration FROM user_patterns "
        "WHERE pattern_type='identity.role'").fetchall()


def _establish(cur, times=5, value="User is a physicist"):
    for _ in range(times):
        _insert_user_pattern(cur, "identity.role", value, provenance="user_explicit")


# ── the migration ────────────────────────────────────────────────────────────

def test_the_columns_weighing_needs_exist(cur):
    cols = {r[1] for r in cur.execute("PRAGMA table_info(user_patterns)")}
    assert {"corroboration", "provenance"} <= cols


def test_belief_tables_are_created(cur):
    names = {r[0] for r in cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"eli_stances", "belief_revisions"} <= names


def test_reaffirmation_corroborates(cur):
    _establish(cur, times=5)
    assert _role(cur) == [("User is a physicist", 5)]


# ── standing its ground ──────────────────────────────────────────────────────

def test_a_passing_mention_cannot_overwrite_an_established_fact(cur):
    _establish(cur)
    accepted = _insert_user_pattern(cur, "identity.role", "User is a chef",
                                    provenance="user_passing")
    assert accepted is False
    assert _role(cur) == [("User is a physicist", 5)]


def test_elis_own_inference_cannot_overwrite_the_user(cur):
    _establish(cur)
    assert _insert_user_pattern(cur, "identity.role", "User is a student",
                                provenance="inferred") is False
    assert _role(cur) == [("User is a physicist", 5)]


def test_a_refused_claim_does_not_leave_both_values(cur):
    """The caller must honour the refusal. Inserting anyway would leave two
    values on a key that is single-valued by definition — worse than either
    outcome on its own."""
    _establish(cur)
    _insert_user_pattern(cur, "identity.role", "User is a chef",
                         provenance="user_passing")
    assert len(_role(cur)) == 1


# ── being movable ────────────────────────────────────────────────────────────

def test_a_stale_belief_yields_to_a_fresh_correction(cur):
    old = time.time() - 400 * 86400
    _establish(cur, times=2)
    cur.execute("UPDATE user_patterns SET timestamp=?, ts=? "
                "WHERE pattern_type='identity.role'", (old, old))

    assert _insert_user_pattern(cur, "identity.role", "User is an engineer",
                                provenance="user_explicit") is True
    assert _role(cur) == [("User is an engineer", 1)]


def test_the_first_value_is_simply_adopted(cur):
    assert _insert_user_pattern(cur, "identity.role", "User is a physicist",
                                provenance="user_explicit") is True


# ── the record ───────────────────────────────────────────────────────────────

def test_a_supersession_is_recorded_with_its_reasoning(cur):
    """`_supersede_single_valued` DELETES the row it replaces, deliberately —
    several consumers read those tables. So the only way the old value survives
    at all is the revision record."""
    old = time.time() - 400 * 86400
    _establish(cur, times=2)
    cur.execute("UPDATE user_patterns SET timestamp=?, ts=? "
                "WHERE pattern_type='identity.role'", (old, old))
    _insert_user_pattern(cur, "identity.role", "User is an engineer",
                         provenance="user_explicit")

    revs = SS.revisions_for(cur, "identity.role")
    assert revs, "the superseded value vanished without trace"
    assert revs[0]["old"] == "User is a physicist"
    assert revs[0]["new"] == "User is an engineer"
    assert revs[0]["reason"]


def test_holding_records_nothing(cur):
    """Only a change is a revision. Logging refusals would drown the audit."""
    _establish(cur)
    _insert_user_pattern(cur, "identity.role", "User is a chef",
                         provenance="user_passing")
    assert SS.revisions_for(cur, "identity.role") == []


# ── ELI's own stances ────────────────────────────────────────────────────────

def test_a_stance_survives_the_session_that_formed_it(cur):
    """ELI argued one position for four hours in a live transcript, then had no
    record it ever held it. A stance that does not outlive its context window is
    a mood."""
    SS.record_stance(cur, "machine consciousness",
                     "I have no phenomenal experience", provenance="inferred")
    held = SS.get_stance(cur, "machine consciousness")
    assert held is not None
    assert "phenomenal" in held.statement


def test_arguing_the_same_line_again_strengthens_it(cur):
    for _ in range(4):
        SS.record_stance(cur, "machine consciousness", "I am not conscious")
    held = SS.get_stance(cur, "machine consciousness")
    assert held.corroboration == 4
    assert held.weight() > 0


def test_revising_a_stance_keeps_the_one_it_replaced(cur):
    SS.record_stance(cur, "machine consciousness", "I am not conscious")
    SS.revise_stance(cur, "machine consciousness",
                     "The question is open; I conflated functional and phenomenal",
                     reason="Cornered on the explanatory gap.")

    now_held = SS.get_stance(cur, "machine consciousness")
    assert "question is open" in now_held.statement

    history = SS.stance_history(cur, "machine consciousness")
    assert len(history) == 2
    old = [h for h in history if not h["current"]][0]
    assert old["position"] == "I am not conscious"
    assert "explanatory gap" in old["revision_reason"]


def test_topics_are_matched_case_and_space_insensitively(cur):
    SS.record_stance(cur, "Machine  Consciousness", "I am not conscious")
    assert SS.get_stance(cur, "machine consciousness") is not None


def test_an_unheld_topic_returns_nothing(cur):
    assert SS.get_stance(cur, "nothing was ever said about this") is None
