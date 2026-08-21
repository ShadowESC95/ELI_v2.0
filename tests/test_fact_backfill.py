"""Historical conversations get mined for durable facts, once, safely.

Fact extraction only runs at session end, so everything said before it existed
stays unmined. On a real install that is 64 sessions and 353 user turns producing
**10** `user_patterns` — and since promotion fans out from that table, the
semantic tier (6 rows) and the knowledge graph inherit the starvation.

The 59 summaries already on disk cannot be re-routed instead: they were written
by the older prompt and contain no USER FACTS section, so there is nothing in
them to route. The sessions have to be re-read.

The properties under test are the operational ones, not the extraction — that is
the live path's, already covered. A 30-minute job that cold-loads a model, or
restarts from zero when interrupted, is worse than no job at all.
"""
from __future__ import annotations

import sqlite3

import pytest

from eli.runtime import profile_extractor as PE


SUMMARY = (
    "SUMMARY: worked on the electrolyser.\n"
    "CURRENT WORK: stack assembly.\n"
    "USER FACTS:\n"
    "- User researches entropy and coherence fields\n"
    "- User is building a solar-to-hydrogen electrolyser\n"
)


class _Broker:
    """Stands in for the resident GGUF. Counts calls so we can assert the job
    does not re-do work it has already done."""
    gguf_ready = True

    def __init__(self):
        self.calls = 0

    def infer(self, prompt, system="", max_tokens=0, temperature=0.0):
        self.calls += 1
        return SUMMARY


@pytest.fixture()
def db(tmp_path):
    path = tmp_path / "user.sqlite3"
    PE.ensure_profile_tables(path)
    con = sqlite3.connect(str(path))
    cur = con.cursor()
    # conversation_turns belongs to Memory, not the profile extractor, so
    # ensure_profile_tables does not create it.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS conversation_turns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT, user_id TEXT, role TEXT, content TEXT,
            ts REAL, timestamp REAL
        )""")
    for s in range(3):
        for t in range(6):
            role = "user" if t % 2 == 0 else "assistant"
            cur.execute(
                "INSERT INTO conversation_turns (session_id, role, content, ts, timestamp) "
                "VALUES (?,?,?,?,?)",
                (f"s{s}", role, f"turn {t} of session {s}, about the electrolyser",
                 1000 + s * 100 + t, 1000 + s * 100 + t),
            )
    # A session too short to carry a durable fact.
    cur.execute("INSERT INTO conversation_turns (session_id, role, content, ts, timestamp) "
                "VALUES ('tiny','user','hi',9000,9000)")
    con.commit()
    con.close()
    return path


def _patterns(path):
    con = sqlite3.connect(str(path))
    try:
        return con.execute("SELECT COUNT(*) FROM user_patterns").fetchone()[0]
    finally:
        con.close()


# ── the gate ─────────────────────────────────────────────────────────────────

def test_it_never_cold_loads_a_model(db, monkeypatch):
    """Pulling gigabytes off disk to mine history is never worth it. With no
    broker passed and nothing resident, it must decline rather than load."""
    import eli.cognition.gguf_inference as gi
    monkeypatch.setattr(gi, "is_loaded", lambda: False, raising=False)

    out = PE.backfill_facts_from_sessions(db_path=db)
    assert out["sessions_processed"] == 0
    assert "no model resident" in out["reason"]


# ── the work ─────────────────────────────────────────────────────────────────

def test_it_mines_historical_sessions(db):
    before = _patterns(db)
    out = PE.backfill_facts_from_sessions(db_path=db, broker=_Broker())
    assert out["sessions_processed"] == 3
    assert _patterns(db) > before
    assert out["patterns_added"] == _patterns(db) - before


def test_facts_reach_the_semantic_tier(db):
    """The point of the exercise: promotion fans out from user_patterns, so a
    fact that stops there has not actually widened anything."""
    PE.backfill_facts_from_sessions(db_path=db, broker=_Broker())
    con = sqlite3.connect(str(db))
    try:
        n = con.execute("SELECT COUNT(*) FROM semantic").fetchone()[0]
    finally:
        con.close()
    assert n > 0


def test_sessions_too_short_to_carry_a_fact_are_skipped(db):
    out = PE.backfill_facts_from_sessions(db_path=db, broker=_Broker())
    assert out["skipped_thin"] >= 1


# ── resumability ─────────────────────────────────────────────────────────────

def test_a_second_run_does_not_redo_the_work(db):
    """~25s per session means a full history is ~30 minutes. Restarting from
    zero after an interruption would make the job unusable."""
    b1 = _Broker()
    PE.backfill_facts_from_sessions(db_path=db, broker=b1)
    # The exact first-run count is incidental — the summariser may infer more
    # than once per session. What matters is that work happened.
    assert b1.calls > 0

    b2 = _Broker()
    out = PE.backfill_facts_from_sessions(db_path=db, broker=b2)
    assert b2.calls == 0, "re-summarised sessions it had already mined"
    # All four, not three: a session too thin to carry a fact is still one this
    # pass has CONSIDERED, and re-reading it every run costs time to reach the
    # same conclusion.
    assert out["skipped_done"] == 4


def test_running_it_twice_does_not_duplicate_patterns(db):
    PE.backfill_facts_from_sessions(db_path=db, broker=_Broker())
    n1 = _patterns(db)
    PE.backfill_facts_from_sessions(db_path=db, broker=_Broker())
    assert _patterns(db) == n1


def test_limit_allows_a_partial_run(db):
    out = PE.backfill_facts_from_sessions(db_path=db, broker=_Broker(), limit=1)
    assert out["sessions_processed"] == 1


def test_oldest_sessions_are_mined_first(db):
    """If it is stopped halfway, the history you would never otherwise revisit
    is the part that got done."""
    seen = []
    PE.backfill_facts_from_sessions(
        db_path=db, broker=_Broker(), limit=2,
        progress=lambda done, total, sid: seen.append(sid))
    assert seen == sorted(seen), seen
    assert seen[0] == "s0"


def test_progress_is_reported(db):
    seen = []
    PE.backfill_facts_from_sessions(
        db_path=db, broker=_Broker(),
        progress=lambda done, total, sid: seen.append((done, total)))
    assert seen and seen[-1][0] == seen[-1][1]


def test_a_broken_progress_callback_does_not_stop_the_job(db):
    def boom(*a):
        raise RuntimeError("ui exploded")
    out = PE.backfill_facts_from_sessions(db_path=db, broker=_Broker(), progress=boom)
    assert out["sessions_processed"] == 3


def test_an_empty_database_is_handled(tmp_path):
    path = tmp_path / "empty.sqlite3"
    PE.ensure_profile_tables(path)
    out = PE.backfill_facts_from_sessions(db_path=path, broker=_Broker())
    assert out["sessions_processed"] == 0
