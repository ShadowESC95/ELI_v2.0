"""A question about a period is answered from that period, with dates, not from the best keyword match."""
import sqlite3
import time
from types import SimpleNamespace

import pytest

from eli.cognition.evidence_format import when_label
from eli.cognition.query_planner import parse_window
from eli.memory.memory import Memory
from eli.memory.unified_retrieval import orchestrator_retrieve

DAY = 86400.0


@pytest.fixture()
def engine(tmp_path, monkeypatch):
    monkeypatch.setenv("ELI_TEST_MODE", "1")
    monkeypatch.setattr("eli.memory.vector_store.get_vector_store", lambda: None)
    mem = Memory(db_path=tmp_path / "user.sqlite3")
    now = time.time()
    c = sqlite3.connect(mem.db_path)
    for days, text in [(3, "i am watching dune again, the second one"),
                       (9, "just started the new arrival film"),
                       (33, "i am watching severance, not much of a deal")]:
        ts = now - days * DAY
        c.execute("insert into conversation_turns (session_id, user_id, role, content, ts, timestamp) "
                  "values ('s', 'old-id', 'user', ?, ?, ?)", (text, ts, ts))
    c.commit()
    c.close()
    return SimpleNamespace(memory=mem, session_id="s", user_id="a-different-id")


def _plan(q):
    return {"need_keyword": True, "need_semantic": True, "window": parse_window(q)}


def test_only_the_period_asked_about_is_returned(engine):
    q = "What movies or series was i watching the past week or two?"
    kw, sem, tr = orchestrator_retrieve(engine, q, q, _plan(q))
    said = " ".join(h["text"] for h in kw + sem)
    assert "dune" in said and "arrival" in said
    assert "severance" not in said


def test_without_a_period_nothing_is_filtered_by_time(engine):
    q = "what do you know about severance"
    kw, sem, tr = orchestrator_retrieve(engine, q, q, {"need_keyword": True, "need_semantic": True})
    assert "severance" in " ".join(h["text"] for h in kw + sem)


def test_every_hit_exposes_its_date_to_ranking_and_display(engine):
    q = "what was i watching in the past week"
    kw, sem, tr = orchestrator_retrieve(engine, q, q, _plan(q))
    turns = [h for h in sem if h["source"] == "conversation"]
    assert turns and all(h.get("timestamp") for h in turns)
    assert all(when_label(h["timestamp"]).count(",") == 1 for h in turns)


def test_turns_from_earlier_user_ids_are_still_found(engine):
    q = "what was i watching the past week"
    _, sem, _ = orchestrator_retrieve(engine, q, q, _plan(q))
    assert any("dune" in h["text"] for h in sem)


def test_the_date_filter_finds_memories_the_topic_search_cannot(engine):
    mem = engine.memory
    now = time.time()
    mem.store_memory("Booked the flat viewing for Thursday afternoon", kind="note", tags="", importance=0.7)
    c = sqlite3.connect(mem.db_path)
    c.execute("update memories set event_ts=?, timestamp=?, ts=? where text like 'Booked the flat%'",
              (now - 4 * DAY, now - 4 * DAY, now - 4 * DAY))
    c.commit()
    c.close()
    q = "past week?"
    assert not mem.recall_memory(q, limit=12), "the topic search alone must not reach it"
    kw, sem, tr = orchestrator_retrieve(engine, q, q, _plan(q))
    assert "flat viewing" in " ".join(h["text"] for h in kw + sem)
    stats = tr.window_stats
    assert stats["added_by_time"] >= 1 and stats["in_window"] >= 1


def test_the_search_reports_what_the_window_did(engine):
    from eli.cognition import memory_diag
    q = "what was going on with me over the past week?"
    kw, sem, tr = orchestrator_retrieve(engine, q, q, _plan(q))
    diag = memory_diag.retrieval_record(len(kw), len(sem), 0, len(kw) + len(sem), None, window=tr.window_stats)
    assert "time-bounded to" in memory_diag.block(diag)
    assert "time-bounded to" in memory_diag.explanation(diag)
