"""A changed fact supersedes the old one and keeps it as dated history; both what held and what ELI knew are answerable."""
import sqlite3
import time

import pytest

from eli.memory import claims
from eli.memory.memory import Memory
from eli.memory.retrieval import _claim_hits


def _d(s):
    return time.mktime(time.strptime(s, "%Y-%m-%d"))


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    claims.record(c, "work_schedule", "days", valid_from=_d("2026-01-01"), now=_d("2026-01-02"))
    claims.record(c, "work_schedule", "nights", valid_from=_d("2026-06-01"), now=_d("2026-06-03"))
    return c


def test_the_new_value_supersedes_and_the_old_is_history(conn):
    assert [c["value"] for c in claims.current(conn)] == ["nights"]
    assert [(c["value"], c["status"]) for c in claims.history(conn, "work_schedule")] == [("days", "superseded"), ("nights", "current")]


def test_what_held_in_a_period(conn):
    spring = claims.valid_during(conn, _d("2026-03-01"), _d("2026-04-01"))
    assert [c["value"] for c in spring] == ["days"]


def test_what_eli_knew_at_a_date(conn):
    assert [c["value"] for c in claims.known_at(conn, _d("2026-03-01"))] == ["days"]
    assert [c["value"] for c in claims.known_at(conn, _d("2026-07-01"))] == ["nights"]


def test_the_same_value_confirms_instead_of_duplicating(conn):
    claims.record(conn, "work_schedule", "Nights", now=_d("2026-07-01"), root_id=11)
    claims.record(conn, "work_schedule", "nights", now=_d("2026-07-02"), root_id=11)
    claims.record(conn, "work_schedule", "nights", now=_d("2026-07-03"), root_id=12)
    rows = claims.history(conn, "work_schedule")
    assert len(rows) == 2 and rows[-1]["confirmations"] == 2


def test_no_longer_retires_and_used_to_is_only_history(conn):
    claims.record_from_text(conn, "I used to work evenings", when=_d("2026-08-01"))
    assert [c["value"] for c in claims.current(conn)] == ["nights"]
    claims.record_from_text(conn, "I no longer work nights", when=_d("2026-08-15"))
    assert claims.current(conn) == []


def test_only_statements_are_read_not_questions(conn):
    assert claims.extract("Do I work nights?") == []
    assert claims.extract("I love pizza") == []
    assert {c["relation"] for c in claims.extract("I work at Acme Corp and my dog is called Max")} == {"employer", "dog_name"}


def test_deleting_the_source_withdraws_the_claim():
    c = sqlite3.connect(":memory:")
    claims.record(c, "lives_in", "Berlin", source_memory_id=7)
    assert claims.retract_from_memory(c, 7) == 1
    assert claims.current(c) == []


@pytest.fixture()
def mem(tmp_path, monkeypatch):
    monkeypatch.setenv("ELI_TEST_MODE", "1")
    monkeypatch.setattr("eli.memory.vector_store.get_vector_store", lambda: None)
    return Memory(db_path=tmp_path / "user.sqlite3")


def test_a_stored_statement_becomes_a_claim_and_a_change_supersedes(mem):
    mem.store_memory("I work days at the warehouse most weeks", source="user")
    mem.store_memory("I work nights now, the warehouse changed my shift", source="user")
    assert [c["value"] for c in mem.claims_current() if c["relation"] == "work_schedule"] == ["nights"]
    assert [c["value"] for c in mem.claim_history("work_schedule")] == ["days", "nights"]


def test_claims_reach_the_evidence_for_a_question_about_them(mem):
    mem.store_memory("I work nights now, the warehouse changed my shift", source="user")
    hits = _claim_hits(mem, "what do you know about my work schedule", None)
    assert hits and "nights" in hits[0]["text"] and hits[0]["id"].startswith("claim:")
    assert _claim_hits(mem, "what is the capital of France", None) == []


def test_a_period_question_gets_what_held_then(mem):
    now = time.time()
    c = mem._claims_conn()
    claims.record(c, "work_schedule", "days", valid_from=now - 200 * 86400, now=now - 199 * 86400)
    claims.record(c, "work_schedule", "nights", valid_from=now - 20 * 86400, now=now - 19 * 86400)
    c.commit()
    c.close()
    hits = _claim_hits(mem, "what was my job schedule then", (now - 120 * 86400, now - 100 * 86400))
    assert len(hits) == 1 and "days" in hits[0]["text"]


def test_a_claim_that_is_not_the_users_own_word_is_disputed_not_substituted():
    conn = sqlite3.connect(":memory:")
    claims.record(conn, "lives_in", "Berlin", origin="user_said", now=_d("2026-05-01"))
    claims.record(conn, "lives_in", "Oslo", origin="eli_said", now=_d("2026-06-01"))
    assert [c["value"] for c in claims.current(conn)] == ["Berlin"]
    conflict = claims.open_conflicts(conn)[0]
    assert [c["value"] for c in conflict["disputed"]] == ["Oslo"] and conflict["standing"][0]["contested"] == 1
    assert "Berlin" in claims.conflict_question(conflict) and "Oslo" in claims.conflict_question(conflict)


def test_the_user_settles_a_conflict():
    conn = sqlite3.connect(":memory:")
    claims.record(conn, "lives_in", "Berlin", origin="user_said", now=_d("2026-05-01"))
    claims.record(conn, "lives_in", "Oslo", origin="eli_said", now=_d("2026-06-01"))
    claims.resolve_conflict(conn, "lives_in", "Oslo", now=_d("2026-06-05"))
    assert [c["value"] for c in claims.current(conn)] == ["Oslo"] and claims.open_conflicts(conn) == []
    assert [c["status"] for c in claims.history(conn, "lives_in")] == ["superseded", "current"]


def test_hedged_and_hypothetical_statements_are_not_claims():
    for t in ("maybe I will work nights", "I might move to Berlin next year", "I am thinking of working at Acme Corp", "what if I work nights"):
        assert claims.extract(t) == []


def test_a_disputed_claim_reaches_the_evidence_marked(mem):
    mem.store_memory("I live in Berlin these days with my partner", source="user")
    c = mem._claims_conn()
    claims.record(c, "lives_in", "Oslo", origin="eli_said")
    c.commit()
    c.close()
    text = " ".join(h["text"] for h in _claim_hits(mem, "where do I live, what do you know about me", None))
    assert "Berlin" in text and "DISPUTED" in text


# "What am I watching?" is answered from the newest thing the user said or ELI saw, with dates.
#
# Live: the user said "GOT is on in the background" a week earlier and ELI's own pause replies named
# "Game of Thrones — S2 E5", yet ELI answered with a show from a month before and then said there was no
# record of GOT. Nothing about what the user was watching ever became a claim: the extractor knew only
# jobs, homes and pets, and only read the messages the storage policy kept.
def _dt(s):
    return time.mktime(time.strptime(s, "%Y-%m-%d %H:%M"))


@pytest.mark.parametrize("said,expected", [
    ("Just woke up, GOT is on in the bckground, and i am checking in", ("watching", "GOT")),
    ("i just told you that i am watching GOT!!!", ("watching", "GOT")),
    ("all done with that. I'm actually watching TWD dead city", ("watching", "TWD dead city")),
    ("looks like you are back. Still watching dead city TWD, bud.", ("watching", "dead city TWD")),
    ("all good, still watching the walking dead", ("watching", "the walking dead")),
    ("i am still watching the matrix now, it is on its 4th film", ("watching", "the matrix")),
    ("I've been playing Baldur's Gate 3 all week", ("playing", "Baldur's Gate 3")),
    ("I'm reading Dune at the moment", ("reading", "Dune")),
    ("there is never any quiet, and i am watching the walking dead, you?", ("watching", "the walking dead")),
])
def test_what_the_user_is_doing_now(said, expected):
    assert [(a["relation"], a["value"]) for a in claims.activities(said)] == [expected]


@pytest.mark.parametrize("said", [
    "You remember what I am currently watching?",
    "check again for what series i am currently watching please!!",
    "no, i am asking you what is the latest show i am watching",
    "now i am going to play fallout 4 and watch something",
    "the headache and watching it was a few days ago",
    "I'm not watching anything",
    "i played xcom 2 last night",
    "i am watching ____ and about to start playing ____.",
    "maybe i'm watching it later",
])
def test_questions_plans_and_the_past_are_not_claims(said):
    assert claims.activities(said) == []


def test_the_newest_wins_and_an_older_statement_is_history():
    conn = sqlite3.connect(":memory:")
    claims.record(conn, "watching", "Dead City", valid_from=_dt("2026-09-01 20:00"))
    claims.record(conn, "watching", "GOT", valid_from=_dt("2026-10-01 09:00"))
    claims.record(conn, "watching", "The Matrix", valid_from=_dt("2026-08-25 14:00"))   # read back late
    assert [c["value"] for c in claims.current(conn)] == ["GOT"]
    old = [c for c in claims.history(conn, "watching") if c["value"] == "The Matrix"][0]
    assert old["status"] == "superseded" and old["valid_to"] == _dt("2026-10-01 09:00")


def test_what_eli_saw_playing_replaces_what_was_said_and_initials_are_the_same_show():
    conn = sqlite3.connect(":memory:")
    claims.record(conn, "watching", "Dead City", valid_from=_dt("2026-09-01 20:00"))
    claims.record(conn, "watching", "Game of Thrones", origin="observed", valid_from=_dt("2026-10-01 15:00"))
    assert [c["value"] for c in claims.current(conn)] == ["Game of Thrones"] and claims.open_conflicts(conn) == []
    claims.record(conn, "watching", "GOT", valid_from=_dt("2026-10-08 21:00"))          # the same show, confirmed
    assert [c["value"] for c in claims.current(conn)] == ["Game of Thrones"]


def test_an_episode_in_a_player_names_the_show():
    assert claims.observed_show("Game of Thrones — S1 E10 – Fire and Blood") == "Game of Thrones"
    assert claims.observed_show("Game of Thrones S02E05") == "Game of Thrones"
    assert claims.observed_show("Eminem — Trouble") == ""


def test_history_is_read_in_order_and_answers_the_question(mem):
    conn = mem._get_connection()
    for role, text, when in [
        ("user", "I'm actually watching Dead City", "2026-09-01 20:12"),
        ("user", "Just woke up, GOT is on in the background", "2026-10-01 09:15"),
        ("assistant", "Paused — chromium (Game of Thrones — S2 E5 – The Ghost of Harrenhal)", "2026-10-01 22:43"),
        ("user", "You remember what I am currently watching?", "2026-10-08 21:38"),
    ]:
        conn.execute("INSERT INTO conversation_turns (session_id, user_id, role, content, ts, timestamp) "
                     "VALUES ('s', 'u', ?, ?, ?, ?)", (role, text, _dt(when), _dt(when)))
    conn.commit()
    conn.close()
    assert mem.backfill_claims()["claims"] == 3
    assert mem.backfill_claims().get("skipped") == "current"
    hits = _claim_hits(mem, "what show am I currently watching", None)
    assert len(hits) == 1 and "watching: GOT" in hits[0]["text"] and "since 2026-10-01" in hits[0]["text"]


def test_a_message_said_in_passing_becomes_a_claim(mem):
    mem.add_conversation_turn("user", "just checking in, GOT is on in the background")
    assert [c["value"] for c in mem.claims_current() if c["relation"] == "watching"] == ["GOT"]
