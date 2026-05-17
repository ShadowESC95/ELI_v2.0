from __future__ import annotations

import re
import sqlite3
import time
from pathlib import Path
from typing import Any

from eli.runtime.identity_validation import extract_explicit_identity_facts


def _root() -> Path:
    return Path(__file__).resolve().parents[2]


def _user_db() -> Path:
    return _root() / "artifacts" / "db" / "user.sqlite3"


def _clean(value: Any, limit: int = 600) -> str:
    s = "" if value is None else str(value)
    s = s.replace("\n", " ").replace("\r", " ")
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) > limit:
        return s[: limit - 1].rstrip() + "…"
    return s


def _table_exists(cur: sqlite3.Cursor, table: str) -> bool:
    return bool(
        cur.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name=?",
            (table,),
        ).fetchone()
    )


def ensure_profile_tables(db_path: Path | None = None) -> None:
    db = db_path or _user_db()
    db.parent.mkdir(parents=True, exist_ok=True)

    con = sqlite3.connect(str(db))
    cur = con.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_patterns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pattern_type TEXT,
            pattern_data TEXT,
            timestamp REAL,
            ts REAL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS session_summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            user_id TEXT,
            summary TEXT,
            turns_count INTEGER,
            started_at REAL,
            ended_at REAL,
            source TEXT,
            timestamp REAL,
            ts REAL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT,
            category TEXT,
            observation TEXT,
            content TEXT,
            text TEXT,
            details TEXT,
            timestamp REAL,
            ts REAL
        )
        """
    )

    con.commit()
    con.close()


def _insert_user_pattern(
    cur: sqlite3.Cursor,
    pattern_type: str,
    pattern_data: str,
    ts_value: float | None = None,
) -> bool:
    pattern_type = _clean(pattern_type, 120)
    pattern_data = _clean(pattern_data, 900)
    now = float(ts_value or time.time())

    if not pattern_type or not pattern_data:
        return False

    exists = cur.execute(
        """
        SELECT 1 FROM user_patterns
        WHERE lower(COALESCE(pattern_type, '')) = lower(?)
          AND lower(COALESCE(pattern_data, '')) = lower(?)
        LIMIT 1
        """,
        (pattern_type, pattern_data),
    ).fetchone()

    if exists:
        return False

    cur.execute(
        """
        INSERT INTO user_patterns(pattern_type, pattern_data, timestamp, ts)
        VALUES (?, ?, ?, ?)
        """,
        (pattern_type, pattern_data, now, now),
    )
    return True


def extract_patterns_from_text(text: Any) -> list[tuple[str, str]]:
    raw = _clean(text, 1600)
    low = raw.lower()
    out: list[tuple[str, str]] = []

    if not raw:
        return out

    # Identity: explicit declarations only. Broad grammar fragments such as
    # "it is ..." or "or ..." are not identity evidence.
    identity_facts = extract_explicit_identity_facts(raw)
    if identity_facts.get("name"):
        out.append(("identity.name", f"User's name is {identity_facts['name']}."))
    if identity_facts.get("preferred_name"):
        out.append(("identity.preferred_name", f"User prefers to be called {identity_facts['preferred_name']}."))
    if identity_facts.get("nickname"):
        out.append(("identity.nickname", f"User uses {identity_facts['nickname']} as a nickname."))

    # Communication / collaboration preferences.
    if re.search(r"\bin depth\b|\bin-depth\b|\bdetailed\b|\bmeticulous\b|\bthorough\b", low):
        out.append(("preference.detail", "User prefers in-depth, meticulous, thorough responses."))

    if re.search(r"\bno vague descriptions\b|\bno vague\b|\bnot vague\b", low):
        out.append(("preference.style", "User dislikes vague descriptions and wants concrete detail."))

    if re.search(r"\bno bias\b|\bwithout bias\b|\bno bullshit\b|\bbullshit-free\b", low):
        out.append(("preference.style", "User prefers direct, low-bias, bullshit-free analysis."))

    if re.search(r"\bbrutally honest\b|\bchallenge\b|\bcorrect me\b|\btell me.*wrong\b", low):
        out.append(("preference.style", "User wants assumptions challenged and errors corrected directly."))

    if re.search(r"\bgeneric\b|\brepetitive\b|\bshallow\b|\bunhelpful\b|\bfiller\b|\bhr[- ]?speak\b|\bcustomer[- ]?service\b", low):
        out.append(("preference.style", "User rejects generic, repetitive, shallow, customer-service style responses."))

    if re.search(r"\bstubs?\b|\btemplates?\b|\bplaceholder\b|\bboilerplate\b", low):
        out.append(("preference.output_quality", "User rejects stubs, templates, placeholders, and boilerplate as generated output."))

    if re.search(r"\bmore depth\b|\bdeeper\b|\bcharacter\b|\bfull persona\b|\bpersonality\b", low):
        out.append(("preference.persona", "User wants ELI to keep a deeper, more characterful persona while staying technically grounded."))

    if re.search(r"\bfull runtime audit\b|\bfull audit\b|\bdiagnostic\b|\bwhat'?s actually broken\b|\bwhat has changed\b", low):
        out.append(("preference.debugging", "User prefers full diagnostics/audits with explicit broken/missing components."))

    if re.search(r"\bevery step\b|\bstep by step\b", low):
        out.append(("preference.process", "User prefers step-by-step technical explanations."))

    if re.search(r"\bcommands\b|\bbash\b|\bsed\b|\bterminal\b", low):
        out.append(("preference.commands", "User prefers executable terminal/Bash commands for repairs."))

    if re.search(r"\bdrop[- ]?in python\b", low):
        out.append(("preference.commands", "User does not want vague drop-in Python snippets; prefers complete command workflows."))

    # ELI project facts.
    if re.search(r"\beli\b|\bmkxi\b|\bmkix\b|\bjarvis\b", low):
        out.append(("project.eli", "User is actively developing ELI, a local-first assistant/runtime project."))

    if re.search(r"\bcognition pipeline\b|\b12 stage pipeline\b|\borchestrator\b|\bagent bus\b", low):
        out.append(("project.eli.cognition", "User focuses on ELI cognition pipeline/orchestrator correctness."))

    if re.search(r"\bmemory\b.*\bsqlite\b|\buser_patterns\b|\bsession_summaries\b|\brecall\b", low):
        out.append(("project.eli.memory", "User is actively debugging ELI's SQLite-backed memory and recall system."))

    if re.search(r"\bgguf\b|\bmistral\b|\bqwen\b|\bllama[-_ ]?cpp\b|\bn_ctx\b|\bgpu_layers\b", low):
        out.append(("project.eli.runtime", "User is tuning ELI's local GGUF runtime parameters."))

    # Research / physics.
    if re.search(r"\bphysics\b|\bsimulation\b|\blagrangian\b|\bfield\b|\bscalar\b|[Ξχφ]", raw, re.IGNORECASE):
        out.append(("research.physics", "User works on theoretical physics/simulation material involving field frameworks."))

    if re.search(r"\bΞ\b|\bχ\b|\bφ\b|xi|chi|phi", raw, re.IGNORECASE):
        out.append(("research.xi_chi_phi", "User references a Ξ–χ–φ field framework in research/simulation work."))

    # De-duplicate while preserving order.
    seen: set[tuple[str, str]] = set()
    deduped: list[tuple[str, str]] = []
    for item in out:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)

    return deduped


def write_patterns_from_turn(
    user_text: Any,
    db_path: Path | None = None,
    ts_value: float | None = None,
) -> int:
    ensure_profile_tables(db_path)

    db = db_path or _user_db()
    patterns = extract_patterns_from_text(user_text)

    if not patterns:
        return 0

    con = sqlite3.connect(str(db))
    cur = con.cursor()

    inserted = 0
    for ptype, pdata in patterns:
        if _insert_user_pattern(cur, ptype, pdata, ts_value=ts_value):
            inserted += 1

    con.commit()
    con.close()
    return inserted


def backfill_user_patterns(db_path: Path | None = None, limit: int = 2500) -> dict[str, Any]:
    ensure_profile_tables(db_path)

    db = db_path or _user_db()
    con = sqlite3.connect(str(db))
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    scanned = 0
    inserted = 0

    if _table_exists(cur, "conversation_turns"):
        rows = cur.execute(
            """
            SELECT id, role, content, ts, timestamp
            FROM conversation_turns
            WHERE lower(COALESCE(role, '')) = 'user'
            ORDER BY COALESCE(ts, timestamp, 0) ASC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()

        for r in rows:
            scanned += 1
            for ptype, pdata in extract_patterns_from_text(r["content"]):
                if _insert_user_pattern(cur, ptype, pdata, ts_value=r["ts"] or r["timestamp"] or time.time()):
                    inserted += 1

    if _table_exists(cur, "memories"):
        rows = cur.execute(
            """
            SELECT id, text, value, content, tags, kind, source, ts, timestamp
            FROM memories
            WHERE lower(COALESCE(source, '')) = 'user'
               OR lower(COALESCE(tags, '')) LIKE '%identity%'
               OR lower(COALESCE(tags, '')) LIKE '%user%'
            ORDER BY COALESCE(ts, timestamp, 0) ASC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()

        for r in rows:
            scanned += 1
            text = r["text"] or r["value"] or r["content"] or ""
            for ptype, pdata in extract_patterns_from_text(text):
                if _insert_user_pattern(cur, ptype, pdata, ts_value=r["ts"] or r["timestamp"] or time.time()):
                    inserted += 1

    con.commit()

    total = cur.execute("SELECT COUNT(*) FROM user_patterns").fetchone()[0]
    con.close()

    return {
        "db": str(db),
        "scanned": scanned,
        "inserted": inserted,
        "user_patterns_total": total,
    }


def write_session_summary_from_recent(
    db_path: Path | None = None,
    session_id: str | None = None,
    user_id: str | None = None,
    source: str = "runtime_profile_extractor",
    max_turns: int = 40,
) -> dict[str, Any]:
    ensure_profile_tables(db_path)

    db = db_path or _user_db()
    con = sqlite3.connect(str(db))
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    if not _table_exists(cur, "conversation_turns"):
        con.close()
        return {"db": str(db), "inserted": False, "reason": "conversation_turns missing"}

    where = ""
    params: list[Any] = []

    if session_id:
        where = "WHERE session_id = ?"
        params.append(session_id)

    rows = cur.execute(
        f"""
        SELECT id, session_id, user_id, role, content, ts, timestamp
        FROM conversation_turns
        {where}
        ORDER BY COALESCE(ts, timestamp, 0) DESC
        LIMIT ?
        """,
        (*params, int(max_turns)),
    ).fetchall()

    if not rows:
        con.close()
        return {"db": str(db), "inserted": False, "reason": "no turns"}

    rows = list(reversed(rows))
    sid = str(session_id or rows[-1]["session_id"] or "unknown")
    uid = str(user_id or rows[-1]["user_id"] or "unknown")

    user_msgs = [_clean(r["content"], 220) for r in rows if str(r["role"]).lower() == "user"]
    assistant_msgs = [_clean(r["content"], 180) for r in rows if str(r["role"]).lower() == "assistant"]

    pattern_counts: dict[str, int] = {}
    for msg in user_msgs:
        for ptype, _pdata in extract_patterns_from_text(msg):
            pattern_counts[ptype] = pattern_counts.get(ptype, 0) + 1

    topics = sorted(pattern_counts, key=pattern_counts.get, reverse=True)[:8]

    if topics:
        summary = (
            f"Session {sid}: {len(rows)} turns. "
            f"Detected user profile/project topics: {', '.join(topics)}."
        )
    else:
        sample = "; ".join(user_msgs[:4])
        summary = f"Session {sid}: {len(rows)} turns. Recent user prompts: {sample}"

    started = min(float(r["ts"] or r["timestamp"] or time.time()) for r in rows)
    ended = max(float(r["ts"] or r["timestamp"] or time.time()) for r in rows)
    now = time.time()

    exists = cur.execute(
        """
        SELECT 1 FROM session_summaries
        WHERE session_id = ? AND source = ?
        LIMIT 1
        """,
        (sid, source),
    ).fetchone()

    if exists:
        con.close()
        return {"db": str(db), "inserted": False, "reason": "already summarized", "session_id": sid}

    cur.execute(
        """
        INSERT INTO session_summaries(
            session_id, user_id, summary, turns_count, started_at, ended_at, source, timestamp, ts
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (sid, uid, summary, len(rows), started, ended, source, now, now),
    )

    con.commit()
    total = cur.execute("SELECT COUNT(*) FROM session_summaries").fetchone()[0]
    con.close()

    return {
        "db": str(db),
        "inserted": True,
        "session_id": sid,
        "turns_count": len(rows),
        "session_summaries_total": total,
        "summary": summary,
    }


def after_process_hook(engine: Any, user_input: Any, output: Any = None) -> dict[str, Any]:
    db = _user_db()
    ensure_profile_tables(db)

    inserted_patterns = 0
    try:
        inserted_patterns = write_patterns_from_turn(user_input, db_path=db)
    except Exception:
        inserted_patterns = 0

    summary_result: dict[str, Any] = {}
    try:
        sid = str(getattr(engine, "session_id", "") or "")
        uid = str(getattr(engine, "user_id", "") or "")
        summary_result = write_session_summary_from_recent(
            db_path=db,
            session_id=sid or None,
            user_id=uid or None,
            source="runtime_profile_extractor",
            max_turns=30,
        )
    except Exception as e:
        summary_result = {"inserted": False, "reason": repr(e)}

    return {
        "inserted_patterns": inserted_patterns,
        "summary": summary_result,
    }
