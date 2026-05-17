from __future__ import annotations

import json
import os
import sqlite3
import time
import hashlib
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
    raw = "|".join(_norm(part, 1000) for part in parts)
    return hashlib.sha1(raw.encode("utf-8", "ignore")).hexdigest()


def _connect(db_path: Optional[str | Path] = None) -> sqlite3.Connection:
    path = Path(db_path).expanduser().resolve() if db_path else _default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=5.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
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
            signature TEXT
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
    ]:
        if name not in existing:
            conn.execute(f"ALTER TABLE runtime_events ADD COLUMN {name} {decl}")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_runtime_events_ts ON runtime_events(ts)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_runtime_events_type ON runtime_events(event_type)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_runtime_events_signature ON runtime_events(signature)")


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
    sig = _signature([event_type, source, action, subject, content, payload.get("error") or payload.get("path") or ""])
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            """
            INSERT INTO runtime_events (
                ts, timestamp, event_type, source, action, subject, content,
                payload_json, severity, outcome, confidence, reusable,
                session_id, user_id, request_id, signature
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now,
                now,
                _norm(event_type, 120),
                _norm(source, 160),
                _norm(action, 160),
                _norm(subject, 300),
                _norm(content, 4000),
                _json(payload)[:30000],
                _norm(severity, 80) or "info",
                _norm(outcome, 160),
                confidence,
                1 if reusable else 0,
                _norm(session_id, 200),
                _norm(user_id, 200),
                _norm(request_id, 200),
                sig,
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
