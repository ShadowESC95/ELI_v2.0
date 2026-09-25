"""The memory report says what memory is: two layers, with self-improvement records owned by the agent database."""
import sqlite3
import time

from eli.memory.memory import AGENT_OWNED_TABLES, Memory
from eli.runtime import deterministic_grounding_gate as gate
from eli.runtime.evidence_ledger import ensure_schema


def test_report_names_both_layers_and_the_owner_of_self_improvement(tmp_path, monkeypatch):
    user, agent = tmp_path / "user.sqlite3", tmp_path / "agent.sqlite3"
    Memory(db_path=user), Memory(db_path=agent)
    monkeypatch.setattr(gate, "_eli_db_paths_v2", lambda: {
        "user_db": user, "agent_db": agent, "vector_index": tmp_path / "i", "vector_meta": tmp_path / "m"})
    text = gate._eli_memory_internals_v2()
    assert "not a dump of every interaction" in text
    assert "Conversation history" in text and "Distilled memory" in text
    user_part, agent_part = text.split("## agent.sqlite3")
    assert not any(f"- {t}:" in user_part for t in AGENT_OWNED_TABLES)
    assert all(f"- {t}:" in agent_part for t in ("improvements", "failures", "corrections", "capability_proposals"))


def test_a_learning_event_is_stored_once(tmp_path):
    mem = Memory(db_path=tmp_path / "user.sqlite3")
    mem.log_learning_event("conversation_turn", input_text="hello", output_text="hi", action="CHAT")
    con = sqlite3.connect(mem.db_path)
    assert con.execute("select count(*) from learning_replay").fetchone()[0] == 1
    tables = {r[0] for r in con.execute("select name from sqlite_master")}
    assert "runtime_events" not in tables or not con.execute(
        "select count(*) from runtime_events where source='memory.log_learning_event'").fetchone()[0]


def test_upkeep_removes_earlier_ledger_copies_of_replay_rows(tmp_path):
    mem = Memory(db_path=tmp_path / "user.sqlite3")
    con = sqlite3.connect(mem.db_path)
    ensure_schema(con)
    con.execute("insert into runtime_events (event_type, source, timestamp) values ('learning_replay', 'memory.log_learning_event', ?)", (time.time(),))
    con.commit()
    con.close()
    assert mem.tidy_learning_tables()["replay_mirrors_removed"] == 1
    con = sqlite3.connect(mem.db_path)
    assert con.execute("select count(*) from runtime_events").fetchone()[0] == 0
