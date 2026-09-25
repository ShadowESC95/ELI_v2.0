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
    claims.record(conn, "work_schedule", "Nights", now=_d("2026-07-01"))
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
