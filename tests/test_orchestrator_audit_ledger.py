"""Unit tests: tamper-evident orchestrator/DAG audit ledger
(eli.runtime.orchestrator_audit_ledger). Metadata-only sibling of
evidence_ledger's runtime_events chain — same HMAC-SHA256 design, same key,
separate table/file so its append-only retention never mixes with prunable
dispatch telemetry.

Mirrors tests/test_audit_ledger.py's structure. Every call passes an explicit
db_path to a throwaway file.
"""
import os
import sqlite3
import tempfile

import pytest

from eli.runtime import orchestrator_audit_ledger as L


@pytest.fixture()
def ledger_db():
    path = os.path.join(tempfile.mkdtemp(prefix="eli_orch_audit_"), "orch.sqlite3")
    yield path


def _seed(db, n=5):
    for i in range(n):
        L.record_turn(
            request_id=f"req-{i}", session_id="s1", user_id="alice" if i % 2 == 0 else "bob",
            action="NEWS_FETCH", reasoning_mode="quick", agents_used="system,voice",
            confidence=0.9, elapsed_ms=120.5, ok=True,
            outcome="ok", db_path=db,
        )


def test_intact_chain_verifies(ledger_db):
    _seed(ledger_db, 5)
    v = L.verify_chain(db_path=ledger_db)
    assert v["ok"] is True
    assert v["chained"] == 5
    assert v["keyed"] is True
    assert v["first_break"] is None


def test_content_tamper_is_detected(ledger_db):
    _seed(ledger_db, 4)
    conn = sqlite3.connect(ledger_db)
    conn.execute("UPDATE orchestrator_audit SET action='HACKED' WHERE id=2")
    conn.commit()
    conn.close()
    v = L.verify_chain(db_path=ledger_db)
    assert v["ok"] is False
    assert v["first_break"]["id"] == 2
    assert "tampered" in v["first_break"]["reason"]


def test_deleted_row_breaks_the_link(ledger_db):
    _seed(ledger_db, 4)
    conn = sqlite3.connect(ledger_db)
    conn.execute("DELETE FROM orchestrator_audit WHERE id=2")
    conn.commit()
    conn.close()
    v = L.verify_chain(db_path=ledger_db)
    assert v["ok"] is False
    assert "broken link" in v["first_break"]["reason"]


def test_recent_turns_returns_newest_first(ledger_db):
    _seed(ledger_db, 3)
    rows = L.recent_turns(limit=10, db_path=ledger_db)
    assert len(rows) == 3
    assert rows[0]["request_id"] == "req-2"
    assert rows[-1]["request_id"] == "req-0"


def test_no_prompt_or_response_content_in_the_schema(ledger_db):
    """The whole point is metadata only — this must never grow a content column."""
    _seed(ledger_db, 1)
    conn = sqlite3.connect(ledger_db)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(orchestrator_audit)")}
    conn.close()
    assert "content" not in cols
    assert "response" not in cols
    assert "prompt" not in cols


def test_empty_ledger_verifies_ok():
    v = L.verify_chain(db_path=os.path.join(tempfile.mkdtemp(), "empty.sqlite3"))
    assert v["ok"] is True
    assert v["checked"] == 0


def test_async_writes_land_in_call_order(ledger_db):
    """Live bug (2026-10-02): engine.py's _record_orchestrator_audit_turn used
    to background each call in its OWN fresh threading.Thread — two turns
    committed close together raced for the SQLite write lock with no
    ordering guarantee between them, caught by a test failing once under
    system load. record_turn_async queues onto ONE persistent worker thread
    instead, so write order matches call (enqueue) order regardless of how
    long any individual write takes."""
    for i in range(5):
        L.record_turn_async(
            request_id=f"async-{i}", session_id="s1", user_id="alice",
            action="CHAT", reasoning_mode="quick", agents_used="",
            confidence=0.5, elapsed_ms=None, ok=True, outcome="ok",
            db_path=ledger_db,
        )
    assert L.flush(timeout=10.0)

    rows = L.recent_turns(limit=10, db_path=ledger_db)
    assert [r["request_id"] for r in rows] == [f"async-{i}" for i in (4, 3, 2, 1, 0)]
    v = L.verify_chain(db_path=ledger_db)
    assert v["ok"] is True and v["chained"] == 5


def test_no_fabricated_stage_mask_column(ledger_db):
    """Live correction (2026-10-02): a 'stages ran' field was planned from a
    deterministic action+mode rule, not from anything that actually confirmed
    each stage completed — the pipeline's own stage logging only covers 2 of
    12 stages today. Shipping that column would silently report a plan as a
    fact. Don't fabricate it; every column here must be something the code
    genuinely observed."""
    _seed(ledger_db, 1)
    conn = sqlite3.connect(ledger_db)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(orchestrator_audit)")}
    conn.close()
    assert "stage_mask" not in cols
    assert "stages" not in cols


# ── chain v2: source + parent_request_id are signed ─────────────────────────

def test_source_and_parent_are_recorded_and_returned(ledger_db):
    L.record_turn(request_id="req-child", parent_request_id="req-parent", source="followthrough",
                  action="NEWS_FETCH", db_path=ledger_db)
    row = L.recent_turns(limit=1, db_path=ledger_db)[0]
    assert row["source"] == "followthrough"
    assert row["parent_request_id"] == "req-parent"


@pytest.mark.parametrize("column,forged", [("source", "user"), ("parent_request_id", "")])
def test_editing_source_or_parent_breaks_the_chain(ledger_db, column, forged):
    """Relabelling an autonomous action as user-requested (or cutting a child
    run loose from the request that caused it) must not verify."""
    L.record_turn(request_id="r1", source="habit", parent_request_id="p1", db_path=ledger_db)
    L.record_turn(request_id="r2", source="user", db_path=ledger_db)
    conn = sqlite3.connect(ledger_db)
    conn.execute(f"UPDATE orchestrator_audit SET {column}=? WHERE id=1", (forged,))
    conn.commit()
    conn.close()
    v = L.verify_chain(db_path=ledger_db)
    assert v["ok"] is False
    assert v["first_break"]["id"] == 1
    assert "tampered" in v["first_break"]["reason"]


def _insert_v1_row(db, request_id):
    """A row as the pre-v2 code wrote it: chain_v NULL, source/parent unsigned."""
    conn = L._connect(db)
    try:
        last = conn.execute("SELECT chain_sig FROM orchestrator_audit ORDER BY id DESC LIMIT 1").fetchone()
        prev = last[0] if last else L._GENESIS
        base = (1000.0, request_id, "s", "u", "CHAT", "quick", "", 0.5, 10.0, 1, "ok")
        sig = L._chain_signature(prev, base, L._audit_key())
        conn.execute(
            "INSERT INTO orchestrator_audit (ts, request_id, session_id, user_id, action, "
            "reasoning_mode, agents_used, confidence, elapsed_ms, ok, outcome, prev_sig, "
            "chain_sig, keyed) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,1)", base + (prev, sig))
        conn.commit()
    finally:
        conn.close()


def test_existing_v1_rows_still_verify_after_upgrade(ledger_db):
    _insert_v1_row(ledger_db, "old-1")
    _insert_v1_row(ledger_db, "old-2")
    L.record_turn(request_id="new-1", source="user", db_path=ledger_db)
    v = L.verify_chain(db_path=ledger_db)
    assert v["ok"] is True, v
    assert v["chained"] == 3


def test_v1_row_after_a_v2_row_is_a_downgrade(ledger_db):
    """Someone rewriting the tail in the old format to drop the signed source."""
    L.record_turn(request_id="new-1", source="habit", db_path=ledger_db)
    _insert_v1_row(ledger_db, "forged")
    v = L.verify_chain(db_path=ledger_db)
    assert v["ok"] is False
    assert v["first_break"]["id"] == 2
    assert "downgrade" in v["first_break"]["reason"]


def test_flush_reports_a_drained_queue(ledger_db):
    L.record_turn_async(request_id="f1", db_path=ledger_db)
    assert L.flush(timeout=10.0) is True
    assert L.recent_turns(limit=5, db_path=ledger_db)[0]["request_id"] == "f1"
