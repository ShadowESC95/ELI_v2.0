"""Different facts must not share a dedupe key, and upkeep must report what really happened."""
import sqlite3
import time

import pytest

from eli.memory import policy
from eli.memory.memory import Memory


@pytest.fixture()
def mem(tmp_path, monkeypatch):
    monkeypatch.setenv("ELI_TEST_MODE", "1")
    monkeypatch.setattr("eli.memory.vector_store.get_vector_store", lambda: None)
    return Memory(db_path=tmp_path / "user.sqlite3")


@pytest.mark.parametrize("a,b", [
    ("I love C++", "I love C"), ("I love C#", "I love C"), ("balance is -5", "balance is 5"),
    ("it costs 3.5", "it costs 35"), ("version 2.0 works", "version 20 works"),
])
def test_meaningful_marks_keep_keys_apart(a, b):
    assert policy.text_key(a) != policy.text_key(b)


@pytest.mark.parametrize("a,b", [("Hello, world.", "hello world"), ("Not fine!", "not fine"), ("  Extra   spaces ", "extra spaces")])
def test_sentence_punctuation_and_case_do_not_matter(a, b):
    assert policy.text_key(a) == policy.text_key(b)


def test_upkeep_dry_run_writes_nothing(mem):
    c = sqlite3.connect(mem.db_path)
    c.execute("insert into memories (text, tags, source, kind, ts, timestamp) values "
              "('legacy row with no policy fields', '', 'user', 'memory', ?, ?)", (time.time(), time.time()))
    c.commit()
    before = c.execute("select count(*) from memories where origin is null or origin = ''").fetchone()[0]
    c.close()
    report = mem.run_upkeep(dry_run=True)
    c = sqlite3.connect(mem.db_path)
    after = c.execute("select count(*) from memories where origin is null or origin = ''").fetchone()[0]
    c.close()
    assert before == after and before >= 1
    assert report["backfill"].get("would_fill", 0) >= 1


def test_a_failed_step_leaves_the_day_undone(mem, monkeypatch):
    monkeypatch.setattr(Memory, "archive_faded", lambda self, dry_run=False: (_ for _ in ()).throw(RuntimeError("disk full")))
    report = mem.run_upkeep(force=True)
    assert report["status"] == "partial" and "archive" in report["failed_steps"]
    c = mem._get_connection()
    try:
        assert mem._meta_get(c, "last_upkeep_day") != time.strftime("%Y-%m-%d")
    finally:
        c.close()


def test_a_clean_run_marks_the_day_done(mem):
    report = mem.run_upkeep(force=True)
    assert report["status"] == "complete"
    assert mem.upkeep_due() is False


def test_old_keys_are_recomputed_once(mem):
    mem.store_memory("I have been using the C++ compiler for my projects lately")
    c = sqlite3.connect(mem.db_path)
    c.execute("update memories set text_key = 'stale'")
    c.execute("delete from memory_meta where key = 'text_key_version'")
    c.commit()
    c.close()
    first = mem.rekey_text_keys()
    assert first["rekeyed"] >= 1
    assert mem.rekey_text_keys().get("skipped") == "current"


def test_integrity_is_not_ok_when_vectors_are_missing(mem, monkeypatch):
    mem.store_memory("I have a sister called Priya who lives near the coast")

    class Store:
        ntotal = 0
        meta_count = 0
        _meta = []
        _tombstone_ids = ()

    monkeypatch.setattr("eli.memory.vector_store.get_vector_store", lambda: Store())
    rep = mem.integrity_report()
    assert rep["missing_vectors"] >= 1 and rep["ok"] is False and rep["status"] == "degraded"
