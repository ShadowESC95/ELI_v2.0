"""Unit tests: tamper-evident audit ledger (eli.runtime.evidence_ledger).

The runtime_events ledger is hash-chained: each row's chain_sig commits to the
previous row's chain_sig. verify_chain() must:
- report an intact chain after a normal sequence of events,
- detect a field edited after the fact (content tamper),
- detect a deleted/reordered row (broken link),
and recent_events(user_id=...) must isolate one user's events.

Uses sqlite3 + hashlib only (no FastAPI/pydantic), so it runs in-process under the
suite's conftest mocks. Every call passes an explicit db_path to a throwaway file —
the real ledger is never touched.
"""
import os
import sqlite3
import tempfile

import pytest

from eli.runtime import evidence_ledger as L


@pytest.fixture()
def ledger_db():
    path = os.path.join(tempfile.mkdtemp(prefix="eli_audit_"), "audit.sqlite3")
    yield path


def _seed(db, n=5):
    for i in range(n):
        L.record_event("executor_action", source="executor", action=f"ACTION_{i}",
                        subject=f"s{i}", outcome="ok",
                        user_id="alice" if i % 2 == 0 else "bob", db_path=db)


def test_intact_chain_verifies(ledger_db):
    _seed(ledger_db, 5)
    v = L.verify_chain(db_path=ledger_db)
    assert v["ok"] is True
    assert v["chained"] == 5
    assert v["first_break"] is None


def test_per_user_filter_isolates(ledger_db):
    _seed(ledger_db, 6)
    alice = L.recent_events(user_id="alice", db_path=ledger_db)
    assert alice and all(e["user_id"] == "alice" for e in alice)
    bob = L.recent_events(user_id="bob", db_path=ledger_db)
    assert bob and all(e["user_id"] == "bob" for e in bob)


def test_field_edit_is_detected(ledger_db):
    _seed(ledger_db, 5)
    conn = sqlite3.connect(ledger_db)
    conn.execute("UPDATE runtime_events SET outcome='FORGED' WHERE action='ACTION_2'")
    conn.commit()
    conn.close()
    v = L.verify_chain(db_path=ledger_db)
    assert v["ok"] is False
    assert "content tampered" in v["first_break"]["reason"]


def test_row_deletion_is_detected(ledger_db):
    _seed(ledger_db, 5)
    conn = sqlite3.connect(ledger_db)
    conn.execute("DELETE FROM runtime_events WHERE action='ACTION_2'")
    conn.commit()
    conn.close()
    v = L.verify_chain(db_path=ledger_db)
    assert v["ok"] is False
    assert "broken link" in v["first_break"]["reason"]


def test_chain_links_each_row_to_previous(ledger_db):
    """Structural: every row's prev_sig equals the prior row's chain_sig."""
    _seed(ledger_db, 4)
    conn = sqlite3.connect(ledger_db)
    rows = conn.execute(
        "SELECT prev_sig, chain_sig FROM runtime_events ORDER BY id ASC"
    ).fetchall()
    conn.close()
    assert rows[0][0] == L._GENESIS
    for i in range(1, len(rows)):
        assert rows[i][0] == rows[i - 1][1]  # prev_sig == previous chain_sig
