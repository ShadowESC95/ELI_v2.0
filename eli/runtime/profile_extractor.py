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
            content TEXT,
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


def _build_transcript(rows: list[Any], max_chars: int = 6000) -> str:
    """Render conversation_turns rows (chronological) into a compact transcript.
    Keeps the most recent tail when over budget — the end of a session carries
    the most continuity value."""
    lines: list[str] = []
    for r in rows:
        role = "User" if str(r["role"]).lower() == "user" else "ELI"
        txt = _clean(r["content"], 400)
        if txt:
            lines.append(f"{role}: {txt}")
    transcript = "\n".join(lines)
    if len(transcript) > max_chars:
        transcript = "…\n" + transcript[-max_chars:]
    return transcript


def _llm_summarise_session(transcript: str, broker: Any = None) -> str:
    """In-depth, 100%-local session summary via the already-loaded GGUF (no
    network). Returns "" on ANY failure so the caller falls back to the
    heuristic topic summary — this must never block or break shutdown."""
    if not transcript.strip():
        return ""
    try:
        # Never COLD-LOAD a model just to summarise (e.g. closing the GUI without
        # ever loading one) — only summarise with an already-resident model.
        if broker is None:
            try:
                import eli.cognition.gguf_inference as _gi
                if not getattr(_gi, "is_loaded", lambda: False)():
                    return ""
            except Exception:
                return ""
            from eli.cognition.inference_broker import get_inference_broker
            broker = get_inference_broker()
        if broker is None or not broker.gguf_ready:
            return ""
        system = (
            "You are writing a concise hand-off note about a FINISHED conversation "
            "between the user and ELI, for ELI to read at the start of the next "
            "session. Be concrete and factual. Do NOT invent anything that is not "
            "in the transcript. No preamble, no sign-off."
        )
        prompt = (
            "Summarise this conversation for continuity. Use exactly these "
            "sections; omit a section if it is empty. Keep each to 1-4 short "
            "bullets:\n"
            "SUMMARY: 2-3 sentences on what happened and what matters next.\n"
            "DECISIONS: concrete decisions that were made.\n"
            "OPEN THREADS: unfinished work or agreed next steps.\n"
            "USER PREFERENCES: how the user wants things done.\n"
            "CURRENT WORK: what the user is actively working on.\n\n"
            f"TRANSCRIPT:\n{transcript}"
        )
        out = (broker.infer(prompt, system=system, max_tokens=420,
                            temperature=0.3) or "").strip()
        # Reject degenerate output (a lone '-', whitespace, no letters).
        if len(out) < 20 or not re.search(r"[A-Za-z]", out):
            return ""
        return out
    except Exception:
        return ""


def write_llm_session_summary(
    db_path: Path | None = None,
    session_id: str | None = None,
    user_id: str | None = None,
    max_turns: int = 60,
    broker: Any = None,
) -> dict[str, Any]:
    """SESSION-END hand-off: generate an in-depth summary of the FULL session and
    UPSERT it into session_summaries (source='session_end'). 100% local — uses
    the loaded GGUF via the broker. Falls back to a heuristic topic summary when
    the broker isn't ready/offline or returns nothing usable. Idempotent: a
    second call for the same session replaces the prior end-of-session row.

    Unlike write_session_summary_from_recent (which writes once, early, from the
    first turn), this is called at shutdown so it sees the whole conversation."""
    ensure_profile_tables(db_path)
    db = db_path or _user_db()
    con = sqlite3.connect(str(db))
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    try:
        if not _table_exists(cur, "conversation_turns"):
            return {"inserted": False, "reason": "conversation_turns missing"}

        where, params = "", []
        if session_id:
            where = "WHERE session_id = ?"
            params.append(session_id)
        rows = cur.execute(
            f"""
            SELECT session_id, user_id, role, content, ts, timestamp
            FROM conversation_turns
            {where}
            ORDER BY COALESCE(ts, timestamp, 0) DESC
            LIMIT ?
            """,
            (*params, int(max_turns)),
        ).fetchall()
        if not rows:
            return {"inserted": False, "reason": "no turns"}

        rows = list(reversed(rows))
        sid = str(session_id or rows[-1]["session_id"] or "unknown")
        uid = str(user_id or rows[-1]["user_id"] or "unknown")
        started = min(float(r["ts"] or r["timestamp"] or time.time()) for r in rows)
        ended = max(float(r["ts"] or r["timestamp"] or time.time()) for r in rows)
        now = time.time()

        transcript = _build_transcript(rows)
        llm_summary = _llm_summarise_session(transcript, broker)
        if llm_summary:
            # First line (the SUMMARY:) is the short headline; full sectioned
            # text goes in `content` for deep recall.
            _head = llm_summary.splitlines()[0]
            _head = re.sub(r"^\s*SUMMARY:\s*", "", _head, flags=re.I).strip()
            summary = _clean(_head or llm_summary, 600)
            content = llm_summary
            source = "session_end"
        else:
            user_msgs = [_clean(r["content"], 220) for r in rows
                         if str(r["role"]).lower() == "user"]
            pattern_counts: dict[str, int] = {}
            for msg in user_msgs:
                for ptype, _pd in extract_patterns_from_text(msg):
                    pattern_counts[ptype] = pattern_counts.get(ptype, 0) + 1
            topics = sorted(pattern_counts, key=pattern_counts.get, reverse=True)[:8]
            if topics:
                summary = f"Session {sid}: {len(rows)} turns. Topics: {', '.join(topics)}."
            else:
                summary = (f"Session {sid}: {len(rows)} turns. "
                           f"Recent: {'; '.join(user_msgs[:4])}")
            content = summary
            source = "session_end_heuristic"

        # UPSERT — replace any prior end-of-session summary for this session so
        # re-running shutdown doesn't accumulate duplicates.
        cur.execute(
            "DELETE FROM session_summaries WHERE session_id = ? "
            "AND source IN ('session_end', 'session_end_heuristic')",
            (sid,),
        )
        cur.execute(
            """
            INSERT INTO session_summaries(
                session_id, user_id, summary, content, turns_count,
                started_at, ended_at, source, timestamp, ts
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (sid, uid, summary, content, len(rows), started, ended, source, now, now),
        )
        con.commit()
        return {
            "inserted": True,
            "session_id": sid,
            "source": source,
            "turns_count": len(rows),
            "llm": bool(llm_summary),
            "summary": summary,
        }
    finally:
        con.close()


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
