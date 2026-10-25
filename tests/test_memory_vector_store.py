"""eli.memory.vector_store: what the store does with and without its embedding model, and after close()."""
from __future__ import annotations

import os
import threading

import pytest

from eli.memory.vector_store import VectorStore, resolve_embedder_path


def _bare_store():
    vs = VectorStore.__new__(VectorStore)
    vs._lock = threading.RLock()
    vs._embed_lock = threading.RLock()
    vs._closed = False
    vs._index = None
    vs._meta = []
    vs._adds_since_save = 0
    return vs


def test_vector_store_add_reports_unindexed_when_embedder_missing():
    vs = _bare_store()
    vs._embedder = None
    assert vs.add("memory text", metadata={"memory_id": 1}) is False


def test_vector_store_add_reports_indexed_on_success():
    class DummyIndex:
        ntotal = 0

        def add(self, vec):
            self.ntotal += 1

    vs = _bare_store()
    vs._index = DummyIndex()
    vs._embed = lambda text: object()
    vs._prune = lambda: None
    vs._save_async = lambda: None

    assert vs.add("memory text", metadata={"memory_id": 1}) is True
    assert vs.ntotal == 1
    assert vs.meta_count == 1


def test_a_closed_store_never_touches_its_model_again():
    """Engine shutdown closed the embedding model underneath the store and left it in place; the
    next embed (a late memory, a search, the document indexer) read freed native memory and the
    process died with a segmentation fault."""
    calls = {"embed": 0, "close": 0}

    class Llm:
        def close(self):
            calls["close"] += 1

    class Embedder:
        _llm = Llm()

        def embed(self, text):
            calls["embed"] += 1
            return [1.0, 0.0]

    vs = _bare_store()
    vs._embedder = Embedder()
    assert vs.embed_text("before") == [1.0, 0.0]
    vs.close()
    assert calls == {"embed": 1, "close": 1}
    vs._init_embedder = lambda: pytest.fail("a closed store loaded its model again")
    assert vs.embed_text("after") is None and vs._embed("after") is None and vs._get_embedder() is None
    assert vs.add("after", metadata={"memory_id": 2}) is False
    assert calls["embed"] == 1


@pytest.mark.skipif(not os.path.isfile(resolve_embedder_path() or ""), reason="no embedding model in models/embeddings")
def test_the_real_model_finds_by_meaning_and_survives_close(tmp_path, monkeypatch):
    monkeypatch.setenv("ELI_ARTIFACTS_DIR", str(tmp_path))
    vs = VectorStore()
    assert vs._embedder is not None, vs._embedder_error
    assert vs.add("The cat slept on the warm windowsill all afternoon", metadata={"memory_id": 1})
    assert vs.add("Quarterly VAT return is due at the end of the month", metadata={"memory_id": 2})
    hits = vs.search("a sleepy kitten in the sun", top_k=2)
    assert hits and "cat" in hits[0]["text"]
    assert isinstance(vs.search("!@#$%^&*() Héllo wörld", top_k=1000), list)
    vs.close()
    assert vs.embed_text("after close") is None
    assert vs.add("after close", metadata={"memory_id": 3}) is False
