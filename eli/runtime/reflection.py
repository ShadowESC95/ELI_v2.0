"""
Reflection engine — analyses memories, conversations, and patterns to extract insights.
Uses unified memory system. Stores reflections back into memory for future context.
"""
from __future__ import annotations

import time
from collections import Counter
from typing import Dict, Any, List
from eli.memory import get_memory


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
            _stopwords = {
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
            }
            for msg in user_msgs:
                words = msg.get("content", "").lower().split()
                for w in words:
                    clean = "".join(c for c in w if c.isalnum())
                    if len(clean) >= 4 and clean not in _stopwords:
                        all_words[clean] = all_words.get(clean, 0) + 1
            # Require a topic to appear at least twice to count as a "topic".
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
        try:
            existing = mem.recall_memory("reflection", limit=5)
            if not any(reflection_text[:50] in str(m.get("text", "")) for m in existing):
                mem.store_memory(reflection_text, tags=["reflection", "auto"])
        except Exception:
            pass
        # Also store each individual insight as a searchable "insight" memory.
        # "reflection" kind/tag is noise-filtered in recall — "insight" kind surfaces.
        for _ins in insights[:6]:
            _ins_text = str(_ins or "").strip()
            if not _ins_text or len(_ins_text) < 15:
                continue
            try:
                _existing = mem.recall_memory(_ins_text[:40], limit=2)
                if not any(_ins_text[:30].lower() in str(m.get("text", "")).lower() for m in _existing):
                    mem.store_memory(
                        _ins_text,
                        tags=["eli_insight", "auto"],
                        kind="insight",
                        source="eli_reflection",
                        importance=0.65,
                    )
            except Exception:
                pass

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
