"""Two memory faults found by measuring a live 2.3.10 database.

**The indexes never existed.** `_ensure_memory_schema` carried four CREATE INDEX
statements, but they sat in the middle of schema creation with
`CREATE INDEX ... ON conversation_turns(...)` running ~20 lines BEFORE
`CREATE TABLE ... conversation_turns`. All four shared one `try` ending in
`except Exception: pass`, so the "no such table" abandoned the rest and reported
nothing. Verified on the operator's live DB: `memories` (441 rows),
`conversation_turns` (617) and `observations` (114) had NO indexes, while
kg_entities/runtime_events/emotion_events — indexed elsewhere — had theirs. Every
recall was `SCAN` + `USE TEMP B-TREE FOR ORDER BY`.

**SELF_ANALYZE hid its own window.** It looks back 7 days and said "No recent
failures found" — while SELF_IMPROVE, using a different lookback, reported
"failures_inspected: 3" seconds later. Both were correct; the seven stored failures
were 9.8-15.1 days old. Two self-reports contradicting each other because neither
said what it had looked at.
"""
import sqlite3
import time

import pytest


# ── indexes ───────────────────────────────────────────────────────────────────

@pytest.fixture()
def db(tmp_path):
    path = tmp_path / "user.sqlite3"
    conn = sqlite3.connect(str(path))
    from eli.memory.memory import _ensure_memory_schema
    _ensure_memory_schema(conn)
    conn.commit()
    yield conn
    conn.close()


def _indexes(conn):
    return {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'")}


@pytest.mark.parametrize("name", [
    "idx_memories_ts",
    "idx_memories_timestamp",
    "idx_memories_importance",
    "idx_conversations_user_session",
    "idx_conversation_turns_session",
    "idx_conversation_turns_ts",
    "idx_observations_timestamp",
])
def test_every_recall_index_exists_on_a_fresh_database(db, name):
    assert name in _indexes(db)


@pytest.mark.parametrize("query", [
    "SELECT * FROM memories ORDER BY ts DESC LIMIT 10",
    "SELECT * FROM conversation_turns ORDER BY timestamp DESC LIMIT 20",
    "SELECT * FROM observations ORDER BY timestamp DESC LIMIT 8",
])
def test_recall_queries_no_longer_sort_in_a_temp_btree(db, query):
    """The temp B-tree WAS the cost — an unindexed ORDER BY sorts the whole table
    in memory on every recall, several times per turn."""
    plan = " ".join(r[3] for r in db.execute("EXPLAIN QUERY PLAN " + query))
    assert "USE TEMP B-TREE" not in plan, f"still sorting in memory: {plan}"
    assert "USING INDEX" in plan, f"not using an index: {plan}"


def test_index_creation_runs_after_every_table_exists(db):
    """The original ordering bug: an index created before its table.

    A fresh database is the exact case that failed — if ordering regresses, the
    conversation_turns indexes are the ones that vanish."""
    assert "idx_conversation_turns_session" in _indexes(db)
    assert "idx_conversation_turns_ts" in _indexes(db)


def test_one_failing_index_cannot_prevent_the_others(tmp_path, caplog):
    """Four statements shared one try, so the first failure took the rest with it."""
    from eli.memory.memory import _ensure_memory_indexes
    conn = sqlite3.connect(str(tmp_path / "partial.sqlite3"))
    # Only ONE of the indexed tables exists; the rest must still be attempted.
    conn.execute("CREATE TABLE observations (id INTEGER PRIMARY KEY, timestamp REAL)")
    _ensure_memory_indexes(conn)
    assert "idx_observations_timestamp" in _indexes(conn)
    conn.close()


def test_index_failures_are_logged_not_swallowed(tmp_path, caplog):
    from eli.memory.memory import _ensure_memory_indexes
    conn = sqlite3.connect(str(tmp_path / "empty.sqlite3"))
    with caplog.at_level("DEBUG"):
        _ensure_memory_indexes(conn)   # no tables at all — every statement fails
    conn.close()
    assert any("index" in r.message.lower() for r in caplog.records), \
        "a database where every index failed produced no log line"


# ── the analysis window ───────────────────────────────────────────────────────

@pytest.fixture()
def engine_with_old_failures(tmp_path, monkeypatch):
    """Seven open failures, all older than the 7-day window — the live shape."""
    monkeypatch.setenv("ELI_DATA_DIR", str(tmp_path))
    from eli.core import paths
    for fn in ("data_dir", "config_dir", "cache_dir"):
        f = getattr(paths, fn, None)
        if hasattr(f, "cache_clear"):
            f.cache_clear()

    # The engine is a module singleton, and by this point in a suite run it is
    # already bound to whatever database imported first. Reset it, or the fixture
    # silently tests the dev tree's real failures instead of the ones seeded here.
    import eli.runtime.self_improvement as si
    monkeypatch.setattr(si, "_self_engine", None, raising=False)

    from eli.memory.memory import get_agent_memory
    engine = si.SelfImprovementEngine(memory=get_agent_memory(db_path=str(tmp_path / "agent.sqlite3")))
    monkeypatch.setattr(si, "_self_engine", engine, raising=False)

    # Setting ELI_DATA_DIR fires vector_store's legacy-index migration, which copies
    # the dev tree's index into the tmp dir AND leaves the module singleton bound to
    # it — poisoning every later test that touches the vector store. Reset it on the
    # way in and the way out.
    try:
        from eli.memory.vector_store import reset_vector_store
        reset_vector_store()
    except Exception:
        pass

    conn = engine.memory._get_connection()
    conn.execute("DELETE FROM failures")
    old = time.time() - (12 * 86400)
    for i in range(7):
        conn.execute(
            "INSERT INTO failures (timestamp, user_input, command, error, status, occurrence_count) "
            "VALUES (?,?,?,?,?,?)",
            (old, f"input {i}", f"CMD_{i}", f"error {i}", "open", 1))
    conn.commit()
    conn.close()
    yield engine

    # Teardown matters as much as setup here. paths.data_dir() is lru_cached, so
    # clearing it only on the way IN leaves it pinned to this tmp_path for every
    # later test — artifacts_dir() is an alias of it, and the vector store resolves
    # through that. Live symptom: test_vector_store_isolation and
    # test_recent_memory_processing_no_gguf failed only when run after this file.
    try:
        from eli.memory.vector_store import reset_vector_store
        reset_vector_store()
    except Exception:
        pass
    for fn in ("data_dir", "config_dir", "cache_dir"):
        f = getattr(paths, fn, None)
        if hasattr(f, "cache_clear"):
            f.cache_clear()


def test_older_open_failures_are_counted(engine_with_old_failures):
    older = engine_with_old_failures.failures_outside_window(days=7)
    assert older["count"] == 7
    assert older["oldest_days"] >= 11


def test_the_seven_day_window_genuinely_finds_none(engine_with_old_failures):
    """The report was not lying — it just was not saying what it had looked at."""
    assert engine_with_old_failures.analyze_failures(days=7, min_cluster_size=1) == []


def test_a_wider_window_finds_them(engine_with_old_failures):
    found = engine_with_old_failures.analyze_failures(days=30, min_cluster_size=1)
    assert len(found) == 7


def test_the_report_states_its_window_and_the_backlog(engine_with_old_failures):
    from eli.execution.executor_enhanced import execute
    text = execute("SELF_ANALYZE", {}).get("response") or ""
    assert "last 7 day" in text, "the window is still unstated"
    assert "7 open failure" in text, "the older backlog is still hidden"
    assert "No recent failures found." not in text, "the misleading phrasing survives"
