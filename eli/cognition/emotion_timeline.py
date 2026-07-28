"""Emotion timeline — the durable record of how the USER has been feeling.

`tone_adaptor` decides the emotion ELI *expresses* on the current turn and then
forgets it: the acoustic read lives in a 12-second process-local slot and the
semantic read is recomputed from the last utterance. That is enough to be
*reactive* (shade this reply) and not enough to be *proactive* — with no history
ELI cannot know the user has been short with it for six turns, cannot tell a
sudden dip from someone's ordinary register, and cannot say what it did just
before the mood turned.

This module is that missing memory. Every fused read is appended to
`emotion_events` in user.sqlite3 together with the utterance that produced it and
the action ELI took immediately before, which makes three questions answerable:

  • **What is the trend?**      — sustained states, not single spikes.
  • **Is it unusual for THEM?** — measured against that user's own baseline, so a
                                  naturally reserved person is never read as upset.
  • **What preceded it?**       — the ELI action on the turn the mood turned, which
                                  is what lets ELI ask whether it was something *it* did.

`assess()` returns EVIDENCE, never a phrase. Deciding what to say about a mood is
the model's job — this module's job is to be sure the model is looking at
something real. See `eli/planning/proactive_daemon.py` for the surfacing path.

Governed by ``ELI_EMOTION_MEMORY`` (default on).
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from eli.utils.log import get_logger

log = get_logger(__name__)

# ── Tuning ────────────────────────────────────────────────────────────────────
# A single grumpy sentence is not a mood. These thresholds are what separate a
# spike from a state; they are deliberately conservative because a wrong "you seem
# upset" is far more costly than a missed one.
SUSTAINED_MIN_READS = 3          # reads of one valence before it counts as a state
SUSTAINED_WINDOW = 8             # how many recent reads we look back over
SUSTAINED_WINDOW_HOURS = 6.0     # ...and how far back those reads may be
BASELINE_DAYS = 30               # how much history defines "normal for this user"
BASELINE_MIN_READS = 20          # below this we have no credible baseline
CHECKIN_COOLDOWN_S = 45 * 60.0   # never raise a mood twice inside this window
MIN_CONFIDENCE = 0.45            # ignore reads we do not really believe

# Valence classes. `tone_adaptor` detects the user's emotion; grouping by valence
# is what makes "has been negative for a while" answerable without caring whether
# each individual read was 'angry' or 'irritated'.
_NEGATIVE = {"sad", "angry", "irritated", "confused", "frustrated"}
_POSITIVE = {"happy", "joyful", "ecstatic", "comedic", "playful"}
_NEUTRAL = {"neutral", "calm", "curious", "professional", "street_smart", "deadpan"}


def _knob(key: str, fallback):
    """Live value of a user-tunable (Settings ▸ Cognition ▸ Emotional awareness).

    Read at call time, not import time, so moving a slider takes effect on the next
    turn without a restart. Any failure falls back to the shipped constant, so the
    settings layer can never break emotional awareness.
    """
    try:
        from eli.core.cognition_tunables import get_tunable
        v = get_tunable(key)
        if v is not None:
            return v
    except Exception:
        log.debug("emotion_timeline: tunable %s unavailable", key, exc_info=True)
    return fallback


def enabled() -> bool:
    """Off via the env kill-switch OR the Settings master toggle."""
    if os.environ.get("ELI_EMOTION_MEMORY", "1").strip().lower() in {
            "0", "false", "no", "off"}:
        return False
    return bool(int(_knob("cog.emotion_enabled", 1)))


def valence_of(emotion: str) -> str:
    """'negative' | 'positive' | 'neutral' for an emotion name."""
    e = str(emotion or "").strip().lower()
    if e in _NEGATIVE:
        return "negative"
    if e in _POSITIVE:
        return "positive"
    return "neutral"


# ── Storage ───────────────────────────────────────────────────────────────────
def _db_path() -> Path:
    try:
        from eli.core.paths import user_db_path
        return Path(user_db_path())
    except Exception:
        root = Path(os.environ.get("ELI_ROOT", Path(__file__).resolve().parents[2]))
        p = root / "artifacts" / "db" / "user.sqlite3"
        p.parent.mkdir(parents=True, exist_ok=True)
        return p


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        from eli.core.sqlite_util import apply_pragmas
        apply_pragmas(conn, db_path=str(path))
    except Exception:
        log.debug("emotion_timeline: pragma setup skipped", exc_info=True)
    return conn


_SCHEMA = """
CREATE TABLE IF NOT EXISTS emotion_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    user_id TEXT DEFAULT '',
    session_id TEXT DEFAULT '',
    detected TEXT NOT NULL,           -- what the USER seemed to feel
    expressed TEXT DEFAULT '',        -- the register ELI answered in
    valence TEXT DEFAULT 'neutral',
    confidence REAL DEFAULT 0.0,
    source TEXT DEFAULT '',           -- voice | text | fused | override
    arousal REAL,
    user_text TEXT DEFAULT '',        -- the utterance that produced the read
    eli_prior_action TEXT DEFAULT ''  -- what ELI did on the PRECEDING turn
)
"""


def _ensure(conn: sqlite3.Connection) -> None:
    conn.execute(_SCHEMA)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_emotion_events_ts ON emotion_events(ts)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_emotion_events_user_ts ON emotion_events(user_id, ts)")


# Dedupe guard: `_build_enhanced_system` can run more than once for a single user
# turn (compact vs full system prompt), and a double-written read would inflate
# every "sustained" count. Keyed on the utterance so a genuine repeat still counts.
_last_key: str = ""
_last_key_ts: float = 0.0
_DEDUPE_WINDOW_S = 20.0


def record(detected: str,
           expressed: str = "",
           confidence: float = 0.0,
           source: str = "",
           *,
           user_text: str = "",
           user_id: str = "",
           session_id: str = "",
           arousal: Optional[float] = None,
           eli_prior_action: str = "") -> bool:
    """Append one emotional read. Returns True if a row was written.

    Neutral and low-confidence reads are stored too — a baseline built only from
    the turns someone was upset would make everyone look upset.
    """
    global _last_key, _last_key_ts
    if not enabled():
        return False
    detected = str(detected or "").strip().lower()
    if not detected:
        return False
    try:
        key = f"{detected}|{(user_text or '')[:160]}"
        now = time.time()
        if key == _last_key and (now - _last_key_ts) < _DEDUPE_WINDOW_S:
            return False
        conn = _connect()
        try:
            _ensure(conn)
            conn.execute(
                "INSERT INTO emotion_events (ts, user_id, session_id, detected, expressed, "
                "valence, confidence, source, arousal, user_text, eli_prior_action) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (now, str(user_id or ""), str(session_id or ""), detected,
                 str(expressed or ""), valence_of(detected), float(confidence or 0.0),
                 str(source or ""), (float(arousal) if arousal is not None else None),
                 str(user_text or "")[:500], str(eli_prior_action or "")[:200]),
            )
            conn.commit()
        finally:
            conn.close()
        _last_key, _last_key_ts = key, now
        return True
    except Exception:
        log.debug("emotion_timeline: record failed", exc_info=True)
        return False


def recent(limit: int = 40, user_id: str = "",
           within_hours: Optional[float] = None) -> List[Dict[str, Any]]:
    """Most-recent-first reads, optionally scoped to a user and a time window."""
    if not enabled():
        return []
    try:
        conn = _connect()
        try:
            _ensure(conn)
            sql = "SELECT * FROM emotion_events WHERE 1=1"
            params: List[Any] = []
            if user_id:
                sql += " AND user_id = ?"
                params.append(str(user_id))
            if within_hours:
                sql += " AND ts >= ?"
                params.append(time.time() - float(within_hours) * 3600.0)
            # id breaks ts ties: several reads inside one second must still come
            # back newest-first or run-length counting silently mis-orders.
            sql += " ORDER BY ts DESC, id DESC LIMIT ?"
            params.append(int(limit))
            return [dict(r) for r in conn.execute(sql, params).fetchall()]
        finally:
            conn.close()
    except Exception:
        log.debug("emotion_timeline: recent failed", exc_info=True)
        return []


def baseline(user_id: str = "", days: Optional[int] = None) -> Dict[str, Any]:
    """This user's own emotional norm, so deviation means something.

    Returns {reads, dominant, negative_share, positive_share, credible}. `credible`
    is False until there is enough history — callers must not treat an absent
    baseline as "everything is normal".
    """
    days = int(days if days is not None else _knob("cog.emotion_baseline_days", BASELINE_DAYS))
    empty = {"reads": 0, "dominant": "", "negative_share": 0.0,
             "positive_share": 0.0, "credible": False}
    if not enabled():
        return empty
    try:
        conn = _connect()
        try:
            _ensure(conn)
            since = time.time() - float(days) * 86400.0
            sql = "SELECT valence, detected FROM emotion_events WHERE ts >= ?"
            params: List[Any] = [since]
            if user_id:
                sql += " AND user_id = ?"
                params.append(str(user_id))
            rows = conn.execute(sql, params).fetchall()
        finally:
            conn.close()
        total = len(rows)
        if not total:
            return empty
        neg = sum(1 for r in rows if r["valence"] == "negative")
        pos = sum(1 for r in rows if r["valence"] == "positive")
        counts: Dict[str, int] = {}
        for r in rows:
            counts[r["detected"]] = counts.get(r["detected"], 0) + 1
        dominant = max(counts.items(), key=lambda kv: kv[1])[0] if counts else ""
        return {
            "reads": total,
            "dominant": dominant,
            "negative_share": round(neg / total, 3),
            "positive_share": round(pos / total, 3),
            "credible": total >= BASELINE_MIN_READS,
        }
    except Exception:
        log.debug("emotion_timeline: baseline failed", exc_info=True)
        return empty


# ── Check-in cooldown ─────────────────────────────────────────────────────────
def _cooldown_path() -> Path:
    try:
        from eli.core.paths import get_paths
        base = Path(get_paths().artifacts_dir) / "runtime"
    except Exception:
        base = Path(__file__).resolve().parents[2] / "artifacts" / "runtime"
    base.mkdir(parents=True, exist_ok=True)
    return base / "emotion_checkin.json"


def last_checkin() -> Dict[str, Any]:
    try:
        p = _cooldown_path()
        if p.exists():
            return dict(json.loads(p.read_text(encoding="utf-8")) or {})
    except Exception:
        log.debug("emotion_timeline: cooldown read failed", exc_info=True)
    return {}


def note_checkin(valence: str, detected: str = "") -> None:
    """Record that ELI just raised the user's mood — starts the cooldown."""
    try:
        _cooldown_path().write_text(
            json.dumps({"ts": time.time(), "valence": valence, "detected": detected}),
            encoding="utf-8")
    except Exception:
        log.debug("emotion_timeline: cooldown write failed", exc_info=True)


def checkin_allowed(valence: str) -> bool:
    """False while inside the cooldown for this valence — ELI must not nag."""
    prev = last_checkin()
    if not prev:
        return True
    cooldown = float(_knob("cog.emotion_cooldown_min", CHECKIN_COOLDOWN_S / 60.0)) * 60.0
    if (time.time() - float(prev.get("ts") or 0.0)) < cooldown:
        return False
    return True


# ── The assessment the model reasons over ─────────────────────────────────────
def assess(user_id: str = "", session_id: str = "") -> Dict[str, Any]:
    """Measure the user's current emotional state and whether it is worth raising.

    Returns evidence only — no phrasing. Keys:
      state            'negative' | 'positive' | 'neutral' | ''
      dominant         the most common emotion in the sustained run
      run_length       how many consecutive reads share the state
      confidence       mean confidence across the run
      transition       {from, to} when the state just changed, else {}
      trigger_action   ELI's action on the turn the state turned (may be '')
      trigger_text     the utterance where it turned (may be '')
      baseline         this user's norm (see baseline())
      unusual          True when the run departs from that norm
      should_checkin   True when a proactive check-in is warranted RIGHT NOW
      reason           why should_checkin is what it is (for logs/telemetry)
    """
    out: Dict[str, Any] = {
        "state": "", "dominant": "", "run_length": 0, "confidence": 0.0,
        "transition": {}, "trigger_action": "", "trigger_text": "",
        "baseline": baseline(user_id), "unusual": False,
        "should_checkin": False, "reason": "",
    }
    if not enabled():
        out["reason"] = "disabled"
        return out

    window_h = float(_knob("cog.emotion_window_hours", SUSTAINED_WINDOW_HOURS))
    min_reads = int(_knob("cog.emotion_run_length", SUSTAINED_MIN_READS))
    min_conf = float(_knob("cog.emotion_confidence_pct", int(MIN_CONFIDENCE * 100))) / 100.0
    rows = recent(limit=SUSTAINED_WINDOW * 2, user_id=user_id, within_hours=window_h)
    if not rows:
        out["reason"] = "no reads in window"
        return out

    window = rows[:SUSTAINED_WINDOW]
    head_valence = window[0]["valence"]

    # How far back does the current valence run unbroken?
    run: List[Dict[str, Any]] = []
    for r in window:
        if r["valence"] != head_valence:
            break
        run.append(r)

    out["state"] = head_valence
    out["run_length"] = len(run)
    confident = [r for r in run if float(r["confidence"] or 0.0) >= min_conf]
    out["confidence"] = round(
        sum(float(r["confidence"] or 0.0) for r in run) / len(run), 3) if run else 0.0

    counts: Dict[str, int] = {}
    for r in run:
        counts[r["detected"]] = counts.get(r["detected"], 0) + 1
    out["dominant"] = max(counts.items(), key=lambda kv: kv[1])[0] if counts else ""

    # The turn the mood changed: first read AFTER the run, plus what ELI did there.
    if len(rows) > len(run):
        prior = rows[len(run)]
        if prior["valence"] != head_valence:
            out["transition"] = {"from": prior["valence"], "to": head_valence}
            edge = run[-1] if run else None
            if edge is not None:
                out["trigger_action"] = str(edge["eli_prior_action"] or "")
                out["trigger_text"] = str(edge["user_text"] or "")[:200]

    # Unusual FOR THIS USER — not unusual in the abstract.
    base = out["baseline"]
    if base.get("credible"):
        if head_valence == "negative" and base["negative_share"] < 0.5:
            out["unusual"] = True
        elif head_valence == "positive" and base["positive_share"] < 0.5:
            out["unusual"] = True

    # Should ELI raise it? Every gate has to pass.
    if head_valence == "neutral":
        out["reason"] = "neutral state — nothing to raise"
    elif len(run) < min_reads:
        out["reason"] = f"run of {len(run)} < {min_reads} — a spike, not a state"
    elif len(confident) < min_reads:
        out["reason"] = f"only {len(confident)} reads above confidence {min_conf:.2f}"
    elif not checkin_allowed(head_valence):
        out["reason"] = "inside check-in cooldown"
    else:
        out["should_checkin"] = True
        out["reason"] = (f"sustained {head_valence} across {len(run)} reads "
                         f"(dominant: {out['dominant']})")
    return out


def evidence_block(user_id: str = "", session_id: str = "") -> str:
    """The assessment as a compact block for the model to reason over.

    Deliberately states the measurement and hands the decision to the model: it
    chooses whether and how to raise it, so the wording is ELI's, never a
    template. Empty when there is nothing worth saying.
    """
    a = assess(user_id=user_id, session_id=session_id)
    if not a.get("should_checkin"):
        return ""
    bits = [f"The user has read as {a['dominant']} across the last {a['run_length']} "
            f"exchanges (mean confidence {a['confidence']:.2f})"]
    if a.get("unusual"):
        b = a["baseline"]
        bits.append(f"which is unusual for them — normally they read "
                    f"{b['dominant']} over {b['reads']} prior reads")
    if a.get("transition"):
        bits.append(f"the shift was {a['transition']['from']} → {a['transition']['to']}")
    if a.get("trigger_action"):
        bits.append(f"immediately after you ran {a['trigger_action']}")
    measurement = "; ".join(bits) + "."
    return (
        "[Emotional state — measured, not inferred from this message alone: "
        f"{measurement} If it fits naturally, acknowledge it in your own words and "
        "offer something useful — checking whether something you did landed badly if "
        "they seem negative, or building on it if they seem positive. Judge for "
        "yourself whether raising it helps right now; if it would interrupt or feel "
        "intrusive, say nothing about it and just answer. Never quote these numbers "
        "or mention that you measured anything.]"
    )


def trend_line(user_id: str = "", limit: int = 6) -> str:
    """One-line recent trend for the system prompt — context, not a prompt to act.

    This runs on every turn (unlike `evidence_block`, which only fires when a
    check-in is warranted) so ELI always has continuity on how the conversation
    has been feeling.
    """
    rows = recent(limit=limit, user_id=user_id,
                  within_hours=float(_knob("cog.emotion_window_hours", SUSTAINED_WINDOW_HOURS)))
    if len(rows) < 2:
        return ""
    seq = [str(r["detected"]) for r in reversed(rows)]
    if len(set(seq)) == 1 and seq[0] == "neutral":
        return ""
    return f"[Recent emotional read of the user, oldest→newest: {' → '.join(seq)}.]"
