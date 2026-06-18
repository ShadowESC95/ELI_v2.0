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
    # Canonical user store — the SAME file every other subsystem uses
    # (eli.core.paths honours ELI_USER_DB/ELI_DB_DIR/ELI_DATA_DIR then platformdirs).
    # Previously this hardcoded <repo>/artifacts/db/user.sqlite3, which on an installed
    # package is a DIFFERENT file from paths.user_db_path() — so the User Model + patterns
    # were WRITTEN here but READ from the canonical store (the brief never surfaced), and
    # it wrote into the package/CWD dir. Delegate so writer and reader always agree.
    try:
        from eli.core.paths import user_db_path
        return Path(user_db_path())
    except Exception:
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

    # Continuous User Model — one synthesized row per user_id. The structured JSON
    # columns + free-text dossier are the in-depth/semantic view; `brief` is a
    # pre-rendered block for a fast per-turn direct read (single SELECT, no joins).
    # User-scoped by user_id (never a flat file) so one user's model never bleeds
    # into another's. Evidence stays in user_patterns/memories/KG; this is synthesis.
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_model (
            user_id       TEXT PRIMARY KEY,
            identity      TEXT,
            comms_style   TEXT,
            current_focus TEXT,
            interests     TEXT,
            habits        TEXT,
            goals         TEXT,
            relationship  TEXT,
            dossier       TEXT,
            brief         TEXT,
            sources       TEXT,
            confidence    REAL,
            updated_at    REAL,
            ts            REAL
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
        # Reaffirmation: refresh recency so "last active" / staleness reflect the
        # MOST RECENT mention, not the first. Projects and interests are dynamic —
        # an active one stays fresh, an abandoned one ages out (see staleness
        # filters in persona_updater + personal_memory_clean_response).
        try:
            cur.execute(
                """
                UPDATE user_patterns SET timestamp = ?, ts = ?
                WHERE lower(COALESCE(pattern_type, '')) = lower(?)
                  AND lower(COALESCE(pattern_data, '')) = lower(?)
                """,
                (now, now, pattern_type, pattern_data),
            )
        except Exception:
            pass
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

    # NOTE (2026-06-09 refactor): the hard-coded keyword→canned-phrase "project facts"
    # were REMOVED. They emitted frozen sentences ("User is actively developing ELI…")
    # every session, so the proactive 'active_project' signal never changed — the
    # opposite of a self-aware, dynamic system. ELI's *current work* is now inferred
    # live from the actual conversation (see _route_summary_to_profile, which writes a
    # fresh 'project.current' user_pattern from each session's LLM hand-off summary).

    # Research / technical-science interest (generic — no user-specific frameworks).
    if re.search(r"\bphysics\b|\bchemistry\b|\bbiology\b|\bengineering\b|\bsimulation\b|\bresearch\b|\bexperiment\b", raw, re.IGNORECASE):
        out.append(("research.science", "User works on technical/scientific research material."))

    # Biographical facts from explicit first-person statements (high precision —
    # anchored to "I am/I'm/I study/I work as" so casual chat isn't mis-extracted).
    # These enrich recall beyond response-preferences (identity, role, interests).
    _m = re.search(
        r"\bi(?:'m| am)\s+(?:a|an)\s+("
        r"physicist|engineer|inventor|researcher|scientist|developer|programmer|"
        r"mathematician|academic|professor|lecturer|phd\s*(?:student|candidate)?|"
        r"postdoc|student|founder|author|writer|designer|analyst)\b",
        low,
    )
    if _m:
        _role = _m.group(1).strip()
        _art = "an" if _role[:1].lower() in "aeiou" else "a"
        out.append(("identity.role", f"User is {_art} {_role}."))

    _m = re.search(r"\bi(?:'m| am)\s+(?:really |very |quite |particularly )?interested in\s+([a-z0-9][\w ,/&+'-]{2,70})", low)
    if _m:
        _v = _m.group(1).strip().rstrip(".,;")
        out.append(("interest.explicit", f"User is interested in {_v}."))

    _m = re.search(
        r"\b(?:i study|i'?m studying|i am studying|i research|i'?m researching|"
        r"i am researching|my field is|my research is in|i speciali[sz]e in|"
        r"i work in)\s+([a-z0-9][\w ,/&+'-]{2,70})",
        low,
    )
    if _m:
        _v = _m.group(1).strip().rstrip(".,;")
        out.append(("research.field", f"User studies/researches {_v}."))

    _m = re.search(r"\b(?:remember that|remember,? |please remember)\s+(i\b.{4,180}|my\b.{4,180})", low)
    if _m:
        _v = _m.group(1).strip().rstrip(".,;")
        out.append(("user.explicit_note", f"User asked to remember: {_v}."))

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


_SUMMARY_SECTION_RE = re.compile(
    r"^\s*(SUMMARY|DECISIONS|OPEN\s+THREADS|USER\s+PREFERENCES|CURRENT\s+WORK)\s*:\s*"
    r"([\s\S]*?)(?=^\s*(?:SUMMARY|DECISIONS|OPEN\s+THREADS|USER\s+PREFERENCES|CURRENT\s+WORK)\s*:|\Z)",
    re.I | re.M,
)


def _summary_section_meaningful(s: str) -> bool:
    t = (s or "").strip().lower().strip(" .-•*")
    return bool(t) and t not in (
        "none", "n/a", "na", "none identified", "no current work", "nothing",
        "no preferences", "none made", "no decisions", "no significant decisions",
        "no open threads", "none expressed", "not specified",
    )


def _route_summary_to_profile(cur: "sqlite3.Cursor", llm_summary: str) -> None:
    """Route the DYNAMIC 'CURRENT WORK' / 'USER PREFERENCES' the model inferred from the
    REAL conversation into fresh user_patterns — the replacement for the removed hard-coded
    project facts. Re-derived every session, so the proactive 'active_project' signal tracks
    what the user is ACTUALLY working on now (not a frozen 'developing ELI' literal)."""
    if not llm_summary:
        return
    sections = {m.group(1).upper().replace(" ", "_"): m.group(2).strip()
                for m in _SUMMARY_SECTION_RE.finditer(llm_summary)}
    work = _clean(sections.get("CURRENT_WORK", ""), 300)
    prefs = _clean(sections.get("USER_PREFERENCES", ""), 300)
    if _summary_section_meaningful(work):
        # Keep only the LATEST dynamic project signal — purge the frozen canned ones
        # (incl. legacy 'project.eli*' rows) so the daemon never reads a stale fact.
        try:
            cur.execute(
                "DELETE FROM user_patterns "
                "WHERE pattern_type = 'project.current' OR pattern_type LIKE 'project.eli%'"
            )
        except Exception:
            pass
        _insert_user_pattern(cur, "project.current", work)
    if _summary_section_meaningful(prefs):
        try:
            cur.execute("DELETE FROM user_patterns WHERE pattern_type = 'preference.session'")
        except Exception:
            pass
        _insert_user_pattern(cur, "preference.session", prefs)


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
            # Route the dynamically-inferred CURRENT WORK / USER PREFERENCES into fresh
            # user_patterns so the proactive 'active_project' signal is live, not canned.
            try:
                _route_summary_to_profile(cur, llm_summary)
            except Exception:
                pass
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
        # Consolidate the freshly-routed user_patterns + this session summary into the
        # continuous User Model (one row per user_id). Reuses the resident GGUF broker and
        # degrades to a heuristic dossier on any failure — never blocks the summary write.
        try:
            from eli.runtime.user_model import synthesize_user_model
            synthesize_user_model(user_id=uid, session_summary=str(content or ""),
                                  db_path=db, broker=broker)
        except Exception:
            pass
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
