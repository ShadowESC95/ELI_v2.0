from __future__ import annotations

import re
import sqlite3
import time
from pathlib import Path
from typing import Any

from eli.runtime.identity_validation import extract_explicit_identity_facts
from eli.utils.log import get_logger

log = get_logger(__name__)


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

    # The semantic tier: durable user facts. Four readers already depend on it —
    # recall injects these FIRST on identity questions with a +0.5 weight boost,
    # and two status surfaces count them into memory_entries / processed_memories.
    # Nothing ever wrote it: the only writer, MemorySystem.store_semantic(), had
    # zero callers in the entire repo, so the table was never created and every
    # read threw "no such table: semantic" (visible as a suppressed traceback on
    # each grounded-evidence build). Created here, alongside the patterns table
    # it is populated from, so the schema exists from first boot.
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS semantic (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            fact TEXT,
            tags TEXT,
            confidence REAL DEFAULT 0.8,
            created_at REAL
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

    backfill_semantic_from_patterns(cur)
    reconcile_single_valued_patterns(cur)

    con.commit()
    con.close()


def _scrub_onboarding_snapshot(cur: sqlite3.Cursor, stale_values: list) -> None:
    """Drop the onboarding baseline row when it embeds a value we just retired.

    ``_baseline_report`` writes one composite memory (kind='identity',
    source='onboarding_interview') that concatenates the same four answers held
    individually in user_patterns. It is never rewritten, so once a single-valued
    answer is corrected the snapshot is a duplicate that disagrees with the
    canonical row — and being in memories_fts, it is the copy recall is most
    likely to surface. The canonical rows survive; only the stale composite goes.
    """
    for value in stale_values:
        core = (value or "").strip().rstrip(".")
        # Match on a distinctive middle chunk: the snapshot joins sentences, so
        # the stored value appears inside it rather than as the whole field.
        if len(core) < 12:
            continue
        try:
            cur.execute(
                """
                DELETE FROM memories
                 WHERE lower(COALESCE(source,'')) = 'onboarding_interview'
                   AND instr(lower(COALESCE(text,'')), lower(?)) > 0
                """,
                (core,),
            )
        except Exception:
            log.debug("could not scrub onboarding snapshot", exc_info=True)


def reconcile_single_valued_patterns(cur: sqlite3.Cursor) -> int:
    """Collapse pre-existing duplicates of a single-valued key to the newest.

    The write path now supersedes on insert, but databases written before that
    already carry the contradictions — on the machine this was diagnosed on,
    preference.style held two mutually exclusive values simultaneously. Newest
    wins, because for a single-valued field a later answer is a correction.

    Idempotent, and a no-op on a clean database, so it is safe to run on every
    ensure_profile_tables().
    """
    removed = 0
    for ptype in sorted(_SINGLE_VALUED_PATTERNS):
        try:
            rows = cur.execute(
                """
                SELECT rowid, pattern_data FROM user_patterns
                 WHERE lower(COALESCE(pattern_type,'')) = lower(?)
                 ORDER BY COALESCE(timestamp, ts, 0) DESC, rowid DESC
                """,
                (ptype,),
            ).fetchall()
        except Exception:
            log.debug("reconcile: could not read %s", ptype, exc_info=True)
            continue
        if len(rows) < 2:
            continue
        keep_value = rows[0][1]
        stale = [r[0] for r in rows[1:]]
        stale_values = [r[1] for r in rows[1:]]
        try:
            cur.executemany(
                "DELETE FROM user_patterns WHERE rowid = ?", [(r,) for r in stale]
            )
            _supersede_single_valued(cur, ptype, keep_value)
            _scrub_onboarding_snapshot(cur, stale_values)
            removed += len(stale)
            log.info(
                "profile: %s had %d competing values; kept the newest (%s)",
                ptype, len(rows), str(keep_value)[:80],
            )
        except Exception:
            log.debug("reconcile: could not collapse %s", ptype, exc_info=True)
    return removed


def backfill_semantic_from_patterns(cur: sqlite3.Cursor) -> int:
    """Seed the semantic tier from user_patterns already on disk.

    The tier only started being written in 2.1.87, so an existing install has a
    populated user_patterns table and an empty semantic one — every durable fact
    ELI had already learned stayed invisible to the identity-recall path that
    reads semantic first.

    Runs only when semantic is EMPTY, which makes it a one-shot: afterwards the
    extractor keeps it current, and a user who deliberately clears the tier does
    not get it silently refilled from history on the next start.

    Promotion goes through _promote_to_semantic, so the durable/transient filter
    and the dedupe are the ones the live path uses — not a second copy that could
    drift away from it.
    """
    try:
        if not _table_exists(cur, "semantic") or not _table_exists(cur, "user_patterns"):
            return 0
        existing = cur.execute("SELECT COUNT(*) FROM semantic").fetchone()
        if existing and int(existing[0] or 0) > 0:
            return 0
        rows = cur.execute(
            "SELECT pattern_type, pattern_data, COALESCE(ts, timestamp, 0) "
            "FROM user_patterns ORDER BY COALESCE(ts, timestamp, 0) ASC"
        ).fetchall()
    except Exception:
        log.debug("profile_extractor: semantic backfill query failed", exc_info=True)
        return 0

    promoted = 0
    for ptype, pdata, ts_value in rows:
        try:
            if _promote_to_semantic(cur, str(ptype or ""), str(pdata or ""),
                                    float(ts_value or time.time())):
                promoted += 1
        except Exception:
            log.debug("profile_extractor: semantic backfill row failed", exc_info=True)
    if promoted:
        log.info("profile_extractor: seeded %d durable fact(s) into the semantic "
                 "tier from existing user_patterns", promoted)
    return promoted


# Profile keys that describe ONE thing about the user. A person has one role,
# one preferred answer style, one primary goal — so a later answer about any of
# them is a CORRECTION of the earlier one, not an additional fact.
#
# The dedupe below keys on (pattern_type, pattern_data), i.e. the value is part
# of the key, which is right for the open-ended kinds (interests, projects: a
# second interest is a second fact) and wrong for these. Correcting a single-
# valued field wrote a SECOND row and both survived, so ELI held mutually
# exclusive answers to the same question and which one surfaced depended on
# retrieval order. Observed live: preference.style carried two competing values
# at once, and identity.role disagreed with the role stated elsewhere.
_SINGLE_VALUED_PATTERNS = frozenset({
    "identity.name",
    "identity.role",
    "preference.style",
    "goal.primary",
})


def _supersede_single_valued(cur: sqlite3.Cursor, pattern_type: str, pattern_data: str) -> None:
    """Retire earlier values of a single-valued key so the correction wins.

    Deletes rather than flags: these rows are read by several independent
    consumers (persona_updater, the personal-memory report, user_info_builder)
    and a 'superseded' column every one of them would have to honour is a
    filter waiting to be forgotten. The semantic mirror is cleared too, or the
    stale value simply comes back from there.
    """
    try:
        cur.execute(
            """
            DELETE FROM user_patterns
             WHERE lower(COALESCE(pattern_type,'')) = lower(?)
               AND lower(COALESCE(pattern_data,'')) <> lower(?)
            """,
            (pattern_type, pattern_data),
        )
    except Exception:
        log.debug("could not retire earlier %s rows", pattern_type, exc_info=True)
    try:
        # _promote_to_semantic stores the key inside tags as
        # "semantic,user_fact,<pattern_type>" — there is no dedicated column.
        cur.execute(
            "DELETE FROM semantic "
            " WHERE ',' || lower(COALESCE(tags,'')) || ',' LIKE ? "
            "   AND lower(COALESCE(fact,'')) <> lower(?)",
            (f"%,{pattern_type.lower()},%", pattern_data),
        )
    except Exception:
        log.debug("could not retire earlier semantic %s rows", pattern_type, exc_info=True)


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

    if pattern_type.lower() in _SINGLE_VALUED_PATTERNS:
        _supersede_single_valued(cur, pattern_type, pattern_data)

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
    _promote_to_semantic(cur, pattern_type, pattern_data, now)
    return True


# Which pattern kinds are durable facts ABOUT THE USER rather than transient
# session state. Only these are promoted: the semantic tier is injected ahead of
# ordinary recall on identity questions, so filling it with per-session chatter
# would push real facts down the list it exists to top.
_SEMANTIC_PATTERN_PREFIXES = ("identity.", "preference.", "project.", "research.", "interest.")
_SEMANTIC_PATTERN_EXCLUDE = ("preference.session",)


def _promote_to_semantic(
    cur: sqlite3.Cursor,
    pattern_type: str,
    pattern_data: str,
    ts_value: float,
) -> bool:
    """Record a newly-learned durable user fact in the semantic tier.

    Called only when _insert_user_pattern actually inserted (it returns False for
    a reaffirmation), so this inherits that dedupe rather than repeating it — and
    it checks the semantic table too, since the two can diverge on an existing
    install whose user_patterns predate this tier being written at all.
    """
    ptype = (pattern_type or "").strip().lower()
    if not ptype.startswith(_SEMANTIC_PATTERN_PREFIXES):
        return False
    if ptype.startswith(_SEMANTIC_PATTERN_EXCLUDE):
        return False
    fact = _clean(pattern_data, 900)
    if not fact:
        return False
    try:
        if not _table_exists(cur, "semantic"):
            return False
        already = cur.execute(
            "SELECT 1 FROM semantic WHERE lower(COALESCE(fact,'')) = lower(?) LIMIT 1",
            (fact,),
        ).fetchone()
        if already:
            return False
        cur.execute(
            "INSERT INTO semantic (user_id, fact, tags, confidence, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("default", fact, f"semantic,user_fact,{ptype}", 0.8, float(ts_value)),
        )
        return True
    except Exception:
        log.debug("profile_extractor: semantic promotion failed", exc_info=True)
        return False


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
