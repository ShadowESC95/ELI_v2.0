"""Lessons: reflection outputs that expire and are checked against what happens next.

A lesson is a hypothesis, not a fact: trigger -> evidence -> proposed change -> predicted outcome. It
applies to one action, is checked each time that action runs, and is retired when it expires or when
the checks show it does not help. Nothing a lesson says is treated as true beyond that record.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from typing import Any, Dict, List, Optional

from eli.utils.log import get_logger

log = get_logger(__name__)

DEFAULT_TTL_DAYS = 30.0
MIN_CHECKS = 3
HELP_RATE_TO_KEEP = 0.5
HELP_RATE_TO_RENEW = 0.7
MAX_HARMED = 2
BASELINE_MARGIN = 0.05

_SCHEMA = """
CREATE TABLE IF NOT EXISTS lessons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lesson_key TEXT UNIQUE NOT NULL,
    applies_to TEXT NOT NULL,
    trigger_text TEXT NOT NULL,
    evidence TEXT,
    hypothesis TEXT,
    proposed_change TEXT NOT NULL,
    predicted_outcome TEXT,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    checks INTEGER NOT NULL DEFAULT 0,
    helped INTEGER NOT NULL DEFAULT 0,
    harmed INTEGER NOT NULL DEFAULT 0,
    renewals INTEGER NOT NULL DEFAULT 0,
    last_checked REAL,
    retired_reason TEXT,
    category TEXT,
    scope TEXT,
    baseline_rate REAL,
    baseline_n INTEGER,
    siblings TEXT,
    transfer_checks INTEGER NOT NULL DEFAULT 0,
    transfer_helped INTEGER NOT NULL DEFAULT 0
);
"""

_CACHE: Dict[str, Any] = {"at": 0.0, "actions": set()}


def _ensure(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    have = {r[1] for r in conn.execute("PRAGMA table_info(lessons)")}
    for name, decl in (("category", "TEXT"), ("scope", "TEXT"), ("baseline_rate", "REAL"), ("baseline_n", "INTEGER"),
                       ("siblings", "TEXT"), ("transfer_checks", "INTEGER NOT NULL DEFAULT 0"), ("transfer_helped", "INTEGER NOT NULL DEFAULT 0")):
        if name not in have:
            conn.execute(f"ALTER TABLE lessons ADD COLUMN {name} {decl}")


def _connect() -> sqlite3.Connection:
    from eli.core.paths import agent_db_path
    conn = sqlite3.connect(str(agent_db_path()), timeout=10)
    _ensure(conn)
    return conn


def _key(applies_to: str, trigger: str) -> str:
    return hashlib.sha1(f"{applies_to.upper()}|{trigger.strip().lower()}".encode()).hexdigest()[:20]


def propose(applies_to: str, trigger: str, evidence: List[str], proposed_change: str, *,
            hypothesis: str = "", predicted_outcome: str = "", ttl_days: float = DEFAULT_TTL_DAYS,
            now: Optional[float] = None, conn: Optional[sqlite3.Connection] = None, category: str = "",
            scope: Optional[List[str]] = None, baseline: Optional[tuple] = None,
            siblings: Optional[List[str]] = None) -> Optional[int]:
    """Record a lesson. The same trigger again adds evidence instead of a second lesson."""
    if not applies_to or not trigger or not proposed_change:
        return None
    own = conn is None
    conn = conn or _connect()
    try:
        _ensure(conn)
        now = float(now if now is not None else time.time())
        key = _key(applies_to, trigger)
        row = conn.execute("SELECT id, evidence, status FROM lessons WHERE lesson_key = ?", (key,)).fetchone()
        if row:
            if row[2] != "active":
                return None
            seen = json.loads(row[1] or "[]")
            merged = (seen + [e for e in evidence if e not in seen])[-6:]
            conn.execute("UPDATE lessons SET evidence = ? WHERE id = ?", (json.dumps(merged), row[0]))
            conn.commit()
            return int(row[0])
        cur = conn.execute(
            "INSERT INTO lessons (lesson_key, applies_to, trigger_text, evidence, hypothesis, proposed_change, "
            "predicted_outcome, created_at, expires_at, category, scope, baseline_rate, baseline_n, siblings) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (key, applies_to.upper(), trigger[:300], json.dumps(list(evidence)[-6:]), hypothesis[:400],
             proposed_change[:400], predicted_outcome[:300], now, now + float(ttl_days) * 86400.0, category,
             json.dumps(list(scope or [])), baseline[0] if baseline else None, baseline[1] if baseline else 0,
             json.dumps(list(siblings or []))))
        conn.commit()
        _CACHE["at"] = 0.0
        return int(cur.lastrowid)
    finally:
        if own:
            conn.close()


def applicable(action: str, *, now: Optional[float] = None, limit: int = 3, args: Optional[Dict[str, Any]] = None,
               conn: Optional[sqlite3.Connection] = None) -> List[Dict[str, Any]]:
    """Active lessons for this action. A lesson scoped to certain argument names applies only when they are present."""
    own = conn is None
    conn = conn or _connect()
    try:
        now = float(now if now is not None else time.time())
        rows = conn.execute(
            "SELECT id, applies_to, trigger_text, proposed_change, predicted_outcome, checks, helped, expires_at, scope "
            "FROM lessons WHERE status = 'active' AND expires_at > ? AND applies_to IN (?, '*') "
            "ORDER BY helped DESC, id DESC", (now, str(action).upper())).fetchall()
        names = ("id", "applies_to", "trigger", "change", "predicted", "checks", "helped", "expires_at")
        out = []
        for r in rows:
            scope = json.loads(r[8] or "[]")
            if scope and args is not None and not all(k in args for k in scope):
                continue
            out.append(dict(zip(names, r[:8])))
        return out[:int(limit)]
    finally:
        if own:
            conn.close()


def record_outcome(lesson_id: int, helped: bool, *, now: Optional[float] = None,
                   conn: Optional[sqlite3.Connection] = None) -> str:
    """Count one check. Returns the lesson's status afterwards."""
    own = conn is None
    conn = conn or _connect()
    try:
        now = float(now if now is not None else time.time())
        conn.execute(
            "UPDATE lessons SET checks = checks + 1, helped = helped + ?, harmed = harmed + ?, last_checked = ? "
            "WHERE id = ? AND status = 'active'", (1 if helped else 0, 0 if helped else 1, now, int(lesson_id)))
        row = conn.execute("SELECT checks, helped, harmed, baseline_rate FROM lessons WHERE id = ?", (int(lesson_id),)).fetchone()
        status = "active"
        if row and row[0] >= MIN_CHECKS:
            rate = row[1] / row[0]
            reason = None
            if row[3] is not None and rate <= float(row[3]) + BASELINE_MARGIN:
                reason = f"no better than before the lesson ({rate:.0%} against {float(row[3]):.0%})"
            elif row[2] >= MAX_HARMED and rate < HELP_RATE_TO_KEEP:
                reason = f"did not help: {row[1]} of {row[0]} checks"
            if reason:
                conn.execute("UPDATE lessons SET status = 'retired', retired_reason = ? WHERE id = ?", (reason, int(lesson_id)))
                status = "retired"
        conn.commit()
        _CACHE["at"] = 0.0
        return status
    finally:
        if own:
            conn.close()


def review(*, now: Optional[float] = None, conn: Optional[sqlite3.Connection] = None) -> Dict[str, int]:
    """Retire lessons that expired unconfirmed; renew (once) the ones the checks keep supporting."""
    own = conn is None
    conn = conn or _connect()
    out = {"retired": 0, "renewed": 0}
    try:
        now = float(now if now is not None else time.time())
        for lid, checks, helped, renewals, base in conn.execute(
                "SELECT id, checks, helped, renewals, baseline_rate FROM lessons WHERE status = 'active' AND expires_at <= ?", (now,)).fetchall():
            beats = base is None or helped / max(checks, 1) >= float(base) + 0.15
            if checks >= MIN_CHECKS and helped / checks >= HELP_RATE_TO_RENEW and beats and renewals < 3:
                conn.execute("UPDATE lessons SET expires_at = ?, renewals = renewals + 1 WHERE id = ?",
                             (now + DEFAULT_TTL_DAYS * 86400.0, lid))
                out["renewed"] += 1
            else:
                reason = "expired unconfirmed" if checks < MIN_CHECKS else "expired, not clearly helping"
                conn.execute("UPDATE lessons SET status = 'retired', retired_reason = ? WHERE id = ?", (reason, lid))
                out["retired"] += 1
        conn.commit()
        _CACHE["at"] = 0.0
        return out
    finally:
        if own:
            conn.close()


def observe_action(action: str, ok: bool) -> None:
    """Called when an action finishes: each active lesson for it gets one check."""
    a = str(action or "").upper()
    if not a:
        return
    try:
        if time.time() - _CACHE["at"] > 60.0:
            conn = _connect()
            try:
                _CACHE["actions"] = {r[0] for r in conn.execute("SELECT DISTINCT applies_to FROM lessons WHERE status = 'active'")}
                _CACHE["siblings"] = {a for (s,) in conn.execute("SELECT siblings FROM lessons WHERE status = 'active' AND siblings IS NOT NULL")
                                      for a in json.loads(s or "[]")}
            finally:
                conn.close()
            _CACHE["at"] = time.time()
        if a not in _CACHE["actions"] and a not in _CACHE.get("siblings", set()):
            return
        for lesson in applicable(a, limit=5):
            record_outcome(lesson["id"], bool(ok))
        _record_transfer(a, bool(ok))
    except Exception:
        log.debug("lesson outcome not recorded", exc_info=True)


def _record_transfer(action: str, ok: bool, conn: Optional[sqlite3.Connection] = None) -> None:
    """The same kind of difficulty on a different action: did the lesson's advice hold up there too?"""
    own = conn is None
    conn = conn or _connect()
    try:
        conn.execute("UPDATE lessons SET transfer_checks = transfer_checks + 1, transfer_helped = transfer_helped + ? "
                     "WHERE status = 'active' AND siblings LIKE ?", (1 if ok else 0, f'%"{action}"%'))
        conn.commit()
    finally:
        if own:
            conn.close()


def transfers(lesson_id: int, *, min_checks: int = MIN_CHECKS, conn: Optional[sqlite3.Connection] = None) -> Optional[bool]:
    """True when the lesson held on sibling actions, False when it did not, None while there is too little to say."""
    own = conn is None
    conn = conn or _connect()
    try:
        row = conn.execute("SELECT transfer_checks, transfer_helped FROM lessons WHERE id = ?", (int(lesson_id),)).fetchone()
        if not row or row[0] < min_checks:
            return None
        return row[1] / row[0] >= HELP_RATE_TO_RENEW
    finally:
        if own:
            conn.close()


def brief(action: Optional[str] = None, *, limit: int = 3) -> str:
    """Active lessons as plain lines, or "" when there are none."""
    try:
        rows = applicable(action, limit=limit) if action else []
    except Exception:
        return ""
    lines = [f"- {r['change']} (from: {r['trigger']}; checked {r['checks']}x, helped {r['helped']}x)" for r in rows]
    return "Lessons to apply:\n" + "\n".join(lines) if lines else ""


def from_failure_clusters(*, days: float = 14.0, min_count: int = 3, now: Optional[float] = None) -> List[int]:
    """Lessons from failures that keep happening: same command and error, at least min_count times."""
    made: List[int] = []
    now = float(now if now is not None else time.time())
    try:
        from eli.core.paths import agent_db_path
        src = sqlite3.connect(str(agent_db_path()), timeout=10)
        try:
            rows = src.execute(
                "SELECT error_type, details, occurrence_count, last_seen FROM error_tracking "
                "WHERE COALESCE(last_seen, 0) >= ?", (now - days * 86400.0,)).fetchall()
        finally:
            src.close()
    except Exception:
        return made
    grouped: Dict[tuple, int] = {}
    for error_type, details, count, _seen in rows:
        try:
            action = str(json.loads(details or "{}").get("action") or "").upper()
        except Exception:
            action = ""
        text = str(error_type or "").strip()
        if action and text and "mock" not in text.lower():
            grouped[(action, text)] = grouped.get((action, text), 0) + int(count or 1)
    rows = [(t, a, n, 0) for (a, t), n in sorted(grouped.items(), key=lambda kv: -kv[1])[:10] if n >= int(min_count)]
    for text, action, count, _unused in rows:
        try:
            from eli.runtime.failure_taxonomy import classify_category
            category = classify_category(text, action)
        except Exception:
            category = ""
        scope = scope_from_history(action, days=days)
        siblings = []
        if category:
            try:
                from eli.runtime.failure_taxonomy import classify_category as _cc
                siblings = sorted({a for (a, t) in grouped if a != action and _cc(t, a) == category})
            except Exception:
                log.debug("sibling actions not resolved", exc_info=True)
        base = None
        try:
            from eli.runtime.evidence_ledger import action_reliability
            r = action_reliability(action)
            base = (round(r["p"], 4), r["n"]) if r["n"] >= MIN_CHECKS else None
        except Exception:
            log.debug("baseline unavailable", exc_info=True)
        where = f" when called with {', '.join(scope)}" if scope else ""
        lid = propose(
            action, f"{action} failed with: {text[:120]}", [f"{count} occurrences in the last {int(days)} days"],
            f"Before running {action}{where}, check the cause of: {text[:120]}",
            hypothesis=(f"A {category or 'recurring'} fault" + (f" that shows up only {where.strip()}" if scope else " that shows up regardless of arguments")
                        + f", so a precondition of {action} is not being met."),
            predicted_outcome=f"{action} succeeds more often than its {base[0]:.0%} before this lesson." if base
            else f"{action} stops failing with this error.",
            now=now, category=category, scope=scope, baseline=base,
            siblings=siblings)
        if lid:
            made.append(lid)
    return made


def scope_from_history(action: str, *, days: float = 14.0, min_runs: int = 4) -> List[str]:
    """Argument names that appear in nearly every failed run of an action and almost none of the successful ones.

    That separates "fails whenever it is given X" from "fails whatever it is given", so a lesson is stated for the
    condition it was learned under and not as a rule for the whole action.
    """
    try:
        from eli.runtime.evidence_ledger import _connect as _ledger
        conn = _ledger()
        try:
            rows = conn.execute(
                "SELECT outcome, payload_json FROM runtime_events WHERE event_type = 'executor_action' AND action = ? "
                "AND COALESCE(ts, timestamp, 0) >= ?", (str(action).upper(), time.time() - days * 86400.0)).fetchall()
        finally:
            conn.close()
    except Exception:
        return []
    fail, ok = [], []
    for outcome, payload in rows:
        try:
            keys = set((json.loads(payload).get("args") or {}).keys())
        except Exception:
            continue
        (fail if outcome == "failed" else ok).append(keys)
    if len(fail) < min_runs or len(ok) < min_runs:
        return []
    every = set.intersection(*fail) if fail else set()
    return sorted(k for k in every if sum(k in r for r in ok) / len(ok) <= 0.2)
