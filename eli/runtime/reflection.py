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
            # Topic detection from user messages
            all_words: Dict[str, int] = {}
            _stopwords = {"i", "me", "my", "the", "a", "an", "is", "was", "it", "to", "do",
                          "you", "your", "and", "or", "of", "in", "on", "for", "what", "how",
                          "can", "that", "this", "with", "not", "are", "have", "has", "be"}
            for msg in user_msgs:
                words = msg.get("content", "").lower().split()
                for w in words:
                    clean = "".join(c for c in w if c.isalnum())
                    if len(clean) >= 4 and clean not in _stopwords:
                        all_words[clean] = all_words.get(clean, 0) + 1
            top_topics = sorted(all_words.items(), key=lambda x: x[1], reverse=True)[:5]
            if top_topics:
                insights.append(f"Top topics: {', '.join(w for w, _ in top_topics)}")
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
        from eli.runtime.evidence_ledger import artifact_snapshot, recent_events, repeated_event_signals

        repeated = repeated_event_signals(limit=5, days=max(1, int((hours + 23) // 24)))
        if repeated:
            parts = []
            for item in repeated[:5]:
                label = item.get("action") or item.get("event_type") or "event"
                subject = item.get("subject") or ""
                suffix = f" on {subject}" if subject else ""
                parts.append(f"{label}{suffix} ({item.get('count')}x)")
            insights.append("Repeated runtime patterns: " + ", ".join(parts))

        challenges = recent_events(limit=8, event_type="user_challenge")
        if challenges:
            insights.append(f"User correction/challenge signals: {len(challenges)} recent events")

        generated = artifact_snapshot("all", limit=6)
        if generated:
            newest = generated[0]
            insights.append(
                "Recent generated artifacts: "
                + ", ".join(item.get("name", "") for item in generated[:4] if item.get("name"))
                + f"; latest={newest.get('name')}"
            )
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
