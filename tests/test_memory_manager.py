import pytest
from eli.memory import get_memory, get_agent_memory, resolve_db_paths
from eli.memory.memory import Memory
import sqlite3
import time
import os

class TestMemoryManager:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        """Create a temporary memory instance for each test."""
        db_path = tmp_path / "test_memory.sqlite3"
        self.memory = Memory(db_path=db_path)
        self.memory.init_db()
        yield
        if db_path.exists():
            db_path.unlink()

    def test_store_and_recall(self):
        mem = self.memory
        result = mem.store_memory("Test memory content", tags=["test"])
        assert result["ok"] is True
        assert result.get("id", 0) > 0

        hits = mem.recall_memory("test", limit=10)
        assert len(hits) >= 1
        assert "Test memory content" in hits[0]["text"]

    def test_recall_finds_jazz(self):
        mem = self.memory
        mem.store_memory("I love jazz music", tags=["music"])
        hits = mem.recall_memory("jazz")
        texts = [h.get("text", "") for h in hits]
        print("Hits:", hits)
        assert any("jazz" in t.lower() for t in texts)

    def test_recall_finds_name(self):
        mem = self.memory
        mem.store_memory("My name is Alice", tags=["identity"])
        hits = mem.recall_memory("Alice")
        texts = [h.get("text", "") for h in hits]
        print("Hits:", hits)
        assert any("Alice" in t for t in texts)

    def test_get_recent_memories(self):
        mem = self.memory
        mem.store_memory("First")
        mem.store_memory("Second")
        recent = mem.get_recent_memories(limit=2)
        assert len(recent) >= 2

    def test_get_stats(self):
        mem = self.memory
        mem.store_memory("Stats test")
        stats = mem.get_stats()
        assert stats["total"] >= 1

    def test_search_memory(self):
        mem = self.memory
        mem.store_memory("Python is a programming language")
        results = mem.search_memory("Python")
        assert len(results) >= 1

    def test_conversation_turns(self):
        mem = self.memory
        rid = mem.add_conversation_turn("user", "Hello", session_id="test")
        assert rid > 0
        turns = mem.get_recent_conversation(limit=10)
        assert any("Hello" in t["content"] for t in turns)

    def test_weight_decay(self):
        mem = self.memory
        conn = sqlite3.connect(str(mem.db_path))
        conn.execute("INSERT INTO memories (ts, text) VALUES (?, ?)", (time.time() - 10*86400, "Old"))
        conn.commit()
        conn.close()
        mem.apply_weight_decay(older_than_days=1)
        # No assertion, just ensure no crash

if __name__ == "__main__":
    pytest.main([__file__])
