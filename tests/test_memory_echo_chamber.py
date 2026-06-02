"""Memory echo-chamber guards (B1 + B2).

B1: ELI's own cross-session recall-narration is not stored as an assistant turn.
B2: recall-narration is filtered from search results, and the active session is
    preferred — so stale self-talk can't drown the live conversation.
"""
import time
import tempfile

from eli.runtime.persistence_gate import (
    should_store_conversation_turn, is_recall_narration,
)


_ECHO = ("From a previous session, we were troubleshooting some issues with my "
         "SQLite-backed memory recall and fine-tuning the local GGUF runtime "
         "parameters. Physics time, indeed.")
_ECHO2 = "From the previous session, you asked if I remembered what we discussed."
_GENUINE = "The capital of France is Paris."
_GENUINE2 = "I fixed the router bug we hit earlier today; want me to push it?"


def test_b1_recall_narration_not_stored():
    assert is_recall_narration(_ECHO) is True
    assert should_store_conversation_turn("assistant", _ECHO) is False
    assert should_store_conversation_turn("assistant", _ECHO2) is False
    # genuine assistant turns are kept
    assert should_store_conversation_turn("assistant", _GENUINE) is True
    assert should_store_conversation_turn("assistant", _GENUINE2) is True
    # a USER turn that quotes the phrase is NOT blocked (only assistant self-talk)
    assert should_store_conversation_turn("user", _ECHO) is True


def test_b2_search_filters_narration_and_prefers_session():
    from eli.memory.memory import Memory
    db = tempfile.mktemp(suffix=".sqlite3")
    try:
        m = Memory(db_path=db)
    except TypeError:
        m = Memory()
    conn = m._get_connection()
    conn.execute(
        "CREATE TABLE IF NOT EXISTS conversation_turns "
        "(id INTEGER PRIMARY KEY, timestamp REAL, ts REAL, session_id TEXT, "
        "user_id TEXT, role TEXT, content TEXT)")
    now = time.time()
    rows = [
        (now - 500000, "old", "u", "assistant", _ECHO),
        (now - 60,     "cur", "u", "user", "today i worked on the memory recall code"),
    ]
    for r in rows:
        conn.execute(
            "INSERT INTO conversation_turns(timestamp,ts,session_id,user_id,role,content)"
            " VALUES(?,?,?,?,?,?)", (r[0], r[0], r[1], r[2], r[3], r[4]))
    conn.commit()
    conn.close()

    res = m.search_conversations("recall memory previous", limit=10, session_id="cur")
    # narration is gone
    assert all("from a previous session" not in (h.get("content") or "").lower()
               for h in res)
    # current-session row is first
    assert res and res[0].get("session_id") == "cur"
