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


def test_different_users_same_action_recorded_separately(ledger_db):
    """Audit attribution: two users doing the identical action within the dedup window
    must each be recorded — user_id is part of the dedup signature."""
    a = L.record_event("e", source="api", action="EXECUTE", user_id="alice", db_path=ledger_db)
    b = L.record_event("e", source="api", action="EXECUTE", user_id="bob", db_path=ledger_db)
    assert a != b  # not collapsed into one row
    # but the SAME user's duplicate (racing threads, same turn) still collapses
    a2 = L.record_event("e", source="api", action="EXECUTE", user_id="alice", db_path=ledger_db)
    assert a2 == a


def test_totals_and_users_summary(ledger_db):
    for u, act, oc in [("alice", "CHAT", "ok"), ("alice", "EXECUTE", "ok"),
                       ("bob", "EXECUTE", "failed"), ("bob", "CHAT", "ok"),
                       ("carol", "RESEARCH", "ok")]:
        L.record_event("e", source="api", action=act, outcome=oc,
                       severity=("error" if oc == "failed" else "info"),
                       user_id=u, db_path=ledger_db)
    t = L.totals(db_path=ledger_db)
    assert t == {"events": 5, "failed": 1, "users": 3}
    us = {u["user_id"]: (u["events"], u["failed"]) for u in L.users_summary(db_path=ledger_db)}
    assert us["bob"] == (2, 1) and us["alice"] == (2, 0) and us["carol"] == (1, 0)


def test_hmac_defeats_knowledgeable_forger(ledger_db, monkeypatch):
    """With an HMAC key, a forger who can write the DB but not read the key cannot
    produce a clean chain even by recomputing chain_sig with plain SHA-256."""
    import hashlib
    monkeypatch.setenv("ELI_AUDIT_HMAC_KEY", "test-key-not-on-disk")
    for i in range(5):
        L.record_event("e", source="api", action=f"A{i}", user_id="u", db_path=ledger_db)
    v = L.verify_chain(db_path=ledger_db)
    assert v["ok"] and v["keyed"] is True

    conn = sqlite3.connect(ledger_db)
    row = conn.execute(
        "SELECT id, ts, event_type, source, action, subject, content, payload_json, severity, "
        "outcome, confidence, reusable, session_id, user_id, request_id, signature, prev_sig "
        "FROM runtime_events ORDER BY id LIMIT 1 OFFSET 2").fetchone()
    rid, prev = row[0], row[16]
    vals = [row[1], row[2], row[3], "FORGED", row[5], row[6], row[7], row[8], row[9],
            row[10], row[11], row[12], row[13], row[14], row[15]]
    forged = hashlib.sha256(("\x1f".join([str(prev)] + ["" if x is None else str(x) for x in vals])).encode()).hexdigest()
    conn.execute("UPDATE runtime_events SET action='FORGED', chain_sig=? WHERE id=?", (forged, rid))
    conn.commit()
    conn.close()
    v2 = L.verify_chain(db_path=ledger_db)
    assert v2["ok"] is False  # the plain-SHA-256 forgery doesn't match the HMAC


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
