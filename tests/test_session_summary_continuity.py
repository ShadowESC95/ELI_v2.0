"""Session-end continuity: in-depth LLM session summary, recent-sessions digest,
and preference-weighted recall (the user's 3-part memory upgrade)."""
import sqlite3
import time
from pathlib import Path

from eli.runtime import profile_extractor as pe
from eli.cognition import persona_updater as pu


def _seed_turns(db: Path):
    pe.ensure_profile_tables(db)
    con = sqlite3.connect(str(db))
    con.execute(
        "CREATE TABLE IF NOT EXISTS conversation_turns("
        "id INTEGER PRIMARY KEY, session_id TEXT, user_id TEXT, role TEXT, "
        "content TEXT, ts REAL, timestamp REAL)"
    )
    now = time.time()
    turns = [
        ("s1", "u1", "user", "I'm building the Atlas weather-station rig, build 06", now - 100),
        ("s1", "u1", "assistant", "Build 06 is the approved baseline", now - 90),
        ("s1", "u1", "user", "I prefer in-depth answers; remind me to file the report", now - 80),
    ]
    for s, u, r, c, t in turns:
        con.execute(
            "INSERT INTO conversation_turns(session_id,user_id,role,content,ts,timestamp)"
            " VALUES (?,?,?,?,?,?)", (s, u, r, c, t, t))
    con.commit()
    con.close()


class _FakeBroker:
    gguf_ready = True

    def __init__(self, text):
        self._text = text

    def infer(self, prompt, system="", max_tokens=512, temperature=0.7, top_p=0.9, retry=True):
        return self._text


# ---- Piece 1: LLM session summary -----------------------------------------

def test_llm_session_summary_written(tmp_path):
    db = tmp_path / "user.sqlite3"
    _seed_turns(db)
    broker = _FakeBroker(
        "SUMMARY: User is building Atlas build 06 and wants the report filed.\n"
        "OPEN THREADS: file the report.\nUSER PREFERENCES: in-depth answers.")
    r = pe.write_llm_session_summary(db_path=db, session_id="s1", broker=broker)
    assert r["inserted"] and r["llm"] and r["source"] == "session_end"

    con = sqlite3.connect(str(db))
    row = con.execute(
        "SELECT summary, content, source FROM session_summaries WHERE session_id='s1'"
    ).fetchone()
    con.close()
    assert "Atlas" in row[0]
    assert "OPEN THREADS" in row[1]      # full sectioned text kept in content
    assert row[2] == "session_end"


def test_degenerate_summary_falls_back_to_heuristic(tmp_path):
    db = tmp_path / "user.sqlite3"
    _seed_turns(db)
    r = pe.write_llm_session_summary(db_path=db, session_id="s1", broker=_FakeBroker("-"))
    assert r["inserted"] and not r["llm"]
    assert r["source"] == "session_end_heuristic"


def test_session_summary_is_idempotent(tmp_path):
    db = tmp_path / "user.sqlite3"
    _seed_turns(db)
    for _ in range(3):
        pe.write_llm_session_summary(db_path=db, session_id="s1", broker=_FakeBroker("SUMMARY: ok thing happened here."))
    con = sqlite3.connect(str(db))
    n = con.execute(
        "SELECT COUNT(*) FROM session_summaries WHERE session_id='s1' "
        "AND source IN ('session_end','session_end_heuristic')").fetchone()[0]
    con.close()
    assert n == 1   # replaced, not accumulated


# ---- Piece 2: recent-sessions digest --------------------------------------

def test_digest_prefers_session_summaries(tmp_path):
    db = tmp_path / "user.sqlite3"
    pe.ensure_profile_tables(db)
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE IF NOT EXISTS memories(id INTEGER PRIMARY KEY, text TEXT, tags TEXT)")
    now = time.time()
    con.execute("INSERT INTO session_summaries(session_id,summary,content,source,ended_at,timestamp,ts)"
                " VALUES('s1','Atlas build 06 progress','full',?,?,?,?)", ("session_end", now - 10, now - 10, now - 10))
    con.execute("INSERT INTO session_summaries(session_id,summary,content,source,ended_at,timestamp,ts)"
                " VALUES('s2','Beacon module iteration 3','full',?,?,?,?)", ("session_end", now, now, now))
    con.execute("INSERT INTO memories(text,tags) VALUES('an old short session narrative line','session_summary')")
    con.commit()
    con.close()

    class M:
        db_path = str(db)
    out = pu._get_session_narrative(M(), limit=3)
    assert any("Beacon module" in o for o in out) and any("Atlas" in o for o in out)
    assert out[0].startswith("Beacon")                     # newest first
    assert not any("old short session" in o for o in out)  # not the memories fallback


def test_digest_falls_back_to_memories_when_table_empty(tmp_path):
    db = tmp_path / "user.sqlite3"
    pe.ensure_profile_tables(db)
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE IF NOT EXISTS memories(id INTEGER PRIMARY KEY, text TEXT, tags TEXT)")
    con.execute("INSERT INTO memories(text,tags) VALUES('a sufficiently long old session narrative for continuity','session_summary,continuity')")
    con.commit()
    con.close()

    class M:
        db_path = str(db)
    out = pu._get_session_narrative(M(), limit=3)
    assert out and "old session narrative" in out[0]


# ---- Piece 3: preference-weighted recall ----------------------------------

def test_preference_memory_ranks_high(tmp_path):
    from eli.memory.memory import Memory
    mem = Memory(db_path=str(tmp_path / "user.sqlite3"))
    # A plain note and a durable preference, both matching the query term.
    mem.store_memory("the reactor uses a tungsten electrode", source="user", kind="note")
    mem.store_memory("I prefer the reactor diagnostics shown in-depth",
                     source="user", kind="preference", tags=["preference"])
    hits = mem.recall_memory("reactor", limit=5)
    assert hits, "recall returned nothing"
    texts = [h.get("text", "") for h in hits]
    # The preference fact should surface, and rank at or above the plain note.
    pref_idx = next((i for i, t in enumerate(texts) if "prefer" in t.lower()), None)
    note_idx = next((i for i, t in enumerate(texts) if "tungsten" in t.lower()), None)
    assert pref_idx is not None
    if note_idx is not None:
        assert pref_idx <= note_idx
