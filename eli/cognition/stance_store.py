"""Persistence for beliefs — ELI's own positions, and the record of revisions.

`eli.cognition.belief` decides; this remembers. Two things live here, and the
second is the one that makes the first worth having.

**Stances.** What ELI holds, as distinct from what it knows about the user. In a
live transcript ELI argued one position on machine consciousness for four hours,
was cornered, and conceded — a genuinely good exchange. But all of it happened
inside a single context window. Reopen the subject tomorrow and there is nothing
to reopen: no record that a position was ever held, argued, or abandoned, so ELI
could contradict itself the next morning with equal confidence and never know.
A stance that does not survive the session that formed it is a mood.

**Revisions.** An append-only record of what was superseded and why.
`_supersede_single_valued` DELETES the row it replaces, deliberately — several
consumers read those tables and a 'superseded' column each would have to honour
is a filter waiting to be forgotten. That reasoning is sound, but it means the
previous value vanishes without trace. Recording the revision separately keeps
the consumers simple AND lets ELI say "I had you as a physicist until you
corrected me in March" — which is the only way a wrong revision is ever noticed.
"""
from __future__ import annotations

import re
import sqlite3
import time
from typing import Any, Dict, List, Optional

from eli.cognition.belief import Belief
from eli.utils.log import get_logger

log = get_logger(__name__)


def ensure_tables(cur: sqlite3.Cursor) -> None:
    """Create the belief tables and add the columns weighting needs.

    `user_patterns` has no corroboration column, so until now there was nothing
    to weigh a claim WITH — every row looked equally supported regardless of
    whether it had been said once or twenty times. The ALTERs are additive and
    each is tried separately, so an older database upgrades in place and a
    column that already exists is not an error.
    """
    cur.execute("""
        CREATE TABLE IF NOT EXISTS eli_stances (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT NOT NULL,
            position TEXT NOT NULL,
            provenance TEXT DEFAULT 'inferred',
            corroboration INTEGER DEFAULT 1,
            confidence REAL DEFAULT 0.8,
            first_held REAL,
            last_held REAL,
            superseded_by TEXT,
            revised_at REAL,
            revision_reason TEXT
        )""")
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_stances_topic ON eli_stances(lower(topic))")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS belief_revisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT,
            topic TEXT,
            old_value TEXT,
            new_value TEXT,
            reason TEXT,
            standing_weight REAL,
            challenger_weight REAL,
            ts REAL
        )""")
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_revisions_topic ON belief_revisions(lower(topic))")
    for stmt in (
        "ALTER TABLE user_patterns ADD COLUMN corroboration INTEGER DEFAULT 1",
        "ALTER TABLE user_patterns ADD COLUMN provenance TEXT DEFAULT 'user_passing'",
    ):
        try:
            cur.execute(stmt)
        except Exception:
            pass  # already present on an existing install


# ── ELI's own stances ─────────────────────────────────────────────────────────

def _norm(topic: str) -> str:
    return re.sub(r"\s+", " ", str(topic or "").strip().lower())[:200]


# How much of the smaller topic must be shared before two turns count as the
# same subject. Exact string equality does not survive natural rewording — the
# same argument phrased twice yields overlapping but unequal word sets — and
# a stance nobody can find again is a stance that does not exist.
TOPIC_MATCH = 0.6

# Positions are longer and more specific than topics, so the bar is higher — but
# it cannot be equality. ELI restates a position in its own words each time it is
# challenged, so exact matching meant reinforcement essentially never fired and
# every rephrasing looked like a NEW position on a topic already held, which
# record_stance then declined. The result was corroboration stuck at 1 no matter
# how long a line was defended — and corroboration is what the weighing runs on.
POSITION_MATCH = 0.75


def _same_position(a: str, b: str) -> bool:
    """Whether two statements are the same position, allowing for rewording."""
    na, nb = _norm(a), _norm(b)
    if na == nb:
        return True
    # Negation is not a rewording: "I am conscious" and "I am not conscious"
    # share nearly every word and are opposites.
    neg = re.compile(r"\b(?:not|never|no|cannot|can't|don't|isn't|aren't)\b")
    if bool(neg.search(na)) != bool(neg.search(nb)):
        return False
    return _overlap(na, nb) >= POSITION_MATCH


def _overlap(a: str, b: str) -> float:
    """Containment, not Jaccard: a short follow-up ('alive, own decisions')
    revisits a long opening turn, and Jaccard would score that pairing low for
    no reason other than length."""
    sa, sb = set(a.split()), set(b.split())
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / min(len(sa), len(sb))


def _find_topic(cur: sqlite3.Cursor, topic: str) -> Optional[str]:
    """The stored topic key this one is about, if any."""
    t = _norm(topic)
    if not t:
        return None
    rows = cur.execute(
        "SELECT DISTINCT topic FROM eli_stances WHERE superseded_by IS NULL"
    ).fetchall()
    best, score = None, 0.0
    for (candidate,) in rows:
        o = _overlap(t, candidate or "")
        if o > score:
            best, score = candidate, o
    return best if score >= TOPIC_MATCH else None


def get_stance(cur: sqlite3.Cursor, topic: str) -> Optional[Belief]:
    """The position ELI currently holds on a topic, if any."""
    key = _find_topic(cur, topic) or _norm(topic)
    row = cur.execute(
        "SELECT position, provenance, corroboration, confidence, first_held, "
        "       last_held, superseded_by, revised_at, revision_reason "
        "  FROM eli_stances "
        " WHERE lower(topic) = ? AND superseded_by IS NULL "
        " ORDER BY COALESCE(last_held, 0) DESC LIMIT 1",
        (key,),
    ).fetchone()
    if not row:
        return None
    now = time.time()
    return Belief(
        statement=row[0], provenance=row[1] or "inferred",
        corroboration=int(row[2] or 1), confidence=float(row[3] or 0.8),
        first_seen=float(row[4] or now), last_seen=float(row[5] or now),
        superseded_by=row[6], revised_at=row[7], revision_reason=row[8] or "",
    )


def record_stance(cur: sqlite3.Cursor, topic: str, position: str,
                  provenance: str = "inferred", now: Optional[float] = None) -> bool:
    """Hold a position, or reinforce it if it is the one already held.

    Arguing the same line again strengthens it — which is what makes a stance
    defended over an hour weigh more than one asserted once in passing.
    """
    topic_n, position = _norm(topic), str(position or "").strip()
    if not topic_n or not position:
        return False
    now = float(now or time.time())
    # Reuse the key an earlier turn on this subject established, so a reworded
    # follow-up reinforces the stance instead of starting a rival one.
    topic_n = _find_topic(cur, topic_n) or topic_n
    existing = cur.execute(
        "SELECT id, position, corroboration FROM eli_stances "
        " WHERE lower(topic) = ? AND superseded_by IS NULL LIMIT 1",
        (topic_n,),
    ).fetchone()
    if existing and _same_position(str(existing[1]), position):
        cur.execute(
            "UPDATE eli_stances SET corroboration = ?, last_held = ?, "
            "       confidence = MIN(1.0, COALESCE(confidence, 0.8) + 0.03) "
            " WHERE id = ?",
            (int(existing[2] or 1) + 1, now, existing[0]),
        )
        return True
    if existing:
        # A different position on a topic already held is a revision, not a new
        # stance. Callers should go through revise_stance so it is weighed.
        return False
    cur.execute(
        "INSERT INTO eli_stances (topic, position, provenance, corroboration, "
        "                         confidence, first_held, last_held) "
        "VALUES (?, ?, ?, 1, 0.8, ?, ?)",
        (topic_n, position, provenance, now, now),
    )
    return True


def revise_stance(cur: sqlite3.Cursor, topic: str, new_position: str,
                  reason: str = "", now: Optional[float] = None) -> bool:
    """Change position, keeping the old one and why it was abandoned."""
    topic_n = _norm(topic)
    now = float(now or time.time())
    topic_n = _find_topic(cur, topic_n) or topic_n
    row = cur.execute(
        "SELECT id, position FROM eli_stances "
        " WHERE lower(topic) = ? AND superseded_by IS NULL LIMIT 1",
        (topic_n,),
    ).fetchone()
    if row:
        cur.execute(
            "UPDATE eli_stances SET superseded_by = ?, revised_at = ?, "
            "       revision_reason = ? WHERE id = ?",
            (new_position, now, reason or "Outweighed by better evidence.", row[0]),
        )
        record_revision(cur, "stance", topic_n, row[1], new_position, reason, now=now)
    cur.execute(
        "INSERT INTO eli_stances (topic, position, provenance, corroboration, "
        "                         confidence, first_held, last_held) "
        "VALUES (?, ?, 'user_explicit', 1, 0.8, ?, ?)",
        (topic_n, str(new_position).strip(), now, now),
    )
    return True


def stance_history(cur: sqlite3.Cursor, topic: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Every position ELI has held on a topic, newest first."""
    rows = cur.execute(
        "SELECT position, first_held, last_held, superseded_by, revised_at, "
        "       revision_reason FROM eli_stances "
        " WHERE lower(topic) = ? ORDER BY COALESCE(first_held, 0) DESC LIMIT ?",
        (_norm(topic), int(limit)),
    ).fetchall()
    return [{
        "position": r[0], "first_held": r[1], "last_held": r[2],
        "superseded_by": r[3], "revised_at": r[4], "revision_reason": r[5] or "",
        "current": r[3] is None,
    } for r in rows]


# ── the revision record ───────────────────────────────────────────────────────

def record_revision(cur: sqlite3.Cursor, kind: str, topic: str, old_value: str,
                    new_value: str, reason: str = "",
                    standing_weight: float = 0.0, challenger_weight: float = 0.0,
                    now: Optional[float] = None) -> None:
    """Append what changed. Never updated, never deleted."""
    try:
        cur.execute(
            "INSERT INTO belief_revisions (kind, topic, old_value, new_value, "
            "  reason, standing_weight, challenger_weight, ts) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (kind, _norm(topic), str(old_value or "")[:900], str(new_value or "")[:900],
             str(reason or "")[:500], float(standing_weight), float(challenger_weight),
             float(now or time.time())),
        )
    except Exception:
        log.debug("could not record belief revision", exc_info=True)


def revisions_for(cur: sqlite3.Cursor, topic: str, limit: int = 10) -> List[Dict[str, Any]]:
    rows = cur.execute(
        "SELECT kind, old_value, new_value, reason, ts FROM belief_revisions "
        " WHERE lower(topic) = ? ORDER BY COALESCE(ts, 0) DESC LIMIT ?",
        (_norm(topic), int(limit)),
    ).fetchall()
    return [{"kind": r[0], "old": r[1], "new": r[2], "reason": r[3], "ts": r[4]}
            for r in rows]


__all__ = [
    "ensure_tables", "get_stance", "record_stance", "revise_stance",
    "stance_history", "record_revision", "revisions_for",
]
