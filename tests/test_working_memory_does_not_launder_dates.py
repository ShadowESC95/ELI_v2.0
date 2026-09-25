"""Recalled memories keep their own date and are never re-saved as new rows."""
import time

from eli.cognition.working_memory import WorkingMemory


class _Store:
    def __init__(self):
        self.rows = []

    def store_memory(self, text, **kw):
        self.rows.append((text, kw))
        return len(self.rows)


def _month_old():
    return time.time() - 30 * 86400


def test_a_recalled_memory_keeps_its_original_date():
    wm = WorkingMemory()
    old = _month_old()
    wm.absorb_memory_hits([{"text": "i am watching severance", "importance": 0.95, "ts": old}])
    fact = next(iter(wm._facts.values()))
    assert abs(fact.ts - old) < 1


def test_recalled_pins_are_not_written_back():
    wm = WorkingMemory()
    for _ in range(3):
        wm.absorb_memory_hits([{"text": "i am watching severance", "importance": 0.95, "ts": _month_old()}])
    store = _Store()
    assert wm.flush_to_memory(store) == 0
    assert store.rows == []


def test_a_fact_stated_this_session_is_still_saved():
    wm = WorkingMemory()
    wm.pin("i drive to cork on saturdays", source="user_explicit", importance=0.95)
    wm.pin("i drive to cork on saturdays", source="user_explicit", importance=0.95)  # second hit
    store = _Store()
    assert wm.flush_to_memory(store) == 1
