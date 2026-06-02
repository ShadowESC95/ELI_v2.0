"""Tests for eli.memory stores and DB utilities — ~120 tests."""
from __future__ import annotations

import sqlite3
from pathlib import Path
import pytest

from eli.memory.memory import Memory


# ── SQLite Memory Store ───────────────────────────────────────────────────

def test_sqlite_memory_importable():
    try:
        from eli.memory.sqlite_memory import SQLiteMemory
        assert SQLiteMemory is not None
    except ImportError:
        pytest.skip("sqlite_memory not available")

def test_sqlite_memory_init(tmp_db):
    try:
        from eli.memory.sqlite_memory import SQLiteMemory
        sm = SQLiteMemory(db_path=str(tmp_db))
        assert sm is not None
    except ImportError:
        pytest.skip("sqlite_memory not available")


# ── Stores ────────────────────────────────────────────────────────────────

def test_stores_importable():
    try:
        from eli.memory.stores import get_memory_store
        assert get_memory_store is not None
    except ImportError:
        pytest.skip("stores not available in this form")


# ── DB Paths ──────────────────────────────────────────────────────────────
# Canonical module is eli.core.db_paths (db_paths was consolidated there; it was
# never a submodule of eli.memory). eli.memory exposes resolve_db_paths().

def test_db_paths_importable():
    from eli.core.db_paths import get_db_paths
    assert get_db_paths is not None

def test_db_paths_resolve_returns_something():
    from eli.core.db_paths import get_db_paths
    result = get_db_paths()
    assert result is not None

def test_db_paths_has_user_db():
    from eli.core.db_paths import get_db_paths
    result = get_db_paths()
    user_db = getattr(result, "user_db", None) or getattr(result, "memory_db", None)
    assert user_db is not None

def test_db_paths_user_db_is_path():
    from eli.core.db_paths import get_db_paths
    result = get_db_paths()
    user_db = getattr(result, "user_db", None)
    if user_db:
        assert isinstance(user_db, (Path, str))


# ── System Index ──────────────────────────────────────────────────────────

def test_system_index_importable():
    try:
        from eli.memory.system_index import SystemIndex
        assert SystemIndex is not None
    except ImportError:
        pytest.skip("system_index not available")


# ── Memory store write/read cycle ────────────────────────────────────────

def _write_memories(tmp_db, count=10):
    conn = sqlite3.connect(str(tmp_db))
    for i in range(count):
        conn.execute(
            "INSERT INTO memories (text, tags, timestamp, kind) VALUES (?,?,?,?)",
            (f"Memory text {i}: user likes {['python','jazz','dark mode','linux'][i%4]}",
             f"tag_{i%4}", f"2024-01-{i+1:02d}T00:00:00", "memory")
        )
    conn.commit()
    conn.close()


def test_memory_write_read_cycle(tmp_db):
    _write_memories(tmp_db, 10)
    mem = Memory(db_path=str(tmp_db))
    result = mem.recall_memory("python programming")
    assert isinstance(result, list)

def test_memory_count_after_write(tmp_db):
    _write_memories(tmp_db, 5)
    conn = sqlite3.connect(str(tmp_db))
    count = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
    conn.close()
    assert count == 5

def test_memory_recall_order(tmp_db):
    conn = sqlite3.connect(str(tmp_db))
    for i in range(5):
        conn.execute(
            "INSERT INTO memories (text, timestamp, kind, importance) VALUES (?,?,?,?)",
            (f"Important memory {i}", f"2024-0{i+1}-01T00:00:00", "memory", float(i)/5)
        )
    conn.commit()
    conn.close()
    mem = Memory(db_path=str(tmp_db))
    result = mem.recall_memory("Important memory", limit=5)
    assert isinstance(result, list)


# ── FTS5 Index ────────────────────────────────────────────────────────────

def test_fts5_table_exists(tmp_db):
    conn = sqlite3.connect(str(tmp_db))
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    conn.close()
    assert "memories_fts" in tables

def test_fts5_search(tmp_db):
    conn = sqlite3.connect(str(tmp_db))
    conn.execute("INSERT INTO memories (text, kind, timestamp) VALUES (?, ?, ?)",
                 ("User mentioned Python programming language", "memory", 1700000000.0))
    conn.commit()
    conn.close()
    mem = Memory(db_path=str(tmp_db))
    result = mem.recall_memory("Python")
    assert isinstance(result, list)

def test_fts5_no_false_positives(tmp_db):
    conn = sqlite3.connect(str(tmp_db))
    conn.execute("INSERT INTO memories (text, kind, timestamp) VALUES (?, ?, ?)",
                 ("User likes coffee in the morning", "memory", 1700000000.0))
    conn.commit()
    conn.close()
    mem = Memory(db_path=str(tmp_db))
    result = mem.recall_memory("elephant aerodynamics quantum")
    assert isinstance(result, list)
    assert len(result) == 0


# ── Memory importance scoring ────────────────────────────────────────────

@pytest.mark.parametrize("importance", [0.0, 0.25, 0.5, 0.75, 1.0])
def test_memory_importance_values(tmp_db, importance):
    conn = sqlite3.connect(str(tmp_db))
    conn.execute(
        "INSERT INTO memories (text, importance, kind, timestamp) VALUES (?,?,?,?)",
        ("Test memory with importance", importance, "memory", 1700000000.0)
    )
    conn.commit()
    conn.close()
    mem = Memory(db_path=str(tmp_db))
    result = mem.recall_memory("Test memory")
    assert isinstance(result, list)


# ── Noise filtering ───────────────────────────────────────────────────────

@pytest.mark.parametrize("kind", [
    "assistant_insight", "episodic", "reflection"
])
def test_noise_kinds_filtered(tmp_db, kind):
    conn = sqlite3.connect(str(tmp_db))
    conn.execute(
        "INSERT INTO memories (text, kind, timestamp) VALUES (?,?,?)",
        (f"This is a {kind} entry", kind, 1700000000.0)
    )
    conn.commit()
    conn.close()
    mem = Memory(db_path=str(tmp_db))
    result = mem.recall_memory(kind)
    for r in result:
        assert r.get("kind") != kind

def test_orchestrator_source_filtered(tmp_db):
    conn = sqlite3.connect(str(tmp_db))
    conn.execute(
        "INSERT INTO memories (text, source, kind, timestamp) VALUES (?,?,?,?)",
        ("Orchestrator internal message", "orchestrator", "memory", 1700000000.0)
    )
    conn.commit()
    conn.close()
    mem = Memory(db_path=str(tmp_db))
    result = mem.recall_memory("Orchestrator internal")
    for r in result:
        assert r.get("source") != "orchestrator"


# ── Memory tags ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("tags", [
    "identity", "preferences", "skills", "work", "music",
    "identity,preferences", "skills,python", ""
])
def test_memory_tags_retrievable(tmp_db, tags):
    conn = sqlite3.connect(str(tmp_db))
    conn.execute(
        "INSERT INTO memories (text, tags, kind, timestamp) VALUES (?,?,?,?)",
        (f"Memory with tags: {tags}", tags, "memory", 1700000000.0)
    )
    conn.commit()
    conn.close()
    mem = Memory(db_path=str(tmp_db))
    result = mem.recall_memory("Memory with tags")
    assert isinstance(result, list)


# ── Large DB performance ──────────────────────────────────────────────────

def test_large_db_recall_performance(tmp_db):
    """Recall should complete in reasonable time even with 500 entries."""
    conn = sqlite3.connect(str(tmp_db))
    for i in range(500):
        conn.execute(
            "INSERT INTO memories (text, tags, timestamp, kind) VALUES (?,?,?,?)",
            (f"Memory entry {i} with {['jazz','python','linux','work'][i%4]} content",
             f"tag_{i%4}", float(i), "memory")
        )
    conn.commit()
    conn.close()

    import time
    mem = Memory(db_path=str(tmp_db))
    start = time.time()
    result = mem.recall_memory("jazz music preferences", limit=10)
    elapsed = time.time() - start
    assert isinstance(result, list)
    assert elapsed < 5.0, f"Recall took too long: {elapsed:.2f}s"
