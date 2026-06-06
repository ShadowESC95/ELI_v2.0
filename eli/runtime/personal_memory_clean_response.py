from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[2]
USER_DB = ROOT / "artifacts" / "db" / "user.sqlite3"
AGENT_DB = ROOT / "artifacts" / "db" / "agent.sqlite3"

_POISON_PATTERNS = [
    r"Reflection \(24h\)",
    r"conversation volume",
    r"HackerNews",
    r"Reddit/",
    r"news synthesis",
    r"SYNTHESISE_FROM_DETERMINISTIC_EVIDENCE",
    r"raw memory-count dump",
    r"You are right: that should not have been",
    r"Memory\s+truth\s+report",
    r"Runtime\s+truth\s+report",
    r"Import\s+audit",
    r"Last-response\s+truth\s+report",
    r"Control-action\s+evidence\s+failure",
    r"sqlite3 schema",
    r"columns:",
    r"rows:",
    r"generated script",
    r"artifact_generated",
    r"answer in ELI",
    r"treat it as ground truth",
]

_FACT_PATTERNS = [
    r"\bUser prefers\b.{3,220}",
    r"\bUser prefers to be called\b.{1,80}",
    r"\bUser wants\b.{3,220}",
    r"\bUser dislikes\b.{3,220}",
    r"\bUser values\b.{3,220}",
    r"\bUser works on\b.{3,220}",
    r"\bUser is working on\b.{3,220}",
    r"\bUser is developing\b.{3,220}",
    r"\bUser uses\b.{3,220}",
    r"\bUser is using\b.{3,220}",
    # Biographical / interest / project / research facts were being DROPPED:
    # the extractor emits "User focuses on…", "is actively debugging…",
    # "references a Ξ–χ–φ field framework…", but none matched the narrow set
    # above, so recall only ever surfaced response-preferences. Surface the
    # full curated fact set from user_patterns (a reset-aware SQLite table).
    r"\bUser focuses on\b.{3,220}",
    r"\bUser is focused on\b.{3,220}",
    r"\bUser is actively\b.{3,220}",
    r"\bUser actively\b.{3,220}",
    r"\bUser references\b.{3,220}",
    r"\bUser is interested in\b.{3,220}",
    r"\bUser is into\b.{3,220}",
    r"\bUser studies\b.{3,220}",
    r"\bUser researches\b.{3,220}",
    r"\bUser is researching\b.{3,220}",
    r"\bUser is building\b.{3,220}",
    r"\bUser is tuning\b.{3,220}",
    r"\bUser rejects\b.{3,220}",
    r"\bUser does not want\b.{3,220}",
    r"\bUser is a\b.{3,220}",
    r"\bUser is an\b.{3,220}",
    r"\bUser has\b.{3,220}",
    r"\bUser asked to remember\b.{3,220}",
]


def _connect(db: Path) -> sqlite3.Connection | None:
    if not db.exists():
        return None
    try:
        con = sqlite3.connect(str(db))
        con.row_factory = sqlite3.Row
        return con
    except Exception:
        return None


def _table_exists(con: sqlite3.Connection, table: str) -> bool:
    try:
        row = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
            (table,),
        ).fetchone()
        return row is not None
    except Exception:
        return False


def _columns(con: sqlite3.Connection, table: str) -> list[str]:
    try:
        return [r[1] for r in con.execute(f'PRAGMA table_info("{table}")')]
    except Exception:
        return []


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple)):
        value = json.dumps(value, ensure_ascii=False)
    text = str(value)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _is_poison(text: str) -> bool:
    low = text.lower()
    if not text or len(text) < 8:
        return True
    if len(text) > 900:
        return True
    return any(re.search(p, text, re.IGNORECASE) for p in _POISON_PATTERNS)


def _extract_fact(text: str) -> str | None:
    text = _clean_text(text)
    if _is_poison(text):
        return None

    for pat in _FACT_PATTERNS:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            fact = _clean_text(m.group(0))
            fact = fact.rstrip(" .;") + "."
            if not _is_poison(fact):
                return fact

    # Allow short direct identity/preference facts (any name), but reject generic logs.
    if re.search(r"\b(preferred name|name)\b\s*[:=]\s*[A-Za-z][A-Za-z0-9 _.\-]{1,40}", text, re.IGNORECASE):
        return text.rstrip(" .;") + "."

    return None


def _iter_table_texts(con: sqlite3.Connection, table: str, limit: int = 80) -> Iterable[str]:
    if not _table_exists(con, table):
        return []

    cols = _columns(con, table)
    preferred = [
        "text", "value", "content", "observation", "details", "pattern_data",
        "summary", "name", "title", "description", "tags",
    ]
    usable = [c for c in preferred if c in cols]
    if not usable:
        return []

    select_cols = ", ".join(f'"{c}"' for c in usable)
    try:
        rows = con.execute(
            f'SELECT {select_cols} FROM "{table}" ORDER BY rowid DESC LIMIT ?',
            (limit,),
        ).fetchall()
    except Exception:
        return []

    out: list[str] = []
    for row in rows:
        for c in usable:
            out.append(_clean_text(row[c]))
    return out


# Volatile fact types age out of recall once not reaffirmed within this window
# (projects/interests change). Stable types (preferences, name, research
# framework, role) are never aged out.
_VOLATILE_PREFIXES = ("project.", "interest.", "app_cmd")
_VOLATILE_STALE_SECONDS = 30 * 86400


def _iter_user_patterns_fresh(con: sqlite3.Connection, limit: int = 200) -> list[str]:
    """user_patterns rows as clean facts, MOST RECENT first, with stale volatile
    facts (projects/interests not reaffirmed within the window) dropped so recall
    reflects current focus rather than everything ever mentioned."""
    if not _table_exists(con, "user_patterns"):
        return []
    import time as _t
    cutoff = _t.time() - _VOLATILE_STALE_SECONDS
    try:
        rows = con.execute(
            "SELECT pattern_type, pattern_data, COALESCE(ts, timestamp, 0) "
            "FROM user_patterns ORDER BY COALESCE(ts, timestamp, id) DESC LIMIT ?",
            (limit,),
        ).fetchall()
    except Exception:
        return []
    out: list[str] = []
    for ptype, pdata, pts in rows:
        ptype = str(ptype or "")
        text = _clean_text(pdata)
        if not text:
            continue
        if any(ptype.startswith(p) for p in _VOLATILE_PREFIXES) and float(pts or 0) < cutoff:
            continue  # stale volatile fact — project/interest no longer current
        out.append(text)
    return out


def _collect_facts() -> tuple[list[str], dict[str, int]]:
    facts: list[str] = []
    counts: dict[str, int] = {}

    for db_label, db in [("user_db", USER_DB), ("agent_db", AGENT_DB)]:
        con = _connect(db)
        if con is None:
            counts[f"{db_label}:missing"] = 1
            continue

        for table in [
            "memories",
            "user_patterns",
            "observations",
            "habits",
            "habit_rules",
            "improvements",
        ]:
            if not _table_exists(con, table):
                counts[f"{db_label}.{table}"] = 0
                continue

            try:
                n = con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            except Exception:
                n = 0

            counts[f"{db_label}.{table}"] = int(n)

            # user_patterns rows are curated facts already; iterate them
            # MOST-RECENT-first with stale volatile facts dropped (dynamic
            # projects/interests). Other tables use the generic iterator.
            texts = (
                _iter_user_patterns_fresh(con)
                if table == "user_patterns"
                else _iter_table_texts(con, table)
            )
            for text in texts:
                fact = _extract_fact(text)
                if fact and fact not in facts:
                    facts.append(fact)

        con.close()

    try:
        from eli.core.cognition_tunables import get_tunable as _cog_get
        _cap = _cog_get("cog.personal_facts_max")
    except Exception:
        _cap = 40
    return facts[:_cap], counts


def build_clean_personal_memory_response(user_input: str = "", mode_label: str = "") -> str:
    facts, counts = _collect_facts()

    durable_total = sum(
        v for k, v in counts.items()
        if k.endswith(".memories")
        or k.endswith(".user_patterns")
        or k.endswith(".observations")
        or k.endswith(".habits")
        or k.endswith(".habit_rules")
        or k.endswith(".improvements")
    )

    lines: list[str] = []

    lines.append("Personal memory evidence report")
    lines.append("")
    lines.append(f"- Durable personal-memory rows currently visible: {durable_total}")
    lines.append(f"- User DB: {USER_DB}")
    lines.append(f"- Agent DB: {AGENT_DB}")
    lines.append("- Excluded from this answer: conversation archives, runtime truth dumps, news cache, reflection spam, generated scripts, schema dumps, prompt echoes, and quarantine folders.")
    lines.append("")

    if not facts:
        lines.append("I do not currently have clean durable personal-memory facts to report from the active memory tables.")
        lines.append("")
        lines.append("That is expected after a fresh reset. If I still answer with old claims about you after this patch, the source is not clean SQLite memory; it is coming from static runtime/profile files, archived conversation JSON, persona overlays, or hard-coded response surfaces.")
        return "\n".join(lines)

    lines.append("Clean facts found:")
    for fact in facts:
        lines.append(f"- {fact}")

    return "\n".join(lines)


__all__ = ["build_clean_personal_memory_response"]
