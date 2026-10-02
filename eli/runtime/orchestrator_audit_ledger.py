"""Tamper-evident audit chain for the orchestrator pipeline — metadata only.

One row per turn, written at the turn's real completion: action, agents
actually used, confidence, timing, outcome. No prompt/response content (see
evidence_ledger for that). No per-stage "ran" column — the pipeline's own
stage logging only covers 2 of 12 stages today, so that would report a plan,
not a fact. Reuses evidence_ledger's HMAC key/signature functions directly —
one key, one trust root for both ledgers.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from eli.runtime.evidence_ledger import _audit_key, _chain_signature

_GENESIS = "ELI-ORCHESTRATOR-AUDIT-GENESIS"


def _default_db_path() -> Path:
    from eli.core.paths import orchestrator_audit_db_path
    return orchestrator_audit_db_path()


def _connect(db_path: Optional[str | Path] = None) -> sqlite3.Connection:
    path = Path(db_path).expanduser().resolve() if db_path else _default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=5.0)
    from eli.core.sqlite_util import apply_pragmas
    apply_pragmas(conn, db_path=str(path), synchronous="NORMAL")
    ensure_schema(conn)
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS orchestrator_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL,
            request_id TEXT,
            session_id TEXT,
            user_id TEXT,
            action TEXT,
            reasoning_mode TEXT,
            agents_used TEXT,
            confidence REAL,
            elapsed_ms REAL,
            ok INTEGER,
            outcome TEXT,
            prev_sig TEXT,
            chain_sig TEXT,
            keyed INTEGER DEFAULT 0
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_orch_audit_ts ON orchestrator_audit(ts)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_orch_audit_request ON orchestrator_audit(request_id)")


def record_turn(
    *,
    request_id: str = "",
    session_id: str = "",
    user_id: str = "",
    action: str = "",
    reasoning_mode: str = "",
    agents_used: str = "",
    confidence: Optional[float] = None,
    elapsed_ms: Optional[float] = None,
    ok: bool = True,
    outcome: str = "",
    db_path: Optional[str | Path] = None,
    timestamp: Optional[float] = None,
) -> int:
    now = float(timestamp or time.time())
    v_ok = 1 if ok else 0
    conn = _connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        last = conn.execute(
            "SELECT chain_sig FROM orchestrator_audit WHERE chain_sig IS NOT NULL "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
        prev_sig = last[0] if last and last[0] else _GENESIS
        ordered = (now, request_id, session_id, user_id, action, reasoning_mode,
                   agents_used, confidence, elapsed_ms, v_ok, outcome)
        key = _audit_key()
        chain_sig = _chain_signature(prev_sig, ordered, key)
        keyed = 1 if key else 0
        cur = conn.execute(
            """
            INSERT INTO orchestrator_audit (
                ts, request_id, session_id, user_id, action, reasoning_mode,
                agents_used, confidence, elapsed_ms, ok, outcome,
                prev_sig, chain_sig, keyed
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (now, request_id, session_id, user_id, action, reasoning_mode,
             agents_used, confidence, elapsed_ms, v_ok, outcome,
             prev_sig, chain_sig, keyed),
        )
        conn.commit()
        return int(cur.lastrowid or 0)
    finally:
        conn.close()


def recent_turns(limit: int = 50, db_path: Optional[str | Path] = None) -> List[Dict[str, Any]]:
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id, ts, request_id, session_id, user_id, action, reasoning_mode, "
            "agents_used, confidence, elapsed_ms, ok, outcome "
            "FROM orchestrator_audit ORDER BY id DESC LIMIT ?",
            (int(limit or 50),),
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "id": r[0], "ts": r[1], "request_id": r[2], "session_id": r[3], "user_id": r[4],
            "action": r[5], "reasoning_mode": r[6], "agents_used": r[7],
            "confidence": r[8], "elapsed_ms": r[9], "ok": bool(r[10]), "outcome": r[11],
        }
        for r in rows
    ]


def verify_chain(db_path: Optional[str | Path] = None) -> Dict[str, Any]:
    """Same shape as evidence_ledger.verify_chain — walk the chain, recompute
    each row's signature, report the first break if any."""
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id, ts, request_id, session_id, user_id, action, reasoning_mode, "
            "agents_used, confidence, elapsed_ms, ok, outcome, "
            "prev_sig, chain_sig, keyed FROM orchestrator_audit ORDER BY id ASC"
        ).fetchall()
    finally:
        conn.close()

    key = _audit_key()
    checked = 0
    chained = 0
    legacy = 0
    keyed_seen = False
    prev_chain = _GENESIS
    first_break: Optional[Dict[str, Any]] = None
    for r in rows:
        rid = r[0]
        stored_chain = r[13]
        if stored_chain is None:
            legacy += 1
            continue
        checked += 1
        stored_prev = r[12]
        row_keyed = bool(r[14])
        if str(stored_prev or "") != str(prev_chain):
            first_break = {"id": rid, "reason": "broken link (prev_sig != previous chain_sig) "
                                                 "— a row was deleted, reordered, or inserted"}
            break
        if keyed_seen and not row_keyed:
            first_break = {"id": rid, "reason": "downgrade attempt — an unkeyed row after the "
                                                "HMAC-keyed epoch (chain may have been rewritten)"}
            break
        if row_keyed and key is None:
            first_break = {"id": rid, "reason": "HMAC key unavailable — cannot verify a keyed row"}
            break
        ordered = r[1:12]
        recomputed = _chain_signature(stored_prev, ordered, key if row_keyed else None)
        if recomputed != str(stored_chain):
            first_break = {"id": rid, "reason": "content tampered (a field was edited "
                                                "after the row was written)"}
            break
        chained += 1
        keyed_seen = keyed_seen or row_keyed
        prev_chain = stored_chain

    return {
        "ok": first_break is None,
        "checked": checked,
        "chained": chained,
        "legacy": legacy,
        "keyed": keyed_seen,
        "first_break": first_break,
    }
