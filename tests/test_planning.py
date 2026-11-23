"""Tests for eli.planning modules — ~60 tests."""
from __future__ import annotations

import pytest
import sqlite3
import time
from unittest.mock import MagicMock, patch


# ── Proactive Daemon ──────────────────────────────────────────────────────

def test_proactive_daemon_importable():
    from eli.planning.proactive_daemon import ProactiveDaemon
    assert ProactiveDaemon is not None

def test_proactive_daemon_pauses_resumes_and_stops():
    """Each of these used to sit in a try/except Exception: pass, so none of them could fail."""
    from eli.planning.proactive_daemon import ProactiveDaemon
    d = ProactiveDaemon()
    assert d.paused is False
    d.pause()
    assert d.paused is True
    d.resume()
    assert d.paused is False
    d.stop()
    assert d.running is False and d._stop_event.is_set()


# ── Plugin system ─────────────────────────────────────────────────────────

def test_plugins_dir_exists():
    from eli.core.paths import plugins_dir
    # Directory may not exist in dev, but function should work
    p = plugins_dir()
    assert p is not None


# ── Knowledge Graph ───────────────────────────────────────────────────────

def test_knowledge_graph_importable():
    from eli.memory.knowledge_graph import KnowledgeGraph
    assert KnowledgeGraph is not None

def test_knowledge_graph_instantiation(tmp_db):
    from eli.memory.knowledge_graph import KnowledgeGraph
    kg = KnowledgeGraph(db_path=str(tmp_db))
    assert str(kg.db_path) == str(tmp_db)
    assert str(kg.path) == str(tmp_db)

def test_knowledge_graph_schema_has_core_tables(tmp_db):
    from eli.memory.knowledge_graph import KnowledgeGraph
    kg = KnowledgeGraph(db_path=str(tmp_db))
    assert kg.stats() == {"entities": 0, "relations": 0}
    conn = sqlite3.connect(str(tmp_db))
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    finally:
        conn.close()
    assert {"kg_entities", "kg_relations", "kg_entities_fts"} <= tables

# ── Memory Adapter ────────────────────────────────────────────────────────

def test_memory_adapter_importable():
    from eli.memory.memory_adapter import MemoryAdapter
    assert MemoryAdapter is not None

def test_memory_adapter_recalls_what_the_store_holds_as_dicts(tmp_path):
    """It was built with a db_path the adapter has never taken, inside try/except Exception: pass."""
    from eli.memory import Memory
    from eli.memory.memory_adapter import MemoryAdapter
    mem = Memory(db_path=str(tmp_path / "adapter.sqlite3"))
    mem.init_db()
    mem.store_memory("The adapter recall check row", tags=["adapter"], source="test")
    rows = MemoryAdapter(mem).recall_memory("adapter recall", limit=5)
    assert rows and all(isinstance(r, dict) for r in rows)
    assert any("adapter recall check" in str(r.get("text", "")) for r in rows)


# ── Memory Service ────────────────────────────────────────────────────────

