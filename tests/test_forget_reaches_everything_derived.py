"""Forgetting a memory removes it and what was made from it: index entries, claims, summaries, profile items, stances, graph, turns."""
import json
import sqlite3
import time

import pytest

from eli.memory.memory import Memory


@pytest.fixture()
def mem(tmp_path, monkeypatch):
    monkeypatch.setenv("ELI_TEST_MODE", "1")
    monkeypatch.setattr("eli.memory.vector_store.get_vector_store", lambda: None)
    return Memory(db_path=tmp_path / "user.sqlite3")


def _q(mem, sql, *a):
    c = sqlite3.connect(mem.db_path)
    try:
        return c.execute(sql, a).fetchall()
    finally:
        c.close()


def _seed(mem):
    text = "I live in Lisbon and the spare key code is ORCHID-7319 for my sister Priya"
    rid = mem.store_memory(text, source="user")["id"]
    other = mem.store_memory("I prefer green tea with a slice of ginger every afternoon", source="user")["id"]
    child = mem.store_memory("Summary: the user has a spare key code ORCHID-7319", source="assistant", kind="summary")["id"]
    mem.link_derivation(child, [rid], "summary")
    from eli.cognition.stance_store import ensure_tables
    from eli.runtime.profile_extractor import ensure_profile_tables
    from eli.runtime.user_model import ensure_user_model_row
    ensure_profile_tables(mem.db_path)
    ensure_user_model_row("u", mem.db_path)
    mem.save_session_summary("s", "u", summary="They shared the key code ORCHID-7319 and Priya", turns_count=2)
    mem.save_session_summary("s2", "u", summary="They talked about tea and gardening", turns_count=2)
    c = sqlite3.connect(mem.db_path)
    ensure_tables(c.cursor())
    now = time.time()
    c.execute("insert into semantic (user_id, fact, evidence, evidence_count, created_at) values ('u', 'Has a spare key', ?, 1, ?)",
              (json.dumps([text]), now))
    c.execute("insert into semantic (user_id, fact, evidence, evidence_count, created_at) values ('u', 'Likes green tea', ?, 1, ?)",
              (json.dumps(["I prefer green tea with a slice of ginger every afternoon"]), now))
    c.execute("update user_model set brief = 'Key code ORCHID-7319 kept for Priya', dossier = 'Likes tea' where user_id = 'u'")
    c.execute("insert into eli_stances (topic, position) values ('key code', 'ORCHID-7319 is not to be shared')")
    c.execute("insert into conversation_turns (session_id, user_id, role, content, ts, timestamp) values ('s','u','user',?,?,?)", (text, now, now))
    c.commit()
    c.close()
    return rid, other, child, text


def test_forget_removes_the_memory_and_everything_made_from_it(mem):
    rid, other, child, text = _seed(mem)
    report = mem.forget([rid])
    assert report["memories"] == 2 and report["derived"] == 1
    assert report["claims"] >= 1 and report["semantic"] == 1 and report["summaries"] == 1
    assert report["profile"] == 1 and report["stances"] == 1 and report["turns"] == 1
    assert not _q(mem, "select id from memories where id in (?, ?)", rid, child)
    assert not _q(mem, "select child_id from memory_lineage")
    assert [r[0] for r in _q(mem, "select fact from semantic")] == ["Likes green tea"]
    assert [r[0] for r in _q(mem, "select summary from session_summaries")] == ["They talked about tea and gardening"]
    brief, dossier = _q(mem, "select brief, dossier from user_model")[0]
    assert not brief and dossier == "Likes tea"
    assert mem.claims_current() == []
    assert _q(mem, "select id from memories where id = ?", other)


def test_forget_leaves_unrelated_memories_and_can_be_repeated(mem):
    rid, other, _child, _text = _seed(mem)
    mem.forget([rid])
    again = mem.forget([rid])
    assert again["memories"] == 0
    assert mem.recall_memory("green tea ginger", limit=3)


def test_a_summary_of_a_fact_is_not_independent_evidence(mem):
    a = mem.store_memory("The lease starts in March according to the landlord letter", source="user")["id"]
    b = mem.store_memory("Summary of the letter: the lease starts in March", source="assistant", kind="summary")["id"]
    c = mem.store_memory("A second separate note says the lease starts in March", source="user")["id"]
    mem.link_derivation(b, [a], "summary")
    assert mem.lineage_root(b) == a
    assert mem.independent_sources([a, b]) == 1
    assert mem.independent_sources([a, b, c]) == 2


def test_forget_candidates_lists_what_would_go(mem):
    rid, *_ = _seed(mem)
    assert rid in [c["id"] for c in mem.forget_candidates("spare key code ORCHID-7319")]
