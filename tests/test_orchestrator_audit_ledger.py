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
