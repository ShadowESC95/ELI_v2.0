"""Lessons expire, are checked against what happens next, and are retired when they do not help."""
import json
import sqlite3
import time

import pytest

from eli.runtime import lessons

DAY = 86400.0


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    c.executescript(lessons._SCHEMA)
    return c


def _make(conn, now=1000.0, **kw):
    return lessons.propose("SCREENSHOT", "SCREENSHOT failed with: no display", ["3 occurrences"],
                           "Check a display is available before SCREENSHOT", now=now, conn=conn, **kw)


def test_the_same_trigger_adds_evidence_not_a_second_lesson(conn):
    a = _make(conn)
    b = lessons.propose("SCREENSHOT", "SCREENSHOT failed with: no display", ["seen again"], "x", now=1001.0, conn=conn)
    assert a == b
    assert len(json.loads(conn.execute("select evidence from lessons").fetchone()[0])) == 2


def test_only_active_unexpired_lessons_for_the_action_apply(conn):
    _make(conn, now=1000.0, ttl_days=1)
    assert lessons.applicable("screenshot", now=1500.0, conn=conn)
    assert not lessons.applicable("OPEN_APP", now=1500.0, conn=conn)
    assert not lessons.applicable("SCREENSHOT", now=1000.0 + 2 * DAY, conn=conn)


def test_a_lesson_that_keeps_failing_is_retired(conn):
    lid = _make(conn)
    status = [lessons.record_outcome(lid, ok, now=2000.0 + i, conn=conn) for i, ok in enumerate([False, False, False])]
    assert status[-1] == "retired"
    assert "did not help" in conn.execute("select retired_reason from lessons").fetchone()[0]


def test_a_lesson_that_helps_survives_and_is_renewed(conn):
    lid = _make(conn, now=0.0, ttl_days=1)
    for i in range(4):
        lessons.record_outcome(lid, True, now=10.0 + i, conn=conn)
    assert lessons.review(now=2 * DAY, conn=conn) == {"retired": 0, "renewed": 1}
    assert lessons.applicable("SCREENSHOT", now=2 * DAY + 1, conn=conn)


def test_an_unconfirmed_lesson_expires(conn):
    _make(conn, now=0.0, ttl_days=1)
    assert lessons.review(now=2 * DAY, conn=conn) == {"retired": 1, "renewed": 0}
    assert conn.execute("select retired_reason from lessons").fetchone()[0] == "expired unconfirmed"


def test_failure_clusters_become_lessons(tmp_path, monkeypatch):
    db = tmp_path / "agent.sqlite3"
    c = sqlite3.connect(db)
    c.execute("create table error_tracking (id integer primary key, error_type text, details text, occurrence_count integer, last_seen real, timestamp real)")
    for n in range(3):
        c.execute("insert into error_tracking (error_type, details, occurrence_count, last_seen) values (?,?,?,?)",
                  ("no display", json.dumps({"action": "SCREENSHOT", "args": {"n": n}}), 1, time.time()))
    c.execute("insert into error_tracking (error_type, details, occurrence_count, last_seen) values ('rare', ?, 1, ?)",
              (json.dumps({"action": "OPEN_APP"}), time.time()))
    c.commit()
    c.close()
    monkeypatch.setattr("eli.core.paths.agent_db_path", lambda: db)
    made = lessons.from_failure_clusters()
    assert len(made) == 1
    row = sqlite3.connect(db).execute("select applies_to, proposed_change from lessons").fetchone()
    assert row[0] == "SCREENSHOT" and "no display" in row[1]


def test_finished_actions_give_active_lessons_a_check(tmp_path, monkeypatch):
    db = tmp_path / "agent.sqlite3"
    monkeypatch.setattr("eli.core.paths.agent_db_path", lambda: db)
    lessons._CACHE["at"] = 0.0
    lid = lessons.propose("SCREENSHOT", "t", ["e"], "change")
    lessons.observe_action("screenshot", True)
    lessons.observe_action("OPEN_APP", False)
    row = sqlite3.connect(db).execute("select checks, helped from lessons where id = ?", (lid,)).fetchone()
    assert row == (1, 1)
