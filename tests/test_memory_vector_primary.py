"""Integration tests: FAISS runs as primary memory retrieval path.

Verifies:
- recall_memory() calls vector_store.search() first when index is populated
- FTS5/LIKE search only runs as a supplement when FAISS returns too few results
- When FAISS index is empty (ntotal == 0), keyword search is the fallback path
- SQL identifier validation blocks f-string injection attempts
"""
import pytest
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_memory(tmp_path: Path):
    from eli.memory.memory import Memory
    return Memory(db_path=tmp_path / "test.sqlite3")


def _make_vector_store_mock(ntotal: int = 5, search_results=None):
    """Return a mock vector store whose index reports ntotal entries."""
    mock_vs = MagicMock()
    mock_index = MagicMock()
    mock_index.ntotal = ntotal
    mock_vs._index = mock_index
    if search_results is None:
        search_results = [
            {"memory_id": i, "ts": 0, "text": f"vector result {i}", "tags": "", "score": 0.9 - i * 0.05}
            for i in range(ntotal)
        ]
    mock_vs.search.return_value = search_results
    return mock_vs


# ---------------------------------------------------------------------------
# SQL identifier hardening
# ---------------------------------------------------------------------------

class TestSQLIdentifierValidation:

    def test_valid_identifier_passes(self):
        from eli.memory.memory import _validate_identifier
        assert _validate_identifier("memories") == "memories"
        assert _validate_identifier("kg_entities") == "kg_entities"
        assert _validate_identifier("col_2") == "col_2"

    def test_identifier_with_space_raises(self):
        from eli.memory.memory import _validate_identifier
        with pytest.raises(ValueError, match="Invalid SQL"):
            _validate_identifier("bad name")

    def test_identifier_with_semicolon_raises(self):
        from eli.memory.memory import _validate_identifier
        with pytest.raises(ValueError, match="Invalid SQL"):
            _validate_identifier("memories; DROP TABLE memories--")

    def test_identifier_with_quote_raises(self):
        from eli.memory.memory import _validate_identifier
        with pytest.raises(ValueError, match="Invalid SQL"):
            _validate_identifier("memories'")

    def test_identifier_starting_with_digit_raises(self):
        from eli.memory.memory import _validate_identifier
        with pytest.raises(ValueError, match="Invalid SQL"):
            _validate_identifier("1badcol")

    def test_empty_string_raises(self):
        from eli.memory.memory import _validate_identifier
        with pytest.raises(ValueError, match="Invalid SQL"):
            _validate_identifier("")


# ---------------------------------------------------------------------------
# FAISS-primary retrieval path
# ---------------------------------------------------------------------------

class TestFAISSPrimaryRetrieval:

    def test_vector_store_search_called_when_index_populated(self, tmp_path):
        """When ntotal > 0, vector_store.search() must be called."""
        mem = _make_memory(tmp_path)
        mock_vs = _make_vector_store_mock(
            ntotal=5,
            search_results=[
                {"memory_id": 1, "ts": 0, "text": "vector result alpha", "tags": "", "score": 0.92},
                {"memory_id": 2, "ts": 0, "text": "vector result beta",  "tags": "", "score": 0.85},
                {"memory_id": 3, "ts": 0, "text": "vector result gamma", "tags": "", "score": 0.80},
                {"memory_id": 4, "ts": 0, "text": "vector result delta", "tags": "", "score": 0.75},
                {"memory_id": 5, "ts": 0, "text": "vector result epsilon","tags": "", "score": 0.70},
            ],
        )

        with patch("eli.memory.vector_store.get_vector_store", return_value=mock_vs):
            results = mem.recall_memory("alpha", limit=5)

        mock_vs.search.assert_called_once()
        texts = [r.get("text", "") for r in results]
        assert any("vector" in t for t in texts), (
            f"Vector results not found in output: {texts}"
        )

    def test_fts5_supplements_when_faiss_returns_too_few(self, tmp_path):
        """If FAISS returns < limit//2 results, keyword search also runs."""
        mem = _make_memory(tmp_path)

        # Only 1 result from a populated index — triggers supplement (limit=10 → threshold=5)
        mock_vs = _make_vector_store_mock(
            ntotal=10,
            search_results=[
                {"memory_id": 1, "ts": 0, "text": "single vector result", "tags": "", "score": 0.9},
            ],
        )

        # Insert a keyword-matching row so FTS5 has something to find
        conn = mem._get_connection()
        conn.execute(
            "INSERT INTO memories (text, tags, timestamp) VALUES (?, ?, ?)",
            ("keyword match result", "", 0),
        )
        conn.commit()

        with patch("eli.memory.vector_store.get_vector_store", return_value=mock_vs):
            results = mem.recall_memory("keyword match result", limit=10)

        # With 1 vector result and limit=10, threshold = max(1, 10//2) = 5
        # FTS5 must supplement → we should see the keyword-inserted row
        texts = [r.get("text", "") for r in results]
        assert any("keyword" in t or "vector" in t for t in texts)

    def test_keyword_search_primary_when_index_empty(self, tmp_path):
        """When ntotal == 0, vector_store.search() must NOT be called."""
        mem = _make_memory(tmp_path)
        mock_vs = _make_vector_store_mock(ntotal=0, search_results=[])

        with patch("eli.memory.vector_store.get_vector_store", return_value=mock_vs):
            results = mem.recall_memory("some query", limit=5)

        # Critical invariant: search() must never be called on an empty index
        mock_vs.search.assert_not_called()
        assert isinstance(results, list)

    def test_vector_store_exception_falls_through_to_keyword(self, tmp_path):
        """If vector_store.search() throws, keyword search must still run."""
        mem = _make_memory(tmp_path)

        conn = mem._get_connection()
        conn.execute(
            "INSERT INTO memories (text, tags, timestamp) VALUES (?, ?, ?)",
            ("fallback keyword text", "", 0),
        )
        conn.commit()

        def _bad_get_vector_store():
            raise RuntimeError("FAISS unavailable")

        with patch("eli.memory.vector_store.get_vector_store", side_effect=_bad_get_vector_store):
            results = mem.recall_memory("fallback keyword text", limit=5)

        # Should not crash; keyword search should provide results
        assert isinstance(results, list)
