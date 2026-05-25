import sqlite3

from eli.memory.memory import Memory
from eli.runtime.evidence_ledger import recent_events, record_event, repeated_event_signals


def _count(db, table):
    with sqlite3.connect(str(db)) as conn:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_user_turn_updates_profile_patterns_and_replay_buffer(tmp_path):
    db = tmp_path / "user.sqlite3"
    mem = Memory(db_path=db, secondary_paths=[])

    mem.add_conversation_turn(
        "user",
        "I prefer in depth diagnostics and no bullshit when debugging ELI memory.",
        session_id="test-session",
        user_id="local-user",
    )

    assert _count(db, "conversation_turns") == 1
    assert _count(db, "learning_replay") == 1
    assert _count(db, "user_patterns") >= 1
    assert _count(db, "runtime_events") >= 2


def test_app_command_updates_habit_tables_and_replay_buffer(tmp_path):
    db = tmp_path / "user.sqlite3"
    mem = Memory(db_path=db, secondary_paths=[])

    mem.store_app_cmd("spotify", "spotify", method="test")
    mem.log_learning_event(
        "command_result",
        input_text="open spotify",
        output_text="Opened app: Spotify",
        action="OPEN_APP",
        outcome="ok",
        reward=1.0,
        metadata={"source": "test"},
    )

    assert _count(db, "habit_events") >= 1
    assert _count(db, "habits") >= 1
    assert _count(db, "habit_rules") >= 1
    assert _count(db, "learning_replay") >= 1


def test_runtime_evidence_ledger_tracks_repeated_events(tmp_path):
    db = tmp_path / "user.sqlite3"

    import time as _time
    # Use explicit timestamps >10 seconds apart so the dedup gate in
    # record_event doesn't suppress the second write.  The dedup window
    # exists to prevent concurrent-thread noise within a single turn;
    # repeated_event_signals() tracks genuine recurrences across turns.
    t0 = _time.time() - 30  # 30 seconds ago
    t1 = _time.time() - 5   # 5 seconds ago

    record_event(
        "executor_action",
        source="test",
        action="LIST_DIR",
        subject="/missing",
        content="Path not found",
        payload={"error": "Path not found"},
        outcome="failed",
        db_path=db,
        timestamp=t0,
    )
    record_event(
        "executor_action",
        source="test",
        action="LIST_DIR",
        subject="/missing",
        content="Path not found",
        payload={"error": "Path not found"},
        outcome="failed",
        db_path=db,
        timestamp=t1,
    )

    rows = recent_events(limit=5, db_path=db)
    repeats = repeated_event_signals(limit=5, db_path=db)

    assert len(rows) == 2
    assert repeats
    assert repeats[0]["count"] == 2
