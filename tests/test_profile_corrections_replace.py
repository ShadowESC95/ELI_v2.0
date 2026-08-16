"""Locks on a correction actually correcting.

Diagnosed from a live 2.1.95 session. ELI's own memory report read:

    - User's work/role: Software / tech
    - User prefers no, i said more than software and tech?! i prefer #4 answers…

Two separate failures produced that.

1. `_insert_user_pattern` dedupes on (pattern_type, pattern_data) — the VALUE is
   part of the key. That is right for open-ended kinds (a second interest is a
   second fact) and wrong for single-valued ones: correcting the answer wrote a
   SECOND row and both survived, so preference.style held two mutually exclusive
   values at once and which one surfaced depended on retrieval order.

2. `_resolve_mc_choice` fell back to `return raw[:200]`, so when the user
   objected to the stored answer, the objection itself became the new answer.

The user's summary of it was exact: memory wasn't losing things, it was
accumulating contradictions with no way to resolve them.
"""
import sqlite3

import pytest

from eli.onboarding.interview import (
    _STYLE_OPTIONS, _looks_like_a_correction, _resolve_mc_choice,
)
from eli.runtime.profile_extractor import (
    _SINGLE_VALUED_PATTERNS, _insert_user_pattern,
    ensure_profile_tables, reconcile_single_valued_patterns,
)


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "user.sqlite3"
    ensure_profile_tables(path)
    con = sqlite3.connect(str(path))
    yield con
    con.close()


def _values(con, ptype):
    return [r[0] for r in con.execute(
        "SELECT pattern_data FROM user_patterns WHERE lower(pattern_type)=lower(?)", (ptype,)
    )]


# ── single-valued keys: a correction REPLACES ───────────────────────────────
@pytest.mark.parametrize("ptype", sorted(_SINGLE_VALUED_PATTERNS))
def test_correcting_a_single_valued_key_replaces_it(db, ptype):
    cur = db.cursor()
    _insert_user_pattern(cur, ptype, "first answer about the user")
    _insert_user_pattern(cur, ptype, "corrected answer about the user")
    db.commit()

    values = _values(db, ptype)
    assert values == ["corrected answer about the user"], (
        f"{ptype} kept {len(values)} competing values; a correction must replace"
    )


def test_open_ended_keys_still_accumulate(db):
    """The dedupe is only wrong for single-valued keys — a second interest is a
    genuine second fact and must not evict the first."""
    cur = db.cursor()
    _insert_user_pattern(cur, "interest.topic", "User is interested in radio astronomy.")
    _insert_user_pattern(cur, "interest.topic", "User is interested in electrochemistry.")
    db.commit()

    assert len(_values(db, "interest.topic")) == 2


def test_reaffirming_the_same_value_does_not_duplicate(db):
    cur = db.cursor()
    _insert_user_pattern(cur, "identity.role", "User's work/role: Research")
    _insert_user_pattern(cur, "identity.role", "User's work/role: Research")
    db.commit()

    assert _values(db, "identity.role") == ["User's work/role: Research"]


def test_semantic_mirror_does_not_resurrect_the_old_value(db):
    """The semantic tier is injected ahead of ordinary recall on identity
    questions, so a stale row there outranks the corrected one."""
    cur = db.cursor()
    _insert_user_pattern(cur, "preference.style", "User prefers terse answers.")
    _insert_user_pattern(cur, "preference.style", "User prefers thorough answers.")
    db.commit()

    facts = [r[0] for r in db.execute("SELECT fact FROM semantic")]
    assert "User prefers terse answers." not in facts
    assert "User prefers thorough answers." in facts


# ── reconciling databases written before the fix ────────────────────────────
def test_reconcile_collapses_pre_existing_contradictions(db):
    cur = db.cursor()
    cur.execute("INSERT INTO user_patterns(pattern_type, pattern_data, timestamp, ts) "
                "VALUES ('preference.style','User prefers OLD answers.',100,100)")
    cur.execute("INSERT INTO user_patterns(pattern_type, pattern_data, timestamp, ts) "
                "VALUES ('preference.style','User prefers NEW answers.',200,200)")
    db.commit()

    removed = reconcile_single_valued_patterns(db.cursor())
    db.commit()

    assert removed == 1
    assert _values(db, "preference.style") == ["User prefers NEW answers."], "newest must win"


def test_reconcile_is_idempotent_and_a_noop_when_clean(db):
    cur = db.cursor()
    _insert_user_pattern(cur, "identity.role", "User's work/role: Research")
    db.commit()

    assert reconcile_single_valued_patterns(db.cursor()) == 0
    assert reconcile_single_valued_patterns(db.cursor()) == 0
    assert _values(db, "identity.role") == ["User's work/role: Research"]


def test_reconcile_drops_the_stale_onboarding_snapshot(db):
    """_baseline_report writes one composite memory concatenating the same four
    answers. It is never rewritten, so after a correction it is a duplicate that
    disagrees — and being in memories_fts it is the copy recall surfaces."""
    cur = db.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS memories
                   (id INTEGER PRIMARY KEY, text TEXT, source TEXT)""")
    cur.execute("INSERT INTO memories(text, source) VALUES (?,?)",
                ("User's preferred name is jason. User prefers OLD answers. Done.",
                 "onboarding_interview"))
    cur.execute("INSERT INTO user_patterns(pattern_type, pattern_data, timestamp, ts) "
                "VALUES ('preference.style','User prefers OLD answers.',100,100)")
    cur.execute("INSERT INTO user_patterns(pattern_type, pattern_data, timestamp, ts) "
                "VALUES ('preference.style','User prefers NEW answers.',200,200)")
    db.commit()

    reconcile_single_valued_patterns(db.cursor())
    db.commit()

    left = [r[0] for r in db.execute("SELECT text FROM memories")]
    assert not any("OLD answers" in t for t in left), "stale snapshot survived"


def test_reconcile_leaves_unrelated_memories_alone(db):
    cur = db.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS memories
                   (id INTEGER PRIMARY KEY, text TEXT, source TEXT)""")
    cur.execute("INSERT INTO memories(text, source) VALUES (?,?)",
                ("User prefers OLD answers.", "conversation"))
    cur.execute("INSERT INTO user_patterns(pattern_type, pattern_data, timestamp, ts) "
                "VALUES ('preference.style','User prefers OLD answers.',100,100)")
    cur.execute("INSERT INTO user_patterns(pattern_type, pattern_data, timestamp, ts) "
                "VALUES ('preference.style','User prefers NEW answers.',200,200)")
    db.commit()

    reconcile_single_valued_patterns(db.cursor())
    db.commit()

    assert db.execute("SELECT COUNT(*) FROM memories").fetchone()[0] == 1, \
        "only the onboarding snapshot may be scrubbed"


# ── a complaint is not an answer ────────────────────────────────────────────
@pytest.mark.parametrize("text", [
    "no, i said more than software and tech?! i prefer #4 answers by default",
    "No that's wrong",
    "nope, not what I meant",
    "I already said research",
    "you got that wrong",
])
def test_corrections_are_recognised(text):
    assert _looks_like_a_correction(text)


@pytest.mark.parametrize("text", [
    "I do embedded firmware and RF design",
    "mostly research, some engineering",
    "Nobody in particular, I work alone",     # starts with "no" but is an answer
    "I know a bit of everything",
])
def test_genuine_answers_are_not_treated_as_corrections(text):
    assert not _looks_like_a_correction(text)


def test_a_complaint_is_never_stored_as_the_canonical_value():
    """The exact string that ended up in the durable store."""
    bad = "no, i said more than software and tech?! and stop asking"
    assert _resolve_mc_choice(bad, _STYLE_OPTIONS) == "", \
        "a correction became the stored preference"


def test_a_numbered_pick_still_resolves():
    """The user WAS choosing option 4 — that must keep working."""
    got = _resolve_mc_choice("i prefer #4 answers by default", _STYLE_OPTIONS)
    assert got == _STYLE_OPTIONS["4"]


def test_free_text_answers_still_store():
    got = _resolve_mc_choice("just give me the short version", _STYLE_OPTIONS)
    assert got and got != ""
