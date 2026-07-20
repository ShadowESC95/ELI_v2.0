from __future__ import annotations

import json
import os
import sqlite3
import time
import hashlib
import hmac
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


def _default_db_path() -> Path:
    try:
        from eli.core.paths import get_user_db_path

        return Path(get_user_db_path()).expanduser().resolve()
    except Exception:
        root = Path(__file__).resolve().parents[2]
        return (root / "artifacts" / "db" / "user.sqlite3").resolve()


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        return json.dumps({"repr": repr(value)}, ensure_ascii=False)


def _norm(value: Any, limit: int = 4000) -> str:
    text = " ".join(str(value or "").split()).strip()
    return text[:limit]


def _signature(parts: Iterable[Any]) -> str:
    # Content/dedup fingerprint (NOT the security boundary — that's the chain below).
    # SHA-256 for consistency with the chain.
    raw = "|".join(_norm(part, 1000) for part in parts)
    return hashlib.sha256(raw.encode("utf-8", "ignore")).hexdigest()


# ── Tamper-evident, HMAC-keyed hash chain ────────────────────────────────────
# Each event's chain_sig = HMAC-SHA256(key, prev_chain_sig ⊕ this row's stored fields).
# Every row commits to the one before it (off a fixed genesis), so an edit, deletion, or
# reorder breaks the chain — which verify_chain() detects. Keying it with a secret stored
# SEPARATELY from the DB means a local attacker who can write the SQLite file but cannot
# read the key cannot forge a clean, self-consistent chain (without the key the chain is
# only tamper-EVIDENT; with it, tampering is also unforgeable). The key lives at
# config/.audit_hmac_key (0600) or $ELI_AUDIT_HMAC_KEY; keep it off the DB's media/backups.
_GENESIS = "ELI-AUDIT-GENESIS"
_SEP = "\x1f"  # unit separator — can't appear in normalised text/JSON values

# The exact stored columns (in order) that the chain commits to. Anything an auditor
# cares about — who/what/when/outcome — is here; id and the chain columns are excluded.
_CHAIN_FIELDS = (
    "ts", "event_type", "source", "action", "subject", "content", "payload_json",
    "severity", "outcome", "confidence", "reusable", "session_id", "user_id",
    "request_id", "signature",
)


def _audit_key() -> Optional[bytes]:
    """The HMAC key for the audit chain: $ELI_AUDIT_HMAC_KEY, else a 0600 file beside the
    config (NOT beside the DB). Created on first use. None only if it can't be read/made."""
    env = os.environ.get("ELI_AUDIT_HMAC_KEY", "").strip()
    if env:
        return env.encode("utf-8")
    try:
        from eli.core.paths import config_dir
        kp = Path(config_dir()) / ".audit_hmac_key"
    except Exception:
        kp = Path("config") / ".audit_hmac_key"
    try:
        if kp.exists():
            data = kp.read_text(encoding="utf-8").strip()
            return data.encode("utf-8") if data else None
        import secrets as _secrets
        key = _secrets.token_hex(32)
        # Born locked (0600) — never world-readable, even for the instant
        # between create and chmod. See eli.core.secure_io.
        from eli.core.secure_io import secure_write_text as _secure_write
        _secure_write(kp, key, mode=0o600)
        return key.encode("utf-8")
    except Exception:
        return None


def _chain_signature(prev_sig: str, ordered_values: Iterable[Any], key: Optional[bytes] = None) -> str:
    parts = [str(prev_sig if prev_sig is not None else "")]
    parts.extend("" if v is None else str(v) for v in ordered_values)
    raw = _SEP.join(parts).encode("utf-8", "ignore")
    if key:
        return hmac.new(key, raw, hashlib.sha256).hexdigest()
    return hashlib.sha256(raw).hexdigest()


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
        CREATE TABLE IF NOT EXISTS runtime_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL,
            timestamp REAL,
            event_type TEXT,
            source TEXT,
            action TEXT,
            subject TEXT,
            content TEXT,
            payload_json TEXT,
            severity TEXT,
            outcome TEXT,
            confidence REAL,
            reusable INTEGER DEFAULT 1,
            session_id TEXT,
            user_id TEXT,
            request_id TEXT,
            signature TEXT,
            prev_sig TEXT,
            chain_sig TEXT,
            keyed INTEGER DEFAULT 0
        )
        """
    )
    existing = [r[1] for r in conn.execute("PRAGMA table_info(runtime_events)").fetchall()]
    for name, decl in [
        ("ts", "REAL"),
        ("timestamp", "REAL"),
        ("event_type", "TEXT"),
        ("source", "TEXT"),
        ("action", "TEXT"),
        ("subject", "TEXT"),
        ("content", "TEXT"),
        ("payload_json", "TEXT"),
        ("severity", "TEXT"),
        ("outcome", "TEXT"),
        ("confidence", "REAL"),
        ("reusable", "INTEGER DEFAULT 1"),
        ("session_id", "TEXT"),
        ("user_id", "TEXT"),
        ("request_id", "TEXT"),
        ("signature", "TEXT"),
        # Tamper-evidence: each row commits to the previous row's chain_sig, so any
        # edit/deletion/reorder breaks the chain (see _chain_signature / verify_chain).
        ("prev_sig", "TEXT"),
        ("chain_sig", "TEXT"),
        ("keyed", "INTEGER DEFAULT 0"),
    ]:
        if name not in existing:
            conn.execute(f"ALTER TABLE runtime_events ADD COLUMN {name} {decl}")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_runtime_events_ts ON runtime_events(ts)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_runtime_events_type ON runtime_events(event_type)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_runtime_events_signature ON runtime_events(signature)")


# Dedup window: identical signature written within this many seconds → skip insert.
# Handles race conditions from concurrent threads and duplicate call paths for the
# same conversation turn. Set to 0 to disable.
_DEDUP_WINDOW_SECONDS: float = 10.0


def record_event(
    event_type: str,
    *,
    source: str = "runtime",
    action: str = "",
    subject: str = "",
    content: Any = "",
    payload: Optional[Dict[str, Any]] = None,
    severity: str = "info",
    outcome: str = "",
    confidence: Optional[float] = None,
    reusable: bool = True,
    session_id: str = "",
    user_id: str = "",
    request_id: str = "",
    db_path: Optional[str | Path] = None,
    timestamp: Optional[float] = None,
) -> int:
    now = float(timestamp or time.time())
    payload = dict(payload or {})
    # user_id + session_id are part of the dedup signature so that two DIFFERENT users
    # (or sessions) performing the same action are recorded SEPARATELY — the audit must
    # attribute each actor — while a single actor's duplicate writes (same turn, racing
    # threads) still collapse.
    sig = _signature([event_type, source, action, subject, content,
                      payload.get("error") or payload.get("path") or "", user_id, session_id])
    # Pre-normalise once; these exact stored values are what the chain commits to.
    v_event = _norm(event_type, 120)
    v_source = _norm(source, 160)
    v_action = _norm(action, 160)
    v_subject = _norm(subject, 300)
    v_content = _norm(content, 4000)
    v_payload = _json(payload)[:30000]
    v_severity = _norm(severity, 80) or "info"
    v_outcome = _norm(outcome, 160)
    v_reusable = 1 if reusable else 0
    v_session = _norm(session_id, 200)
    v_user = _norm(user_id, 200)
    v_request = _norm(request_id, 200)
    conn = _connect(db_path)
    try:
        # Serialise the read-prev → compute → insert so concurrent writers can't fork
        # the chain (the audit log is low-rate; an immediate write lock is fine).
        conn.execute("BEGIN IMMEDIATE")
        # Deduplication: skip if the same signature was inserted within the dedup window.
        # This prevents duplicate rows from concurrent threads writing the same event.
        if _DEDUP_WINDOW_SECONDS > 0:
            existing = conn.execute(
                "SELECT id FROM runtime_events WHERE signature = ? AND ts >= ? LIMIT 1",
                (sig, now - _DEDUP_WINDOW_SECONDS),
            ).fetchone()
            if existing:
                conn.commit()
                return int(existing[0])

        # Chain link: this row commits to the previous row's chain_sig (genesis if first).
        last = conn.execute(
            "SELECT chain_sig FROM runtime_events WHERE chain_sig IS NOT NULL "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
        prev_sig = (last[0] if last and last[0] else _GENESIS)
        ordered = (now, v_event, v_source, v_action, v_subject, v_content, v_payload,
                   v_severity, v_outcome, confidence, v_reusable, v_session, v_user,
                   v_request, sig)
        key = _audit_key()
        chain_sig = _chain_signature(prev_sig, ordered, key)
        keyed = 1 if key else 0

        cur = conn.execute(
            """
            INSERT INTO runtime_events (
                ts, timestamp, event_type, source, action, subject, content,
                payload_json, severity, outcome, confidence, reusable,
                session_id, user_id, request_id, signature, prev_sig, chain_sig, keyed
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now, now, v_event, v_source, v_action, v_subject, v_content,
                v_payload, v_severity, v_outcome, confidence, v_reusable,
                v_session, v_user, v_request, sig, prev_sig, chain_sig, keyed,
            ),
        )
        conn.commit()
        return int(cur.lastrowid or 0)
    finally:
        conn.close()


def recent_events(
    *,
    limit: int = 20,
    event_type: str | None = None,
    source: str | None = None,
    action: str | None = None,
    reusable_only: bool = False,
    user_id: str | None = None,
    db_path: Optional[str | Path] = None,
) -> List[Dict[str, Any]]:
    sql = (
        "SELECT id, ts, event_type, source, action, subject, content, payload_json, "
        "severity, outcome, confidence, reusable, session_id, user_id, request_id, signature "
        "FROM runtime_events"
    )
    where: List[str] = []
    params: List[Any] = []
    if event_type:
        where.append("event_type = ?")
        params.append(event_type)
    if source:
        where.append("source = ?")
        params.append(source)
    if action:
        where.append("action = ?")
        params.append(action)
    if user_id is not None:
        where.append("user_id = ?")
        params.append(_norm(user_id, 200))
    if reusable_only:
        where.append("COALESCE(reusable, 1) = 1")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY COALESCE(ts, timestamp, id) DESC LIMIT ?"
    params.append(int(limit or 20))
    conn = _connect(db_path)
    try:
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()

    out: List[Dict[str, Any]] = []
    for row in rows:
        payload: Any = row[7]
        if isinstance(payload, str) and payload:
            try:
                payload = json.loads(payload)
            except Exception:
                payload = {"raw": payload}
        out.append(
            {
                "id": row[0],
                "timestamp": row[1],
                "event_type": row[2],
                "source": row[3],
                "action": row[4],
                "subject": row[5],
                "content": row[6],
                "payload": payload if isinstance(payload, dict) else {},
                "severity": row[8],
                "outcome": row[9],
                "confidence": row[10],
                "reusable": bool(row[11]),
                "session_id": row[12],
                "user_id": row[13],
                "request_id": row[14],
                "signature": row[15],
            }
        )
    return out


def verify_chain(db_path: Optional[str | Path] = None) -> Dict[str, Any]:
    """Walk the tamper-evident hash chain and report its integrity.

    Recomputes each row's chain_sig from its stored fields + the previous row's
    chain_sig. Any edited field, deleted row, or reordering makes a recomputed
    signature mismatch or breaks the prev_sig linkage — reported as the first break.

    Returns ``{ok, checked, chained, legacy, keyed, first_break}``. ``keyed`` is True when
    the chain is HMAC-protected (a local forger without the key can't produce a clean
    chain). Once HMAC starts, a later UNkeyed row is treated as a downgrade attempt."""
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id, ts, event_type, source, action, subject, content, payload_json, "
            "severity, outcome, confidence, reusable, session_id, user_id, request_id, "
            "signature, prev_sig, chain_sig, keyed FROM runtime_events ORDER BY id ASC"
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
        stored_chain = r[17]
        if stored_chain is None:
            legacy += 1  # pre-tamper-evidence row; not part of the chain
            continue
        checked += 1
        stored_prev = r[16]
        row_keyed = bool(r[18])
        # 1) Linkage: this row must commit to the previous chained row.
        if str(stored_prev or "") != str(prev_chain):
            first_break = {"id": rid, "reason": "broken link (prev_sig != previous chain_sig) "
                                                 "— a row was deleted, reordered, or inserted"}
            break
        # 1b) No downgrade: once the chain is HMAC-keyed, every later row must be too.
        if keyed_seen and not row_keyed:
            first_break = {"id": rid, "reason": "downgrade attempt — an unkeyed row after the "
                                                "HMAC-keyed epoch (chain may have been rewritten)"}
            break
        if row_keyed and key is None:
            first_break = {"id": rid, "reason": "HMAC key unavailable — cannot verify a keyed row"}
            break
        # 2) Integrity: recompute this row's chain_sig from its stored fields (+ key if keyed).
        ordered = (r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9], r[10],
                   r[11], r[12], r[13], r[14], r[15])
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


_FAILED_SQL = "(LOWER(COALESCE(outcome,'')) IN ('failed','error') OR LOWER(COALESCE(severity,'')) = 'error')"


def totals(db_path: Optional[str | Path] = None) -> Dict[str, Any]:
    """Aggregate counts across the whole audit ledger (events, failures, distinct users)."""
    conn = _connect(db_path)
    try:
        ev = conn.execute("SELECT COUNT(*) FROM runtime_events").fetchone()[0]
        failed = conn.execute(f"SELECT COUNT(*) FROM runtime_events WHERE {_FAILED_SQL}").fetchone()[0]
        users = conn.execute(
            "SELECT COUNT(DISTINCT COALESCE(NULLIF(user_id,''),'(system)')) FROM runtime_events"
        ).fetchone()[0]
    finally:
        conn.close()
    return {"events": int(ev or 0), "failed": int(failed or 0), "users": int(users or 0)}


def users_summary(db_path: Optional[str | Path] = None) -> List[Dict[str, Any]]:
    """Per-user activity rollup for the admin console: event count, failures, last seen."""
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            f"""
            SELECT COALESCE(NULLIF(user_id,''),'(system)') AS u,
                   COUNT(*) AS n,
                   SUM(CASE WHEN {_FAILED_SQL} THEN 1 ELSE 0 END) AS f,
                   MAX(COALESCE(ts, timestamp)) AS last_ts
            FROM runtime_events
            GROUP BY u
            ORDER BY n DESC
            """
        ).fetchall()
    finally:
        conn.close()
    return [{"user_id": r[0], "events": int(r[1] or 0), "failed": int(r[2] or 0),
             "last_seen": r[3]} for r in rows]


def repeated_event_signals(*, limit: int = 8, days: int = 3, db_path: Optional[str | Path] = None) -> List[Dict[str, Any]]:
    since = time.time() - float(days or 3) * 86400.0
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT signature, event_type, action, subject, COUNT(*) AS n, MAX(ts) AS last_ts
            FROM runtime_events
            WHERE COALESCE(ts, timestamp, 0) >= ?
            GROUP BY signature, event_type, action, subject
            HAVING COUNT(*) > 1
            ORDER BY n DESC, last_ts DESC
            LIMIT ?
            """,
            (since, int(limit or 8)),
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "signature": r[0],
            "event_type": r[1],
            "action": r[2],
            "subject": r[3],
            "count": int(r[4] or 0),
            "last_timestamp": r[5],
        }
        for r in rows
    ]


def artifact_snapshot(kind: str = "all", limit: int = 12) -> List[Dict[str, Any]]:
    root = _project_root() / "artifacts"
    kind = str(kind or "all").lower()
    dirs: List[Path] = []
    if kind in {"all", "image", "images"}:
        dirs.append(root / "image_engine" / "outputs")
    if kind in {"all", "document", "documents"}:
        dirs.append(root / "documents")
    if kind in {"all", "script", "scripts"}:
        dirs.append(root / "scripts")

    rows: List[Dict[str, Any]] = []
    for directory in dirs:
        if not directory.exists():
            continue
        for path in directory.iterdir():
            try:
                if not path.is_file():
                    continue
                stat = path.stat()
                rows.append(
                    {
                        "path": str(path),
                        "name": path.name,
                        "size": stat.st_size,
                        "mtime": stat.st_mtime,
                        "kind": directory.name,
                    }
                )
            except Exception:
                continue
    rows.sort(key=lambda item: float(item.get("mtime") or 0), reverse=True)
    return rows[: int(limit or 12)]


# Actions that genuinely produce a user-facing artifact.
_GENERATION_ACTIONS = (
    "GENERATE_SCRIPT", "CODE_SOLVE", "GENERATE_DOCUMENT", "DOC_GENERATE",
    "CREATE_DOCUMENT", "CONVERT_DOCUMENT", "CREATE_FILE", "GENERATE_PROJECT",
)


def recent_generated_artifacts(*, hours: float = 24, limit: int = 6,
                               db_path: Optional[str | Path] = None) -> List[Dict[str, Any]]:
    """Artifacts ELI ACTUALLY generated, from recorded generation events within
    the window — NOT filesystem mtime (which any touch/copy/regen bumps, so a
    week-old script can look 'just generated'). Returns newest-first, deduped by
    name: [{"name", "action", "ts"}].
    """
    since = time.time() - float(hours or 24) * 3600.0
    placeholders = ",".join("?" * len(_GENERATION_ACTIONS))
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            f"""
            SELECT ts, action, subject, content
            FROM runtime_events
            WHERE event_type = 'executor_action'
              AND action IN ({placeholders})
              AND COALESCE(ts, timestamp, 0) >= ?
            ORDER BY COALESCE(ts, timestamp, 0) DESC
            LIMIT 200
            """,
            (*_GENERATION_ACTIONS, since),
        ).fetchall()
    except Exception:
        return []
    finally:
        try:
            conn.close()
        except Exception:
            pass

    out: List[Dict[str, Any]] = []
    seen: set = set()
    for ts, action, subject, content in rows:
        name = ""
        c = str(content or "")
        # Preferred: the artifact_generated marker carries the real written path.
        if '"artifact_generated"' in c and '"path"' in c:
            try:
                i, j = c.find("{"), c.rfind("}")
                obj = json.loads(c[i:j + 1])
                p = obj.get("path")
                if p:
                    name = os.path.basename(str(p))
            except Exception:
                name = ""
        if not name:
            s = str(subject or "").strip()
            if s and s not in ("command_result",):
                name = os.path.basename(s) if ("/" in s or "." in s) else s
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({"name": name, "action": action, "ts": ts})
        if len(out) >= int(limit or 6):
            break
    return out


def status_evidence(question: str = "", *, db_path: Optional[str | Path] = None) -> Dict[str, Any]:
    text = str(question or "").lower()
    artifact_kind = "all"
    if any(word in text for word in ("image", "picture", "visual", "render")):
        artifact_kind = "image"
    elif "script" in text:
        artifact_kind = "script"
    elif any(word in text for word in ("document", "report", "thesis", "article")):
        artifact_kind = "document"

    return {
        "question": str(question or ""),
        "recent_runtime_events": recent_events(limit=12, db_path=db_path),
        "repeated_event_signals": repeated_event_signals(limit=8, db_path=db_path),
        "recent_artifacts": artifact_snapshot(artifact_kind, limit=12),
        "runtime_events_db": str(Path(db_path).expanduser().resolve() if db_path else _default_db_path()),
    }
