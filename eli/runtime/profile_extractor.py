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

    # Belief storage and the corroboration/provenance columns the weighing needs.
    # Before the backfill, so those passes see the migrated shape.
    try:
        from eli.cognition.stance_store import ensure_tables as _ensure_belief
        _ensure_belief(cur)
    except Exception:
        log.debug("belief tables unavailable", exc_info=True)

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


def _supersede_single_valued(cur: sqlite3.Cursor, pattern_type: str,
                            pattern_data: str,
                            provenance: str = "user_passing") -> bool:
    """Weigh a replacement for a single-valued key, and retire the old value only
    if it actually loses.

    This used to delete unconditionally: whoever wrote last won. That is the
    yes-man mechanism sitting in the data layer — it makes ASSERTION equal to
    EVIDENCE, so a passing mention could overwrite something the user had stated
    outright and reaffirmed a dozen times, silently and with no record.

    Now the standing value is weighed against the new one (see
    `eli.cognition.belief`). Returns True when the replacement should proceed.
    False means the standing value held and the CALLER MUST NOT INSERT — an
    unweighed insert would leave both values present, which is worse than either
    outcome.

    Retiring still DELETES rather than flagging, for the original reason: several
    consumers read these rows and a 'superseded' column each would have to honour
    is a filter waiting to be forgotten. What is new is that the retired value is
    written to `belief_revisions` first, so it is recoverable and ELI can say what
    it used to hold and why that changed.
    """
    now = time.time()
    try:
        from eli.cognition.belief import (
            Belief, HOLD, assess_claim,
        )
        from eli.cognition.stance_store import ensure_tables, record_revision
        ensure_tables(cur)
        row = cur.execute(
            "SELECT pattern_data, COALESCE(corroboration, 1), "
            "       COALESCE(provenance, 'user_passing'), "
            "       COALESCE(timestamp, ts, 0) "
            "  FROM user_patterns "
            " WHERE lower(COALESCE(pattern_type,'')) = lower(?) "
            "   AND lower(COALESCE(pattern_data,'')) <> lower(?) "
            " ORDER BY COALESCE(timestamp, ts, 0) DESC LIMIT 1",
            (pattern_type, pattern_data),
        ).fetchone()
        if row:
            standing = Belief(statement=row[0], corroboration=int(row[1] or 1),
                              provenance=row[2], last_seen=float(row[3] or now))
            challenger = Belief(statement=pattern_data, corroboration=1,
                                provenance=provenance, last_seen=now)
            verdict = assess_claim(standing, challenger, now)
            # Refuse only on HOLD. A QUESTION means the evidence genuinely does
            # not settle it, and on a SINGLE-VALUED key there is no third option
            # — something has to be stored. Deferring to the newer statement when
            # nothing distinguishes them is not caving: caving is yielding when
            # you hold the better evidence, which is exactly what HOLD catches.
            # Refusing here instead would resurrect the original defect this key
            # exists to prevent, where a correction left two mutually exclusive
            # values and retrieval order decided which one ELI believed.
            if verdict.action == HOLD:
                log.debug("profile_extractor: keeping %s=%r over %r (%s)",
                          pattern_type, row[0], pattern_data, verdict.action)
                return False
            record_revision(cur, "user_pattern", pattern_type, row[0], pattern_data,
                            reason="; ".join(verdict.reasons),
                            standing_weight=verdict.standing_weight,
                            challenger_weight=verdict.challenger_weight, now=now)
    except Exception:
        # Never block a write on the belief layer. Falling back to the old
        # last-writer-wins is worse than weighing, but far better than losing
        # the correction entirely.
        log.debug("belief assessment unavailable; superseding unweighed",
                  exc_info=True)

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
    return True


def _insert_user_pattern(
    cur: sqlite3.Cursor,
    pattern_type: str,
    pattern_data: str,
    ts_value: float | None = None,
    provenance: str = "user_passing",
) -> bool:
    pattern_type = _clean(pattern_type, 120)
    pattern_data = _clean(pattern_data, 900)
    now = float(ts_value or time.time())

    if not pattern_type or not pattern_data:
        return False

    if pattern_type.lower() in _SINGLE_VALUED_PATTERNS:
        # A refusal means the standing value won. Inserting anyway would leave
        # both values present on a key that is single-valued by definition.
        if not _supersede_single_valued(cur, pattern_type, pattern_data,
                                        provenance=provenance):
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
        # Reaffirmation also CORROBORATES. Without this the belief layer has
        # nothing to weigh with: a fact stated once and a fact stated twenty
        # times looked identically supported, so a passing correction could
        # overturn either. Provenance is upgraded but never downgraded — a
        # passing mention must not weaken something said outright.
        try:
            cur.execute(
                """
                UPDATE user_patterns
                   SET timestamp = ?, ts = ?,
                       corroboration = COALESCE(corroboration, 1) + 1
                WHERE lower(COALESCE(pattern_type, '')) = lower(?)
                  AND lower(COALESCE(pattern_data, '')) = lower(?)
                """,
                (now, now, pattern_type, pattern_data),
            )
        except Exception:
            # Pre-migration database without the column — recency alone.
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
                log.debug("could not refresh %s", pattern_type, exc_info=True)
        try:
            from eli.cognition.belief import PROVENANCE_WEIGHT
            cur.execute(
                "UPDATE user_patterns SET provenance = ? "
                " WHERE lower(COALESCE(pattern_type,'')) = lower(?) "
                "   AND lower(COALESCE(pattern_data,'')) = lower(?) "
                "   AND COALESCE(?, 0) > COALESCE("
                "        (SELECT ? ), 0)",
                (provenance, pattern_type, pattern_data,
                 PROVENANCE_WEIGHT.get(provenance, 0.0),
                 PROVENANCE_WEIGHT.get(provenance, 0.0)),
            )
        except Exception:
            log.debug("could not upgrade provenance", exc_info=True)
        return False

    try:
        cur.execute(
            "INSERT INTO user_patterns(pattern_type, pattern_data, timestamp, ts, "
            "                          corroboration, provenance) "
            "VALUES (?, ?, ?, ?, 1, ?)",
            (pattern_type, pattern_data, now, now, provenance),
        )
    except Exception:
        # Pre-migration database without the belief columns.
        log.debug("insert with provenance failed; using the legacy shape",
                  exc_info=True)
        cur.execute(
            """
            INSERT INTO user_patterns(pattern_type, pattern_data, timestamp, ts)
            VALUES (?, ?, ?, ?)
            """,
            (pattern_type, pattern_data, now, now),
        )

    # Must run on BOTH insert paths. An earlier cut returned straight after the
    # new insert and skipped it, so nothing reached the semantic tier at all.
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


def _evidence(raw: str, match: "re.Match[str] | None", width: int = 120) -> str:
    """The user's own words around a match, for appending to a canned label.

    Every rule below emits a FIXED sentence, which is why hundreds of turns
    collapsed into ten rows: "User prefers in-depth, meticulous, thorough
    responses." is byte-identical whether the user wrote 'be thorough' or three
    paragraphs about how they work, so `_insert_user_pattern`'s dedupe folds them
    all into one. The label is still worth keeping — it is what the persona and
    proactive surfaces read — so the quote is appended rather than replacing it.
    Two different statements now produce two different rows, both traceable to
    what was actually said.
    """
    if match is None:
        return ""
    start = max(0, match.start() - width // 3)
    end = min(len(raw), match.end() + width)
    quote = raw[start:end].strip()
    # Snap to word boundaries so the quote does not start or end mid-word.
    if start > 0 and " " in quote:
        quote = quote.split(" ", 1)[1]
    if end < len(raw) and " " in quote:
        quote = quote.rsplit(" ", 1)[0]
    quote = " ".join(quote.split())
    if len(quote) < 8:
        return ""
    return f' Said: "{quote}"'


def _pref(out: list, raw: str, low: str, pattern: str, ptype: str, label: str) -> None:
    """Emit a preference rule with the user's own phrasing attached."""
    m = re.search(pattern, low)
    if m:
        out.append((ptype, label + _evidence(raw, m)))


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
    _pref(out, raw, low, r"\bin depth\b|\bin-depth\b|\bdetailed\b|\bmeticulous\b|\bthorough\b", "preference.detail",
          "User prefers in-depth, meticulous, thorough responses.")

    _pref(out, raw, low, r"\bno vague descriptions\b|\bno vague\b|\bnot vague\b", "preference.style",
          "User dislikes vague descriptions and wants concrete detail.")

    _pref(out, raw, low, r"\bno bias\b|\bwithout bias\b|\bno bullshit\b|\bbullshit-free\b", "preference.style",
          "User prefers direct, low-bias, bullshit-free analysis.")

    _pref(out, raw, low, r"\bbrutally honest\b|\bchallenge\b|\bcorrect me\b|\btell me.*wrong\b", "preference.style",
          "User wants assumptions challenged and errors corrected directly.")

    _pref(out, raw, low, r"\bgeneric\b|\brepetitive\b|\bshallow\b|\bunhelpful\b|\bfiller\b|\bhr[- ]?speak\b|\bcustomer[- ]?service\b", "preference.style",
          "User rejects generic, repetitive, shallow, customer-service style responses.")

    _pref(out, raw, low, r"\bstubs?\b|\btemplates?\b|\bplaceholder\b|\bboilerplate\b", "preference.output_quality",
          "User rejects stubs, templates, placeholders, and boilerplate as generated output.")

    _pref(out, raw, low, r"\bmore depth\b|\bdeeper\b|\bcharacter\b|\bfull persona\b|\bpersonality\b", "preference.persona",
          "User wants ELI to keep a deeper, more characterful persona while staying technically grounded.")

    _pref(out, raw, low, r"\bfull runtime audit\b|\bfull audit\b|\bdiagnostic\b|\bwhat'?s actually broken\b|\bwhat has changed\b", "preference.debugging",
          "User prefers full diagnostics/audits with explicit broken/missing components.")

    _pref(out, raw, low, r"\bevery step\b|\bstep by step\b", "preference.process",
          "User prefers step-by-step technical explanations.")

    _pref(out, raw, low, r"\bcommands\b|\bbash\b|\bsed\b|\bterminal\b", "preference.commands",
          "User prefers executable terminal/Bash commands for repairs.")

    _pref(out, raw, low, r"\bdrop[- ]?in python\b", "preference.commands",
          "User does not want vague drop-in Python snippets; prefers complete command workflows.")

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
    r"^\s*(SUMMARY|DECISIONS|OPEN\s+THREADS|USER\s+PREFERENCES|CURRENT\s+WORK|USER\s+FACTS)\s*:\s*"
    r"([\s\S]*?)(?=^\s*(?:SUMMARY|DECISIONS|OPEN\s+THREADS|USER\s+PREFERENCES|CURRENT\s+WORK|USER\s+FACTS)\s*:|\Z)",
    re.I | re.M,
)

# A durable fact line -> the pattern type it becomes. Order matters: the first
# match wins, so the more specific verbs are listed before the general ones.
# Every prefix here is one _promote_to_semantic accepts, so a fact captured
# tonight is in the semantic tier and the knowledge graph by morning.
_FACT_ROUTES: tuple[tuple[str, str], ...] = (
    (r"\b(?:is called|goes by|name is|prefers to be called)\b", "identity.name"),
    (r"\b(?:works as|is an? |their role|job title|employed as)\b", "identity.role"),
    (r"\b(?:lives in|based in|is from|located in|timezone)\b", "identity.location"),
    (r"\b(?:studies|researches|research(?:es|ing)?|specialis|specializ|"
     r"phd|thesis|dissertation|field is)\b", "research.field"),
    (r"\b(?:is (?:building|developing|working on)|project|prototype|"
     r"is writing|is designing)\b", "project.named"),
    (r"\b(?:prefers|wants|likes it when|dislikes|hates|expects|always asks)\b",
     "preference.stated"),
    (r"\b(?:is interested in|cares about|enjoys|is a fan of|follows)\b", "interest.explicit"),
)

# A "fact" that is really ELI talking about itself is not a fact about the user.
# Recall already filters ELI's own telemetry at read time; keeping it out of
# user_patterns stops it reaching the semantic tier and the KG in the first place.
_FACT_REJECT = re.compile(
    r"\b(?:eli|the assistant|the model|the system)\b\s+(?:is|was|has|had|will|can|"
    r"logged|recorded|stored|generated|failed|reported)\b|"
    r"\b(?:reflection|telemetry|failure count|token|gpu layers|vram|"
    r"session summary|conversation volume)\b",
    re.I,
)


def _fact_pattern_type(line: str) -> str:
    """Classify a durable user fact into a promotable pattern type.

    Defaults to `identity.fact` rather than dropping the line: an unclassified
    durable fact is still worth remembering, and `identity.` is a prefix
    _promote_to_semantic accepts. It is deliberately NOT one of the
    _SINGLE_VALUED_PATTERNS, so facts accumulate instead of overwriting.
    """
    low = (line or "").lower()
    for pattern, ptype in _FACT_ROUTES:
        if re.search(pattern, low):
            return ptype
    return "identity.fact"


def _route_facts_to_patterns(cur: "sqlite3.Cursor", facts_text: str) -> int:
    """Write each durable fact the model found as its own accumulating pattern.

    This is the width of the funnel. The regex extractor upstream recognises about
    twenty fixed phrasings and most of them emit a CANNED sentence — the same
    string whatever the user actually said — so on a live machine 619 turns and
    441 memories produced only 10 user_patterns, 6 semantic facts and 27 KG
    entities. Everything downstream inherits that.

    The session summariser already reads the whole transcript; it just had nowhere
    to put anything except two single-slot rows (`project.current`,
    `preference.session`) that are deleted and rewritten every session. Facts go
    to accumulating types instead, and `_insert_user_pattern` dedupes them and
    refreshes recency on reaffirmation, so a fact repeated across sessions stays
    fresh rather than duplicating.

    Returns the number of facts written.
    """
    if not _summary_section_meaningful(facts_text):
        return 0
    written = 0
    seen: set[str] = set()
    for raw_line in (facts_text or "").splitlines():
        line = _clean(raw_line, 300).strip().lstrip("-•*0123456789. ").strip()
        # Too short to be a fact, or no letters at all.
        if len(line) < 12 or not re.search(r"[A-Za-z]", line):
            continue
        if _FACT_REJECT.search(line):
            log.debug("profile_extractor: dropped self-referential 'fact': %s", line[:80])
            continue
        key = line.lower()
        if key in seen:
            continue
        seen.add(key)
        try:
            if _insert_user_pattern(cur, _fact_pattern_type(line), line):
                written += 1
        except Exception:
            log.debug("profile_extractor: fact insert failed", exc_info=True)
    return written


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

    # Durable facts accumulate. CURRENT_WORK and USER_PREFERENCES above are both
    # single-slot by design — they answer "what now?" and are rewritten each
    # session — which is exactly why they could never widen the funnel.
    facts = sections.get("USER_FACTS", "")
    if facts:
        n = _route_facts_to_patterns(cur, facts)
        if n:
            log.debug("profile_extractor: %d durable user fact(s) captured", n)


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
            "CURRENT WORK: what the user is actively working on.\n"
            "USER FACTS: durable facts about the USER that would still be true "
            "next month — who they are, what they work on, what they care about. "
            "One per line, in your own words, drawn ONLY from what the USER said "
            "about themselves. Omit anything about ELI, this software, or this "
            "session's mechanics. If the user stated nothing durable, write "
            "'none'.\n\n"
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


def _mark_backfilled(db: Path, session_id: str) -> None:
    """Record that a session has been mined, so a resumed run skips it."""
    try:
        con = sqlite3.connect(str(db))
        try:
            con.execute(
                "INSERT OR REPLACE INTO fact_backfill_log (session_id, ts) VALUES (?, ?)",
                (str(session_id), time.time()),
            )
            con.commit()
        finally:
            con.close()
    except Exception:
        log.debug("could not mark session %s backfilled", session_id, exc_info=True)


def backfill_facts_from_sessions(
    db_path: Path | None = None,
    limit: int | None = None,
    broker: Any = None,
    progress: Any = None,
) -> dict[str, Any]:
    """Mine durable user facts out of conversations that predate fact extraction.

    The live path only runs at session end, so everything said before it existed
    stays unmined. On a real install that is 64 sessions and 353 user turns
    producing **10** `user_patterns` — and because promotion fans out from that
    table, the semantic tier (6 rows) and the knowledge graph inherit the same
    starvation.

    The 59 summaries already on disk cannot simply be re-routed: they were
    written by the older prompt and contain no USER FACTS section at all. The
    sessions have to be re-read.

    So this walks them through the SAME path that works live —
    `write_llm_session_summary`, which builds the transcript, asks the local
    model, and routes the result through `_route_summary_to_profile`. No second
    extractor to keep in step with the first.

    Four properties matter more here than the extraction does:

      * **Never cold-loads.** Same rule `_llm_summarise_session` enforces: if no
        model is resident this returns immediately rather than pulling gigabytes
        off disk to mine history. Mining is never worth a cold load.
      * **Resumable.** Measured against a real 64-session store, the summariser
        makes TWO inference calls per session, so a full history is closer to an
        hour than the half hour a single-call estimate suggests. That cannot be a
        startup task or a modal dialog. Every session considered is written to
        `fact_backfill_log`, so an interrupted run continues instead of
        restarting.
      * **Idempotent.** `_insert_user_pattern` dedupes and refreshes recency on
        reaffirmation, so a repeat pass costs time and changes nothing. That is
        what makes interrupting it safe.
      * **Oldest first.** If it is stopped halfway you have mined the history you
        would otherwise never revisit; recent sessions are covered by the live
        path anyway.

    `progress` is an optional callable(done, total, session_id) for a UI.
    Returns a summary; `reason` explains any early return.
    """
    ensure_profile_tables(db_path)
    db = db_path or _user_db()
    out: dict[str, Any] = {
        "sessions_seen": 0, "sessions_processed": 0, "skipped_done": 0,
        "skipped_thin": 0, "failed": 0, "patterns_before": 0,
        "patterns_after": 0, "reason": "",
    }

    # Gate BEFORE touching anything: a cold load to mine history is never worth it.
    if broker is None:
        try:
            import eli.cognition.gguf_inference as _gi
            if not getattr(_gi, "is_loaded", lambda: False)():
                out["reason"] = "no model resident — load one, then run this again"
                return out
        except Exception:
            out["reason"] = "inference unavailable"
            return out

    con = sqlite3.connect(str(db))
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    try:
        if not _table_exists(cur, "conversation_turns"):
            out["reason"] = "conversation_turns missing"
            return out
        out["patterns_before"] = cur.execute(
            "SELECT COUNT(*) FROM user_patterns").fetchone()[0]

        # Oldest first, and only sessions with enough turns to carry a fact.
        rows = cur.execute(
            """
            SELECT session_id, COUNT(*) AS n, MIN(COALESCE(timestamp, ts, 0)) AS first_ts
              FROM conversation_turns
             WHERE COALESCE(session_id, '') <> ''
             GROUP BY session_id
             ORDER BY first_ts ASC
            """
        ).fetchall()

        # An explicit log, not an inference. The obvious marker — "does the stored
        # summary contain a USER FACTS section" — does not work:
        # write_llm_session_summary persists a PROCESSED summary, not the raw
        # sectioned model output, so that test never matches and every run
        # re-summarised the whole history from scratch.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS fact_backfill_log (
                session_id TEXT PRIMARY KEY,
                ts REAL
            )""")
        con.commit()
        done: set = set()
        try:
            done = {str(r[0]) for r in
                    cur.execute("SELECT session_id FROM fact_backfill_log").fetchall()
                    if r[0]}
        except Exception:
            log.debug("could not read the backfill log", exc_info=True)
    finally:
        con.close()

    out["sessions_seen"] = len(rows)
    todo = [r for r in rows if str(r["session_id"]) not in done]
    out["skipped_done"] = len(rows) - len(todo)
    if limit:
        todo = todo[: int(limit)]

    for i, r in enumerate(todo, 1):
        sid = str(r["session_id"])
        thin = int(r["n"] or 0) < 4        # too short to carry a durable fact
        if not thin:
            try:
                write_llm_session_summary(db_path=db, session_id=sid, broker=broker,
                                          max_turns=60)
                out["sessions_processed"] += 1
            except Exception:
                out["failed"] += 1
                log.debug("backfill: session %s failed", sid, exc_info=True)
        else:
            out["skipped_thin"] += 1

        # Mark it either way: a session too thin to carry a fact is still one
        # this pass has considered, and re-reading it on every future run costs
        # time to reach the same conclusion.
        _mark_backfilled(db, sid)

        # Reported for EVERY session, skips included — a progress bar that never
        # reaches its total because thin sessions were passed over silently reads
        # as a hung job.
        if callable(progress):
            try:
                progress(i, len(todo), sid)
            except Exception:
                pass

    con = sqlite3.connect(str(db))
    try:
        out["patterns_after"] = con.execute(
            "SELECT COUNT(*) FROM user_patterns").fetchone()[0]
    finally:
        con.close()
    out["patterns_added"] = out["patterns_after"] - out["patterns_before"]
    log.info("backfill: %d/%d sessions mined, %d new user_patterns",
             out["sessions_processed"], out["sessions_seen"], out["patterns_added"])
    return out


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
