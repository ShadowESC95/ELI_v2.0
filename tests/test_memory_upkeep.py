"""Daily upkeep: label, merge, decay, archive. Runs on a real database, never a mock."""
import sqlite3
import time

import pytest

from eli.memory.memory import Memory, flush_recall_writes

DAY = 86400.0


@pytest.fixture()
def mem(tmp_path, monkeypatch):
    monkeypatch.delenv("ELI_TEST_MODE", raising=False)
    monkeypatch.setenv("ELI_TEST_MODE", "1")
    return Memory(db_path=tmp_path / "user.sqlite3")


def _rows(mem, sql, *a):
    c = sqlite3.connect(mem.db_path)
    try:
        return c.execute(sql, a).fetchall()
    finally:
        c.close()


def _age(mem, mid, days):
    c = sqlite3.connect(mem.db_path)
    ts = time.time() - days * DAY
    c.execute("UPDATE memories SET ts=?, timestamp=?, event_ts=?, last_seen=?, weight=1.0 WHERE id=?", (ts, ts, ts, ts, mid))
    c.commit()
    c.close()


def test_a_repeated_statement_is_one_row_that_counts_sightings(mem):
    a = mem.store_memory("I am watching Severance")
    b = mem.store_memory("i am watching severance!")
    assert b["deduplicated"] and b["id"] == a["id"]
    assert _rows(mem, "select count(*), max(seen_count) from memories") == [(1, 2)]


def test_what_a_source_is_decides_its_origin_and_provenance(mem):
    mem.store_memory("Reflection (24h): Top topics: a, b", tags=["reflection", "auto"])
    mem.store_memory("my cat is called Biscuit")
    rows = dict(_rows(mem, "select origin, provenance_kind from memories"))
    assert rows == {"telemetry": "system_generated", "user_said": "user_verbatim"}


def test_telemetry_is_not_embedded(mem, monkeypatch):
    added = []

    class VS:
        def add(self, text, metadata=None):
            added.append(text)
            return True

        def flush(self):
            pass

    monkeypatch.setattr("eli.memory.vector_store.get_vector_store", lambda: VS())
    mem.store_memory("Top topics: a, b", source="eli_reflection", kind="insight")
    mem.store_memory("I drive to Cork on Saturdays")
    assert added == ["I drive to Cork on Saturdays"]


def test_decay_weakens_derived_rows_but_not_important_user_facts(mem):
    tel = mem.store_memory("Top topics: a, b", source="eli_reflection", kind="insight", importance=0.65)["id"]
    fact = mem.store_memory("my wife is called Jane", importance=0.95)["id"]
    meh = mem.store_memory("i had toast", importance=0.4)["id"]
    for i in (tel, fact, meh):
        _age(mem, i, 120)
    mem.apply_weight_decay()
    w = dict(_rows(mem, "select id, weight from memories"))
    assert w[fact] == 1.0
    assert w[tel] < w[meh] < 1.0


def test_recall_resets_the_curve_and_counts_the_use(mem):
    mid = mem.store_memory("i love the dune films")["id"]
    _age(mem, mid, 90)
    mem.apply_weight_decay()
    before = _rows(mem, "select weight from memories where id=?", mid)[0][0]
    assert before < 1.0
    mem.recall_memory("dune films", limit=3)
    flush_recall_writes()
    w, n = _rows(mem, "select weight, recall_count from memories where id=?", mid)[0]
    assert w == 1.0 and n == 1
    assert _rows(mem, "select count(*) from recall_log where memory_id=?", mid)[0][0] >= 1


def test_faded_unused_derived_rows_are_archived_and_restorable(mem):
    tel = mem.store_memory("Top topics: a, b", source="eli_reflection", kind="insight", importance=0.5)["id"]
    fact = mem.store_memory("i had toast", importance=0.3)["id"]
    for i in (tel, fact):
        _age(mem, i, 4000)
    mem.apply_weight_decay()
    out = mem.archive_faded()
    assert out["archived"] == 1
    assert [r[0] for r in _rows(mem, "select id from memories")] == [fact]
    assert mem.search_archive("topics")[0]["id"] == tel
    assert mem.restore_from_archive([tel]) == 1
    assert {r[0] for r in _rows(mem, "select id from memories")} == {tel, fact}


def test_upkeep_runs_once_a_day_and_is_idempotent(mem):
    mem.store_memory("Reflection (24h): a", tags=["reflection", "auto"])
    assert mem.upkeep_due()
    assert mem.run_upkeep()["ran"] is True
    assert not mem.upkeep_due()
    assert mem.run_upkeep()["ran"] is False
    before = _rows(mem, "select id, weight from memories")
    mem.run_upkeep(force=True)
    assert _rows(mem, "select id, weight from memories") == before


def test_legacy_rows_get_labelled_and_their_true_date_recovered(mem):
    old = time.time() - 40 * DAY
    c = sqlite3.connect(mem.db_path)
    c.execute("insert into conversation_turns (session_id, user_id, role, content, ts, timestamp) values ('s','u','user',?,?,?)",
              ("i am watching severance", old, old))
    c.execute("insert into memories (text, tags, kind, source, ts, timestamp, importance, provenance_kind, verification_status) "
              "values (?,?,?,?,?,?,?,?,?)",
              ("i am watching severance", "working_memory,memory_recall,session_pin", "fact", "working_memory",
               time.time(), time.time(), 0.9, "user_verbatim", "verified"))
    c.execute("insert into memories (text, tags, kind, source, ts, timestamp, provenance_kind, verification_status) values (?,?,?,?,?,?,?,?)",
              ("Top topics: a", "eli_insight,auto", "insight", "eli_reflection", time.time(), time.time(), "user_verbatim", "verified"))
    c.commit()
    c.close()
    out = mem.backfill_policy_fields()
    assert out["filled"] == 2 and out["redated"] == 1 and out["relabelled"] == 1
    ev = _rows(mem, "select event_ts from memories where source='working_memory'")[0][0]
    assert abs(ev - old) < 1
    assert _rows(mem, "select provenance_kind from memories where source='eli_reflection'") == [("system_generated",)]


def test_repeated_revisions_and_inflated_corroboration_are_tidied(mem):
    from eli.cognition.stance_store import ensure_tables, record_revision

    c = sqlite3.connect(mem.db_path)
    cur = c.cursor()
    ensure_tables(cur)
    for _ in range(50):   # the flip-flop: same pair logged on every pass
        cur.execute("INSERT INTO belief_revisions (kind, topic, old_value, new_value, reason, ts) "
                    "VALUES ('user_pattern','preference.style','A','B','r',1.0)")
    record_revision(cur, "user_pattern", "preference.style", "A", "B")   # already on record: not repeated
    cur.execute("INSERT INTO user_patterns (pattern_type, pattern_data, timestamp, ts, corroboration) "
                "VALUES ('research.science','x',1,1,19219)")
    ts = time.time() - 3 * DAY
    for d in range(3):
        cur.execute("INSERT INTO conversation_turns (session_id, user_id, role, content, ts, timestamp) "
                    "VALUES ('s','u','user','hi',?,?)", (ts + d * DAY, ts + d * DAY))
    c.commit()
    c.close()
    out = mem.tidy_learning_tables()
    assert out["revisions_removed"] == 49 and out["corroboration_capped"] == 1
    assert _rows(mem, "select count(*) from belief_revisions")[0][0] == 1
    assert _rows(mem, "select corroboration from user_patterns")[0][0] == 3


def test_a_fact_is_corroborated_once_per_day_not_once_per_pass(mem):
    from eli.cognition.stance_store import ensure_tables
    from eli.runtime.profile_extractor import _insert_user_pattern

    c = sqlite3.connect(mem.db_path)
    cur = c.cursor()
    ensure_tables(cur)
    _insert_user_pattern(cur, "research.science", "User works on science.")
    for _ in range(20):
        _insert_user_pattern(cur, "research.science", "User works on science.")
    assert cur.execute("select corroboration from user_patterns").fetchone()[0] == 1
    yesterday = time.time() - DAY
    cur.execute("update user_patterns set ts = ?", (yesterday,))
    _insert_user_pattern(cur, "research.science", "User works on science.")
    assert cur.execute("select corroboration from user_patterns").fetchone()[0] == 2
    c.close()


def test_earlier_generated_user_ids_fold_into_the_owner_and_named_users_stay(mem):
    import json

    owner, u1, u2 = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222", "33333333-3333-4333-8333-333333333333"
    from eli.runtime.profile_extractor import ensure_profile_tables

    ensure_profile_tables(mem.db_path)
    assert mem.owner_id(owner) == owner
    assert mem.owner_id("a-later-random-uuid") == owner          # a reinstall can't change it
    c = sqlite3.connect(mem.db_path)
    for uid in (owner, u1, u2, "alice"):
        c.execute("insert into conversation_turns (session_id, user_id, role, content, ts, timestamp) values ('s',?,'user','hi',1,1)", (uid,))
    cols = "user_id, identity, interests, confidence, updated_at, ts, dossier, brief"
    c.execute(f"insert into user_model ({cols}) values (?,?,?,?,?,?,?,?)",
              (owner, json.dumps(["Software"]), json.dumps([]), 0.7, 300.0, 300.0, "new", "b-new"))
    c.execute(f"insert into user_model ({cols}) values (?,?,?,?,?,?,?,?)",
              (u1, json.dumps(["Software", "Physics"]), json.dumps(["chemistry"]), 0.9, 100.0, 100.0, "old", "b-old"))
    c.commit()
    c.close()
    out = mem.merge_user_ids()
    assert out["merged_ids"] == 2 and out["rows"] == 2
    assert sorted(r[0] for r in _rows(mem, "select distinct user_id from conversation_turns")) == sorted([owner, "alice"])
    (row,) = _rows(mem, "select user_id, identity, interests, confidence, dossier from user_model")
    assert row[0] == owner and json.loads(row[1]) == ["Software", "Physics"] and json.loads(row[2]) == ["chemistry"]
    assert row[3] == 0.9 and row[4] == "new"
    assert mem.merge_user_ids()["merged_ids"] == 0                 # idempotent


def test_the_integrity_report_measures_agreement(mem, monkeypatch):
    monkeypatch.setattr("eli.memory.vector_store.get_vector_store", lambda: None)
    mem.store_memory("my cat is called Biscuit")
    mem.store_memory("Top topics: a", source="eli_reflection", kind="insight")
    rep = mem.integrity_report()
    assert rep["memories"] == 2 and rep["fts_missing"] == 0 and rep["fts_orphans"] == 0
    assert rep["duplicate_groups"] == 0 and rep["unlabelled"] == 0 and rep["ok"] is True
    c = sqlite3.connect(mem.db_path)
    c.execute("insert into memories (text, source, kind, ts, timestamp) values ('legacy','user','memory',1,1)")
    c.commit()
    c.close()
    rep = mem.integrity_report()
    assert rep["unlabelled"] == 1 and rep["fts_missing"] == 1 and rep["ok"] is False
    mem.run_upkeep(force=True)
    assert mem.integrity_report()["unlabelled"] == 0


def test_repeated_evidence_folds_into_one_dated_fact(mem):
    from eli.runtime.profile_extractor import _promote_to_semantic, ensure_profile_tables

    ensure_profile_tables(mem.db_path)
    c = sqlite3.connect(mem.db_path)
    cur = c.cursor()
    base = "User prefers in-depth, meticulous, thorough responses."
    for i, q in enumerate(["be more in depth", "do better, much more in depth", "be more in depth"]):
        _promote_to_semantic(cur, "preference.detail", f'{base} Said: "{q}"', 1000.0 + i)
    rows = cur.execute("select fact, evidence_count, last_seen, evidence from semantic").fetchall()
    assert len(rows) == 1 and rows[0][0] == base and rows[0][1] == 3 and rows[0][2] == 1002.0
    assert rows[0][3] == '["do better, much more in depth", "be more in depth"]'
    # legacy rows written one per quote are folded by upkeep
    for i in range(3):
        cur.execute("insert into semantic (user_id, fact, tags, confidence, created_at) values ('default', ?, 't', 0.8, ?)",
                    (f'User is a tester. Said: "q{i}"', 10.0 + i))
    c.commit()
    c.close()
    out = mem.consolidate_semantic()
    assert out["facts_before"] == 4 and out["facts_after"] == 2
    assert _rows(mem, "select fact, evidence_count from semantic where fact like 'User is%'") == [("User is a tester.", 3)]
