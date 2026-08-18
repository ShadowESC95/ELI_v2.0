"""Is this row ELI's own bookkeeping, or evidence about the user?

One question, asked in four places, that had four different answers.

Three times in two days the same defect shipped: ELI's own generated records
re-entered a path meant for evidence about the user, and ELI reported them back
as fact.

  * reflection telemetry was stored under a kind/source chosen to dodge the
    recall filter, so 94% of everything ELI could recall about itself was its own
    failure counts — and a greeting came back "I'm a patch job, a walking
    glitch";
  * the insight synthesiser was handed ten rows of "Proactive daemon started",
    asked to reflect on its own recent activity, and answered the question it was
    given, every 30 minutes, all night;
  * the proactive daemon counted words from its own event log and reported
    "afternoon (x11)" as the operator's foremost interest.

Each was fixed on its own, in its own module, with its own mechanism — a source
tuple here, a category set there, tag substrings in a third place, a stopword
list in a fourth. Nothing connected them, so the fourth instance was a matter of
time: any new reader that queries a store for "what do I know" inherits the bug
by default, because the default is to see everything.

This module is the choke point. It owns the vocabulary of ELI's own record-
keeping and answers the question in whatever form the caller needs — a Python
predicate for row filtering, a SQL fragment for queries. Call sites do not carry
private copies; `tests/test_self_provenance_is_the_choke_point.py` asserts that.

Adding a new kind of generated record means adding it HERE, once, and every
reader inherits it.

Deliberately NOT one flat set: the substrates differ (a memory has kind/source/
tags, an observation has category/text) and so do the exclusions. `eli_world`
autonomy notes stay recallable as memories while `world_autonomy` observations
are not reflection material — that asymmetry is intentional and is recorded
below rather than lost in a merge.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Sequence, Tuple

# ── memories ───────────────────────────────────────────────────────────────
# Kinds that are ELI's own output rather than something learned about the user.
MEMORY_KINDS: frozenset = frozenset({
    "assistant_insight", "episodic", "reflection",
})

# Sources that only ever write generated records. `eli_reflection` covers both
# reflection writers; on a live machine it accounted for 242 of the 257 memories
# that were reaching recall, every one of them a statistic (Conversation volume,
# Top topics, Recent issues, User correction signals, User model focus, Repeated
# actions, App usage) and none a fact about anyone.
#
# `eli_world` is intentionally absent: autonomy notes describe something that
# actually happened and remain recallable.
MEMORY_SOURCES: frozenset = frozenset({
    "orchestrator", "eli_reflection",
})

# Tag substrings, for rows that are reflections by their tags while carrying a
# generic kind.
MEMORY_TAG_MARKERS: Tuple[str, ...] = (
    "reflection", "assistant_insight", "session_summary",
)

# A recalled memory longer than this is a transcript blob, not a fact.
MEMORY_MAX_CHARS = 1500

# ── memory rows scanned in bulk (word counting, topic extraction) ───────────
# Broader than MEMORY_TAG_MARKERS: when COUNTING words rather than recalling a
# fact, every auto-generated row must be skipped, including news and briefings
# whose text is real prose but is not the user speaking.
AUTO_TAG_MARKERS: Tuple[str, ...] = (
    "auto", "insight", "reflection", "proactive", "news", "briefing",
)

# ── observations ───────────────────────────────────────────────────────────
# Categories written by ELI's own loops. Measured on a live machine:
# agent.sqlite3 held 220 observations, 104 `proactive_pattern_tick` and 104
# `runtime`; the ten most recent rows in user.sqlite3 were "Proactive daemon
# started" repeated.
OBSERVATION_CATEGORIES: frozenset = frozenset({
    "proactive_pattern_tick", "runtime", "world_autonomy", "system",
})

# Openings that identify a bookkeeping row whatever it is filed under.
OBSERVATION_TEXT_PREFIXES: Tuple[str, ...] = (
    "proactive daemon started", "proactive daemon stopped", "pattern_summary",
    "persona auto-overlay cleaned", "[world_suggestion]", "[auto] world awareness",
    "daemon initialized", "habit scheduler started", "self-improvement loop started",
)

# ── event labels ───────────────────────────────────────────────────────────
# Internal/meta actions are ELI's own plumbing, never a "pattern" worth
# reporting to a human.
META_ACTIONS: frozenset = frozenset({
    "CHAT", "NOOP", "CHECK_JOB", "BACKGROUND_JOBS", "HABIT_RUN",
    "MORNING_REPORT", "DATE", "TIME", "SELF_REPORT", "RUNTIME_AUDIT",
    "GUI_RUNTIME_AUDIT", "MEMORY_STATUS", "MEMORY_RECALL", "SELF_ANALYZE",
})


def _text_of(row: Any, *keys: str) -> str:
    row = row or {}
    for k in keys:
        v = row.get(k) if isinstance(row, dict) else getattr(row, k, None)
        if v:
            return str(v).strip()
    return ""


def _field(row: Any, key: str) -> str:
    row = row or {}
    v = row.get(key) if isinstance(row, dict) else getattr(row, key, None)
    return str(v or "").strip().lower()


def is_bookkeeping_observation(row: Any) -> bool:
    """True when an observation row is ELI's own record-keeping.

    Used by anything that treats observations as material to reason FROM.
    """
    if _field(row, "category") in OBSERVATION_CATEGORIES:
        return True
    if _field(row, "source") in OBSERVATION_CATEGORIES:
        return True
    low = _text_of(row, "observation", "content", "text", "details").lower()
    if any(low.startswith(p) for p in OBSERVATION_TEXT_PREFIXES):
        return True
    # A serialised pattern tick is machine bookkeeping however it is filed.
    if low.startswith("{") and '"patterns"' in low:
        return True
    return False


def observation_text(row: Any) -> str:
    """The row's text, or '' when it is ELI's own bookkeeping."""
    if is_bookkeeping_observation(row):
        return ""
    return _text_of(row, "observation", "content", "text", "details")


def is_bookkeeping_memory(row: Any) -> bool:
    """True when a memory row is ELI's own generated record.

    The Python mirror of `memory_exclusion_sql` — for readers that already hold
    rows rather than building a query.
    """
    if _field(row, "kind") in MEMORY_KINDS:
        return True
    if _field(row, "source") in MEMORY_SOURCES:
        return True
    tags = _field(row, "tags")
    if any(m in tags for m in MEMORY_TAG_MARKERS):
        return True
    return False


def has_auto_tag(tags: Any) -> bool:
    """True for any auto-generated row, when counting rather than recalling."""
    low = str(tags or "").lower()
    return any(m in low for m in AUTO_TAG_MARKERS)


def is_meta_action(label: Any) -> bool:
    """True for ELI's own plumbing actions."""
    return str(label or "").upper().strip() in META_ACTIONS


def memory_exclusion_sql(
    cols: Iterable[str],
    alias: str = "",
) -> Tuple[str, List[str]]:
    """SQL fragment excluding ELI's own records from a memories query.

    Returns ``(sql, params)`` where `sql` is a chain of ``AND ...`` conditions
    ready to append to a WHERE clause. `alias` is the table alias including its
    dot (``"m."``) or ``""`` for an unaliased query — the two forms were
    previously written out twice by hand and had to be kept in step manually.

    Columns absent from the schema degrade to a constant so the fragment is
    valid against older databases.
    """
    cols = set(cols or ())
    a = alias or ""
    kind_col = f"COALESCE({a}kind, '')" if "kind" in cols else "''"
    source_col = f"COALESCE({a}source, '')" if "source" in cols else "''"
    tags_col = f"LOWER(COALESCE({a}tags, ''))" if "tags" in cols else "''"

    kinds = sorted(MEMORY_KINDS)
    sources = sorted(MEMORY_SOURCES)
    parts = [
        f"AND {kind_col} NOT IN ({', '.join('?' * len(kinds))}) ",
        f"AND {source_col} NOT IN ({', '.join('?' * len(sources))}) ",
    ]
    for marker in MEMORY_TAG_MARKERS:
        parts.append(f"AND {tags_col} NOT LIKE '%{marker}%' ")
    parts.append(
        f"AND LENGTH(COALESCE({a}text, {a}content, '')) <= {int(MEMORY_MAX_CHARS)}"
    )
    return "".join(parts), list(kinds) + list(sources)


# ── retention ──────────────────────────────────────────────────────────────
# Bookkeeping observations are pure churn: the daemon appends one per tick
# forever. They are filtered from every reasoning path above, so their only
# remaining cost is unbounded growth in the store. Cap them; leave genuine
# observations a generous ceiling.
OBSERVATION_RETENTION_BOOKKEEPING = 250
OBSERVATION_RETENTION_DEFAULT = 5000


def observation_retention_limit(category: Any) -> int:
    """Rows to keep for a category."""
    if str(category or "").strip().lower() in OBSERVATION_CATEGORIES:
        return OBSERVATION_RETENTION_BOOKKEEPING
    return OBSERVATION_RETENTION_DEFAULT
