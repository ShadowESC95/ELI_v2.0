"""A prune must never leave the FAISS index and its metadata out of step.

`search()` maps a FAISS position straight to `self._meta[idx]`. The old `_prune()`
skipped the VECTOR when an embed failed but kept the METADATA row:

    for entry, vec in zip(keep, vecs):
        if vec is not None:
            new_index.add(vec)
    self._index = new_index
    self._meta  = keep          # ← every row kept

From the first failure onward every position mapped to the wrong entry, so search
returned a memory whose text did not belong to the matched vector — with a
confident score — and the misalignment was flushed to disk. `add()` and
`rebuild_full()` both keep the pair in lockstep; only this path did not.

`search()` guards `idx >= len(self._meta)`, which is the opposite direction and
cannot see this.

Latent rather than live: MAX_ENTRIES is 50,000, so a prune only happens on a very
full store — which is exactly why it needs a test rather than a field report.
"""
import numpy as np
import pytest

from eli.memory import vector_store as vs


class _FakeIndex:
    """Minimal stand-in for faiss.IndexFlatL2.

    The suite mocks `faiss` session-wide (tests/conftest.py), so a real index is
    not available here — and a MagicMock cannot answer `ntotal`, which is the
    exact quantity this file is about.
    """

    def __init__(self, dim):
        self.dim = dim
        self.rows = []

    @property
    def ntotal(self):
        return len(self.rows)

    def add(self, arr):
        self.rows.append(np.asarray(arr, dtype="float32").reshape(-1))

    def search(self, vec, k):
        q = np.asarray(vec, dtype="float32").reshape(-1)
        if not self.rows:
            return np.zeros((1, 0), dtype="float32"), np.zeros((1, 0), dtype="int64")
        d = np.array([[float(((r - q) ** 2).sum()) for r in self.rows]], dtype="float32")
        idx = np.argsort(d, axis=1)[:, :k]
        return np.take_along_axis(d, idx, axis=1), idx.astype("int64")


@pytest.fixture
def store(tmp_path, monkeypatch):
    """A store with a deterministic fake embedder and a tiny prune threshold."""
    import threading

    monkeypatch.setattr(vs, "MAX_ENTRIES", 6, raising=False)
    monkeypatch.setattr(vs.faiss, "IndexFlatL2", _FakeIndex, raising=False)

    s = vs.VectorStore.__new__(vs.VectorStore)
    s._lock = threading.RLock()
    s._embed_lock = threading.RLock()
    s._index = _FakeIndex(vs.EMBED_DIM)
    s._meta = []
    s._adds_since_save = 0
    s._save_generation = 0
    s._index_path = str(tmp_path / "idx.faiss")
    s._meta_path = str(tmp_path / "meta.json")
    s._embedder = object()          # non-None so _embed is attempted

    fail_on = set()

    def fake_embed(text):
        if text in fail_on:
            return None
        h = abs(hash(text)) % 997
        return np.full((1, vs.EMBED_DIM), h / 997.0, dtype="float32")

    monkeypatch.setattr(s, "_embed", fake_embed, raising=False)
    monkeypatch.setattr(s, "_save_async", lambda: None, raising=False)
    monkeypatch.setattr(s, "flush", lambda: None, raising=False)
    return s, fail_on


def _fill(store, n):
    for i in range(n):
        store._index.add(store._embed(f"memory {i}"))
        store._meta.append({"text": f"memory {i}"})


def test_prune_keeps_them_aligned_when_every_embed_succeeds(store):
    s, _ = store
    _fill(s, 10)
    s._prune()
    assert s._index.ntotal == len(s._meta), "index and metadata diverged"
    assert len(s._meta) == vs.MAX_ENTRIES


def test_a_failed_re_embed_drops_the_row_with_its_vector(store):
    """The bug: the vector was skipped and the row was kept."""
    s, fail_on = store
    _fill(s, 10)
    fail_on.add("memory 5")          # one of the newest six
    s._prune()
    assert s._index.ntotal == len(s._meta), (
        f"index has {s._index.ntotal} vectors but metadata has {len(s._meta)} rows — "
        "search would return the wrong memory for every position after the failure")
    assert all(e["text"] != "memory 5" for e in s._meta)


def test_several_failures_still_leave_them_aligned(store):
    s, fail_on = store
    _fill(s, 12)
    fail_on.update({"memory 7", "memory 9", "memory 11"})
    s._prune()
    assert s._index.ntotal == len(s._meta)


def test_search_returns_the_text_that_matches_the_vector(store):
    """End to end: the point of alignment is that a hit means what it says."""
    s, fail_on = store
    _fill(s, 10)
    fail_on.add("memory 6")
    s._prune()

    target = s._meta[-1]["text"]
    hits = s.search(target, top_k=1)
    assert hits, "no results after prune"
    assert hits[0]["text"] == target, (
        f"search matched the vector for {target!r} but returned {hits[0]['text']!r}")


def test_every_failure_leaves_an_empty_but_consistent_store(store):
    s, fail_on = store
    _fill(s, 8)
    fail_on.update(f"memory {i}" for i in range(8))
    s._prune()
    assert s._index.ntotal == 0 and s._meta == []


def test_prune_does_not_hold_the_store_lock_while_embedding(store):
    """The lock must be free during inference — its own comment always said so,
    and the CALL SITE used to defeat it.

    Probed from ANOTHER thread on purpose. `self._lock` is an RLock, so the
    thread that owns it can re-acquire it freely; asking "is it held?" from the
    embedding thread itself answers yes either way and proves nothing. Driven
    through add(), because calling _prune() directly bypasses the caller that
    used to hold the lock.
    """
    import threading

    s, _ = store
    _fill(s, vs.MAX_ENTRIES)          # next add() tips it over and triggers a prune

    free_when_embedding = []
    real_embed = s._embed

    def probe_from_other_thread():
        got = s._lock.acquire(blocking=False)
        free_when_embedding.append(bool(got))
        if got:
            s._lock.release()

    def watching_embed(text):
        t = threading.Thread(target=probe_from_other_thread)
        t.start()
        t.join()
        return real_embed(text)

    s._embed = watching_embed
    assert s.add("one more memory") is True
    assert s._index.ntotal == len(s._meta)
    assert free_when_embedding, "no embedding happened — the prune did not run"
    assert all(free_when_embedding), (
        "another thread could not take the store lock while prune was embedding — "
        "memory reads and writes are blocked for the whole rebuild")
