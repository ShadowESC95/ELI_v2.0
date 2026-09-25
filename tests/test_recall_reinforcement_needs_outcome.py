"""Retrieving a memory must not strengthen it; an answer nobody corrected does, and a corrected one weakens it."""
import sqlite3

import pytest

from eli.memory.memory import Memory


@pytest.fixture()
def mem(tmp_path, monkeypatch):
    monkeypatch.setenv("ELI_TEST_MODE", "1")
    monkeypatch.setattr("eli.memory.vector_store.get_vector_store", lambda: None)
    return Memory(db_path=tmp_path / "user.sqlite3")


def _row(mem, rid):
    c = sqlite3.connect(mem.db_path)
    try:
        return c.execute("select weight, recall_count, exposure_count, corrected_count from memories where id = ?", (rid,)).fetchone()
    finally:
        c.close()


def _weaken(mem, rid):
    c = sqlite3.connect(mem.db_path)
    c.execute("update memories set weight = 0.3 where id = ?", (rid,))
    c.commit()
    c.close()


def test_helped_reinforces_and_counts_a_use(mem):
    rid = mem.store_memory("I keep my running shoes by the back door of the house")["id"]
    _weaken(mem, rid)
    assert mem.record_recall_outcome([rid], helped=True) == 1
    weight, recalls, _exposed, corrected = _row(mem, rid)
    assert weight == 1.0 and recalls == 1 and corrected == 0


def test_corrected_weakens_and_never_counts_as_a_use(mem):
    rid = mem.store_memory("I keep my running shoes by the back door of the house")["id"]
    assert mem.record_recall_outcome([rid], helped=False) == 1
    weight, recalls, _exposed, corrected = _row(mem, rid)
    assert weight <= 0.5 and recalls == 0 and corrected == 1


def test_a_corrected_memory_cannot_be_rescued_by_retrieval_alone(mem):
    rid = mem.store_memory("I keep my running shoes by the back door of the house")["id"]
    mem.record_recall_outcome([rid], helped=False)
    before = _row(mem, rid)
    for _ in range(5):
        mem.recall_memory("running shoes back door", limit=5)
    import time
    time.sleep(0.3)
    after = _row(mem, rid)
    assert after[0] == before[0] and after[1] == before[1]


def test_the_engine_settles_the_previous_answer_from_the_next_message():
    from eli.kernel.engine import CognitiveEngine

    calls = []

    class Mem:
        def record_recall_outcome(self, ids, helped):
            calls.append((list(ids), helped))

    class E:
        memory = Mem()
        _pending_recall_ids = [4, 5]
    e = E()
    CognitiveEngine._settle_recall_outcome(e, "no, that's wrong, I said Tuesday", "user")
    assert calls == [([4, 5], False)] and e._pending_recall_ids is None
    e._pending_recall_ids = [7]
    CognitiveEngine._settle_recall_outcome(e, "great, thanks", "user")
    assert calls[-1] == ([7], True)
    e._pending_recall_ids = [9]
    CognitiveEngine._settle_recall_outcome(e, "run the nightly job", "habit")
    assert e._pending_recall_ids == [9]
