"""recall_memory(tags=...) must filter without TypeError."""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path


def test_recall_memory_accepts_tags_filter():
    from eli.memory.memory import Memory

    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test.sqlite3"
        mem = Memory(db_path=str(db))
        mem.store_memory(
            "Morning briefing: systems nominal.",
            tags=["morning_report", "briefing"],
            source="test",
        )
        mem.store_memory(
            "Unrelated lunch note.",
            tags=["personal"],
            source="test",
        )

        rows = mem.recall_memory(
            "briefing",
            limit=5,
            tags=["morning_report"],
        )
        assert rows, "expected at least one tagged hit"
        assert all(
            "morning_report" in str(r.get("tags", "")).lower()
            for r in rows
        ), rows
        assert not any("lunch" in str(r.get("text", "")).lower() for r in rows)
