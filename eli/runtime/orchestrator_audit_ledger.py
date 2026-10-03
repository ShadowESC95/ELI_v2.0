"""Tamper-evident audit chain for the orchestrator pipeline — metadata only.

One row per turn (every CognitiveEngine.process() call), written when the
turn really ends: who, from where, action, agents actually used, confidence,
timing, outcome. No prompt/response content (see
evidence_ledger for that). No per-stage "ran" column — the pipeline's own
stage logging only covers 2 of 12 stages today, so that would report a plan,
not a fact. Reuses evidence_ledger's HMAC key/signature functions directly —
one key, one trust root for both ledgers.
"""
from __future__ import annotations

import atexit
import queue
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from eli.runtime.evidence_ledger import _audit_key, _chain_signature
from eli.utils.log import get_logger

log = get_logger(__name__)

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
            keyed INTEGER DEFAULT 0,
            source TEXT,
            chain_v INTEGER,
            parent_request_id TEXT
        )
        """
    )
    # Additive for chains created before these existed. Old rows keep chain_v NULL
    # and verify against the original field set; see _signed_fields().
    have = {r[1] for r in conn.execute("PRAGMA table_info(orchestrator_audit)")}
    for name, decl in (("source", "TEXT"), ("chain_v", "INTEGER"), ("parent_request_id", "TEXT")):
        if name not in have:
            conn.execute(f"ALTER TABLE orchestrator_audit ADD COLUMN {name} {decl}")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_orch_audit_ts ON orchestrator_audit(ts)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_orch_audit_request ON orchestrator_audit(request_id)")


# chain_v 2 signs `source` (user, api:<who>, habit, scheduled_task, followthrough...)
# and `parent_request_id` (set when a turn ran inside another one), so "a person
# asked" vs "ELI did this on its own" can't be edited after the fact.
_CHAIN_V = 2


def _signed_fields(base: tuple, source: Any, parent_request_id: Any, chain_v: Any) -> tuple:
    return base + (source, parent_request_id) if (chain_v or 0) >= 2 else base


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
    source: str = "",
    parent_request_id: str = "",
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
        ordered = _signed_fields(
            (now, request_id, session_id, user_id, action, reasoning_mode,
             agents_used, confidence, elapsed_ms, v_ok, outcome),
            source, parent_request_id, _CHAIN_V)
        key = _audit_key()
        chain_sig = _chain_signature(prev_sig, ordered, key)
        keyed = 1 if key else 0
        cur = conn.execute(
            """
            INSERT INTO orchestrator_audit (
                ts, request_id, session_id, user_id, action, reasoning_mode,
                agents_used, confidence, elapsed_ms, ok, outcome,
                prev_sig, chain_sig, keyed, source, chain_v, parent_request_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (now, request_id, session_id, user_id, action, reasoning_mode,
             agents_used, confidence, elapsed_ms, v_ok, outcome,
             prev_sig, chain_sig, keyed, source, _CHAIN_V, parent_request_id),
        )
        conn.commit()
        return int(cur.lastrowid or 0)
    finally:
        conn.close()


# ── Serialized async writer ──────────────────────────────────────────────────
# record_turn() itself is synchronous and correctly serializes against OTHER
# concurrent writers via BEGIN IMMEDIATE (the chain's hash links stay correct
# no matter which caller's transaction wins the lock race). But a caller that
# backgrounds each call in its OWN fresh threading.Thread (as engine.py's
# _record_orchestrator_audit_turn used to) has no ordering guarantee BETWEEN
# calls: two turns committed close together could have their rows land in
# whichever order the two independent threads happened to win the SQLite
# lock, not the order the turns actually happened in. ts still records real
# wall-clock time either way, so nothing is lost or misattributed, but a
# reviewer reading the log top-to-bottom could not trust row order for
# audit/compliance purposes. One persistent worker thread draining one FIFO
# queue fixes that: enqueue order (fast, no disk I/O) determines write order,
# not whichever write happens to finish first.
_write_queue: "queue.Queue[Dict[str, Any]]" = queue.Queue()
_worker_started = False
_worker_lock = threading.Lock()


def _worker_loop() -> None:
    while True:
        kwargs = _write_queue.get()
        try:
            record_turn(**kwargs)
        except Exception:
            log.debug("orchestrator audit async write failed", exc_info=True)
        finally:
            _write_queue.task_done()


def _ensure_worker() -> None:
    global _worker_started
    if _worker_started:
        return
    with _worker_lock:
        if _worker_started:
            return
        threading.Thread(
            target=_worker_loop, daemon=True, name="eli-orch-audit-writer"
        ).start()
        # Daemon threads still run during atexit, so this drains the queue
        # before the interpreter (or the GUI's os._exit, which runs atexit
        # first) kills the writer with rows still in it.
        atexit.register(flush)
        _worker_started = True


def record_turn_async(**kwargs: Any) -> None:
    """Queue a turn for the single serial writer thread instead of writing
    inline — callers that don't want to block a turn on this write (the
    normal case) should use this instead of backgrounding record_turn() in
    their own thread."""
    _ensure_worker()
    _write_queue.put(kwargs)


def record_direct_action(
    *,
    action: str,
    ok: bool,
    outcome: str,
    source: str,
    session_id: str = "",
    user_id: str = "",
    elapsed_ms: Optional[float] = None,
) -> str:
    """A row for an action run outside CognitiveEngine.process(): the GUI's voice
    fast path (OPEN_APP, READ_FILE, SCREENSHOT... straight to the executor) and
    UI buttons that call an action. Those never reach the engine, so without
    this they left no record at all. Returns the request id it used."""
    request_id = f"req-{uuid.uuid4().hex[:12]}"
    record_turn_async(
        request_id=request_id, session_id=str(session_id or ""), user_id=str(user_id or ""),
        source=str(source or ""), action=str(action or "").upper(),
        elapsed_ms=(round(float(elapsed_ms), 1) if elapsed_ms is not None else None),
        ok=bool(ok), outcome=str(outcome or "")[:500], timestamp=time.time(),
    )
    return request_id


def flush(timeout: float = 5.0) -> bool:
    """Wait for queued rows to be written. The writer is a daemon thread, so
    anything still queued when the process exits would be lost; registered
    with atexit by _ensure_worker. True if the queue drained in time."""
    deadline = time.monotonic() + max(0.0, float(timeout))
    while _write_queue.unfinished_tasks and time.monotonic() < deadline:
        time.sleep(0.01)
    return not _write_queue.unfinished_tasks


def recent_turns(limit: int = 50, db_path: Optional[str | Path] = None) -> List[Dict[str, Any]]:
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id, ts, request_id, session_id, user_id, action, reasoning_mode, "
            "agents_used, confidence, elapsed_ms, ok, outcome, source, parent_request_id "
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
            "source": r[12] or "", "parent_request_id": r[13] or "",
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
            "prev_sig, chain_sig, keyed, source, chain_v, parent_request_id "
            "FROM orchestrator_audit ORDER BY id ASC"
        ).fetchall()
    finally:
        conn.close()

    key = _audit_key()
    checked = 0
    chained = 0
    legacy = 0
    keyed_seen = False
    max_v_seen = 0
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
        row_v = int(r[16] or 0)
        if row_v < max_v_seen:
            first_break = {"id": rid, "reason": "downgrade attempt — an older-format row after "
                                                "a newer one (chain may have been rewritten)"}
            break
        ordered = _signed_fields(tuple(r[1:12]), r[15], r[17], row_v)
        recomputed = _chain_signature(stored_prev, ordered, key if row_keyed else None)
        if recomputed != str(stored_chain):
            first_break = {"id": rid, "reason": "content tampered (a field was edited "
                                                "after the row was written)"}
            break
        chained += 1
        keyed_seen = keyed_seen or row_keyed
        max_v_seen = max(max_v_seen, row_v)
        prev_chain = stored_chain

    return {
        "ok": first_break is None,
        "checked": checked,
        "chained": chained,
        "legacy": legacy,
        "keyed": keyed_seen,
        "first_break": first_break,
    }
