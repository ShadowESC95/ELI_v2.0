"""
Reflection engine — analyses memories, conversations, and patterns to extract insights.
Uses unified memory system. Stores reflections back into memory for future context.
"""
from __future__ import annotations

import time
from collections import Counter
from typing import Dict, Any, List, Optional
from eli.memory import get_memory
from eli.utils.log import get_logger

log = get_logger(__name__)


def _already_stored(mem, text: str) -> bool:
    """True when this exact reflection text is already in the store.

    The previous check asked ``recall_memory("reflection", limit=5)`` whether the
    new text appeared among the five rows it returned. That is a relevance query,
    not an existence query: once the store held a hundred reflections the five it
    chose were almost never the one being written, the check passed, and the row
    was appended again. A live machine accumulated 135 reflection rows, 34 of them
    exact duplicates — six identical copies of one of them — which then dominated
    retrieval by sheer count.

    An exact match on the text column answers the question that was actually
    being asked. Falls back to the old behaviour only if the table cannot be
    queried directly, so a schema change degrades to "store it" rather than
    silently dropping reflections.
    """
    text = str(text or "").strip()
    if not text:
        return True
    try:
        import sqlite3

        path = getattr(mem, "db_path", None)
        if not path:
            return False
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
        try:
            cols = {r[1] for r in con.execute("PRAGMA table_info(memories)")}
            targets = [c for c in ("text", "content") if c in cols]
            if not targets:
                return False
            where = " OR ".join(f"{c} = ?" for c in targets)
            row = con.execute(
                f"SELECT 1 FROM memories WHERE {where} LIMIT 1", [text] * len(targets)
            ).fetchone()
            return row is not None
        finally:
            con.close()
    except Exception:
        log.debug("reflection: duplicate check failed", exc_info=True)
        return False



# Canonical topic-noise vocabulary. Shared, because it was NOT: the proactive
# daemon carried its own ~180-word list that never received the fixes this one
# did, and on a live overnight run it reported the user's "Current focus areas"
# as `afternoon (x11), doing (x10), today (x10), memory (x9), world (x7)` —
# four of those five are in this set and would have been dropped.
TOPIC_STOPWORDS = frozenset({
            "i", "me", "my", "the", "a", "an", "is", "was", "it", "to", "do",
            "you", "your", "and", "or", "of", "in", "on", "for", "what", "how",
            "can", "that", "this", "with", "not", "are", "have", "has", "be",
            # high-frequency conversational filler — never a meaningful topic
            "about", "just", "know", "like", "really", "there", "here", "they",
            "them", "then", "than", "some", "any", "get", "got", "one", "out",
            "now", "but", "so", "we", "us", "our", "dont", "cant", "yeah", "okay",
            "good", "morning", "hey", "eli", "thanks", "thank", "please", "going",
            "fine", "been", "were", "will", "would", "could", "should", "also",
            "very", "much", "more", "most", "into", "over", "from", "when", "who",
            "why", "which", "because", "while", "said", "say", "says", "tell",
            "told", "ask", "asked", "seeing", "want", "need", "make", "made",
            "using", "use", "used", "lately", "stuff", "things", "thing", "your",
            "yours", "still", "back", "thats", "whats", "gonna", "wanna", "let",
            # Filler that reached a live report as "Top topics: doing,
            # evening, afternoon, head, mean" — none of which was a subject
            # anyone discussed.
            "doing", "does", "mean", "means", "meant", "evening", "afternoon",
            "night", "today", "tomorrow", "yesterday", "sorry", "remember",
            "again", "sure", "actually", "maybe", "think", "thought", "guess",
            "looks", "looking", "talking", "discussing", "anything", "everything",
            "something", "nothing", "another", "though", "each", "every",
})


def contributes_topics(text: str) -> bool:
    """False for small talk, which contributes no subjects.

    No stopword list anticipates every idiom, so phatic turns are skipped
    wholesale rather than word-by-word — "afternoon, Eli" is a greeting, not an
    interest in afternoons. Imported lazily: reflection must not take an
    import-time dependency on the engine.
    """
    text = str(text or "").strip()
    if not text:
        return False
    try:
        from eli.kernel.engine import _is_brief_phatic_prompt as _phatic
    except Exception:
        return True
    try:
        return not _phatic(text.lower())
    except Exception:
        log.debug("reflection: phatic check failed", exc_info=True)
        return True


def topic_words(text: str) -> set:
    """Distinct topic-bearing words in one message ('' when it is small talk)."""
    if not contributes_topics(text):
        return set()
    out = set()
    for w in str(text).lower().split():
        clean = "".join(c for c in w if c.isalnum())
        if len(clean) >= 4 and clean not in TOPIC_STOPWORDS:
            out.add(clean)
    return out


# Shared so the report header and the daemon's greeting cannot drift apart. The
# 12/17 boundaries are the ones proactive_daemon already used for its greeting.
def part_of_day(ts: Optional[float] = None) -> str:
    """"morning" / "afternoon" / "evening" for a wall-clock time."""
    hour = time.localtime(ts if ts is not None else time.time()).tm_hour
    if hour < 12:
        return "morning"
    if hour < 17:
        return "afternoon"
    return "evening"


def report_label(ts: Optional[float] = None) -> str:
    """Title for the daily report — named for when it is actually produced.

    The header was the fixed string "Morning report", printed beside a timestamp
    that frequently contradicted it: an 18:16 report read "Morning report —
    Saturday 15 August 2026, 18:16". The action is still MORNING_REPORT (that is
    its routing identity); only the words shown to the user follow the clock.
    """
    return f"{part_of_day(ts).capitalize()} report"


def reflect_on_period(hours: int = 24) -> Dict[str, Any]:
    """Generate a reflection summary from the last N hours."""
    mem = get_memory()
    insights: List[str] = []

    # App usage patterns
    events = mem.get_habit_events(event_type="app_launch", days=hours / 24)
    apps = []
    for e in (events or []):
        try:
            details = e.get("details", {}) if isinstance(e, dict) else {}
            if isinstance(details, str):
                import json
                try:
                    details = json.loads(details)
                except Exception:
                    details = {}
            app = details.get("app") if isinstance(details, dict) else None
            if app:
                apps.append(app)
        except Exception:
            continue
    if apps:
        top = Counter(apps).most_common(5)
        insights.append(f"App usage: {', '.join(f'{app} ({count}x)' for app, count in top)}")

    # Conversation volume
    try:
        since = time.time() - (hours * 3600)
        conversations = mem.get_recent_conversation(limit=500)
        recent = [c for c in conversations if c.get("timestamp", 0) >= since]
        user_msgs = [c for c in recent if c.get("role") == "user"]
        if user_msgs:
            insights.append(f"Conversation volume: {len(user_msgs)} user messages in last {hours}h")
            # Topic detection from user messages. Aggressive stopword filtering +
            # a minimum frequency so the report shows real subjects, not
            # conversational filler ("about", "just", "know", "going", etc.).
            all_words: Dict[str, int] = {}
            # Count DISTINCT MESSAGES a word appears in, not raw occurrences: one
            # message saying "head" twice is not a topic raised twice.
            for msg in user_msgs:
                for clean in topic_words(msg.get("content", "") or ""):
                    all_words[clean] = all_words.get(clean, 0) + 1
            # Require a topic to have been raised in at least two messages.
            top_topics = [(w, c) for w, c in
                          sorted(all_words.items(), key=lambda x: x[1], reverse=True)
                          if c >= 2][:5]
            if top_topics:
                insights.append("Top topics: " + ", ".join(w for w, _ in top_topics))
    except Exception:
        pass

    # Failure patterns
    try:
        failures = mem.recall_memory("failure error", limit=10)
        if failures:
            insights.append(f"Recent issues: {len(failures)} failure-related memories stored")
    except Exception:
        pass

    # Runtime evidence ledger: repeated actions, challenges, artifacts.
    try:
        from eli.runtime.evidence_ledger import recent_generated_artifacts, recent_events, repeated_event_signals

        repeated = repeated_event_signals(limit=12, days=max(1, int((hours + 23) // 24)))
        if repeated:
            # Internal/meta actions are not meaningful "patterns" for a human
            # report — they're just the assistant's own plumbing. Drop them, and
            # dedup by label so the same action isn't listed twice.
            _NOISE_ACTIONS = {
                "CHAT", "NOOP", "CHECK_JOB", "BACKGROUND_JOBS", "HABIT_RUN",
                "MORNING_REPORT", "DATE", "TIME", "SELF_REPORT", "RUNTIME_AUDIT",
                "GUI_RUNTIME_AUDIT", "MEMORY_STATUS", "MEMORY_RECALL", "SELF_ANALYZE",
            }
            parts = []
            seen = set()
            for item in repeated:
                label = str(item.get("action") or item.get("event_type") or "event").strip()
                if label.upper() in _NOISE_ACTIONS:
                    continue
                subject = item.get("subject") or ""
                key = (label.lower(), str(subject).lower())
                if key in seen:
                    continue
                seen.add(key)
                suffix = f" on {subject}" if subject else ""
                parts.append(f"{label}{suffix} ({item.get('count')}x)")
                if len(parts) >= 5:
                    break
            if parts:
                insights.append("Repeated actions: " + ", ".join(parts))

        challenges = recent_events(limit=8, event_type="user_challenge")
        if challenges:
            insights.append(f"User correction/challenge signals: {len(challenges)} recent events")

        # Source from real generation EVENTS, not filesystem mtime — a touched/
        # copied old file must never be reported as "just generated".
        generated = recent_generated_artifacts(hours=hours, limit=5)
        if generated:
            names = ", ".join(g.get("name", "") for g in generated if g.get("name"))
            insights.append(
                f"Generated artifacts ({len(generated)} in last {int(hours)}h): {names}"
                f"; latest={generated[0].get('name')}"
            )

        # Continuous User Model — surface the user's current focus so reflections track
        # how the user (not just the system) is evolving.
        try:
            from eli.runtime.user_model import read_user_model
            _um = read_user_model()
            if _um.get("is_seeded"):
                _focus = _um.get("current_focus") or []
                _focus_s = "; ".join(_focus[:3]) if isinstance(_focus, list) else str(_focus)
                if _focus_s:
                    insights.append(f"User model — current focus: {_focus_s}")
        except Exception:
            pass
    except Exception:
        pass

    # Store reflection as a memory for future context
    if insights:
        reflection_text = f"Reflection ({hours}h): " + "; ".join(insights)
        if not _already_stored(mem, reflection_text):
            try:
                mem.store_memory(reflection_text, tags=["reflection", "auto"])
            except Exception:
                log.debug("reflection: aggregate store failed", exc_info=True)
        # Also store each individual insight so the reflection surfaces can cite
        # it. These are TELEMETRY, not facts about anyone: recall filters them by
        # source ('eli_reflection') so they cannot compete with real user memories
        # — see the note on _noise_sources in memory.recall_memory. They were
        # previously written under a kind/tag combination picked to dodge that
        # filter, which is how 83% of everything ELI could recall came to be its
        # own failure counts and keyword tallies.
        for _ins in insights[:6]:
            _ins_text = str(_ins or "").strip()
            if not _ins_text or len(_ins_text) < 15:
                continue
            if _already_stored(mem, _ins_text):
                continue
            try:
                mem.store_memory(
                    _ins_text,
                    tags=["eli_insight", "auto"],
                    kind="insight",
                    source="eli_reflection",
                    importance=0.65,
                )
            except Exception:
                log.debug("reflection: insight store failed", exc_info=True)

    if not insights:
        insights.append("No evidence-backed activity signals recorded for this period.")

    return {"insights": insights, "period_hours": hours}


def reflect_on_memories(days: int = 1) -> Dict[str, Any]:
    """Analyse recent memories for patterns and store insights."""
    return reflect_on_period(hours=days * 24)


def run_reflection(hours: int = 24, days: int = None) -> Dict[str, Any]:
    """Primary entry point for reflection. Analyses activity, conversations, and errors."""
    if days is not None:
        hours = days * 24
    return reflect_on_period(hours=hours)
