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


def _store_on_disk(tmp_path, saved_texts):
    """A bare store with a real saved index of `saved_texts`, and an embedder that can be cut off."""
    faiss = pytest.importorskip("faiss")
    import numpy as np
    from eli.memory.vector_store import EMBED_DIM
    vs = _bare_store()
    vs._index_path, vs._meta_path, vs._save_generation = str(tmp_path / "index.faiss"), str(tmp_path / "meta.json"), 0
    vs._index = faiss.IndexFlatL2(EMBED_DIM)
    if saved_texts:
        vs._index.add(np.ones((len(saved_texts), EMBED_DIM), dtype="float32"))
    vs._meta = [{"memory_id": i, "text": t} for i, t in enumerate(saved_texts)]
    vs.flush()

    class Embedder:
        _llm = None
        calls = 0
        stop_after = None

        def embed(self, text):
            Embedder.calls += 1
            if Embedder.stop_after and Embedder.calls >= Embedder.stop_after:
                vs._closed, vs._embedder = True, None      # what close() at shutdown does
            return [0.5] * EMBED_DIM
    return vs, Embedder, faiss


def test_a_rebuild_cut_short_by_shutdown_keeps_the_saved_index(tmp_path):
    """Live: a background rebuild was still running when ELI closed; it replaced the index with the
    2 memories it had reached and saved that, and the next start loaded 2 vectors."""
    vs, Embedder, faiss = _store_on_disk(tmp_path, ["saved one", "saved two", "saved three"])
    Embedder.stop_after = 2
    vs._embedder = Embedder()
    assert vs.rebuild_full([{"text": f"memory {i}", "memory_id": i} for i in range(10)]) is False
    assert [m["text"] for m in vs._meta] == ["saved one", "saved two", "saved three"] and vs.ntotal == 3
    assert faiss.read_index(vs._index_path).ntotal == 3


def test_a_rebuild_without_its_model_keeps_the_saved_index(tmp_path):
    vs, _Embedder, faiss = _store_on_disk(tmp_path, ["saved one", "saved two"])
    vs._embedder = None
    assert vs.rebuild_full([{"text": "memory", "memory_id": 1}]) is False
    assert vs.ntotal == 2 and faiss.read_index(vs._index_path).ntotal == 2


def test_the_rebuild_button_indexes_what_the_policy_keeps_with_ids(tmp_path, monkeypatch):
    """The upgrade step and the settings button used a second rebuild that emptied the live index
    first, ignored the storage policy (166 entries where 73 belonged) and could pair vectors with
    the wrong texts."""
    import sqlite3
    from eli.memory.memory import Memory, rebuild_vector_index_from_search_db
    db = tmp_path / "user.sqlite3"
    mem = Memory(db_path=str(db))
    ids = [mem.store_memory(t, tags=["conversation"])["id"] for t in
           ("the garden fence needs a coat of paint", "the kettle in the back kitchen is new",
            "Top topics: garden, kettle, paint")]
    with sqlite3.connect(db) as c:
        c.execute("UPDATE memories SET origin = 'telemetry' WHERE id = ?", (ids[2],))
    monkeypatch.setattr("eli.core.paths.user_db_path", lambda: db)
    vs, Embedder, _faiss = _store_on_disk(tmp_path, [])
    vs._embedder = Embedder()
    monkeypatch.setattr("eli.memory.vector_store.get_vector_store", lambda: vs)
    result = rebuild_vector_index_from_search_db()
    assert result["ok"] and result["indexed"] == 2 and result["source_count"] == 2 and result["skipped"] == 0
    assert sorted(m["memory_id"] for m in vs._meta) == sorted(ids[:2])
    assert all(m["text"] in ("the garden fence needs a coat of paint", "the kettle in the back kitchen is new")
               for m in vs._meta)
