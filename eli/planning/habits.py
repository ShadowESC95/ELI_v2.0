"""
Habit learning – monitors user actions, detects patterns, and manages automation rules.
Uses unified user memory.
"""

import time
from collections import Counter, defaultdict
from datetime import datetime
import hashlib

from eli.memory import get_memory



from eli.utils.log import get_logger
log = get_logger(__name__)

def log_event(event_type: str, data: dict):
    """Log an event for habit analysis."""
    mem = get_memory()
    mem.log_habit_event(event_type, data)


def _extract_hour_minute(ts):
    """Return (hour, minute), or None when the timestamp is missing/degenerate.

    Supports real unix timestamps and synthetic HHMM-style test timestamps
    (1000, 1001, …). Returns None for None / unparseable / epoch-0 sentinels so
    callers SKIP the event instead of fabricating a bogus 00:00 habit from a
    timestamp-less app-launch row (Jason, 2026-06-06: habits kept appearing at
    00:00).
    """
    if ts is None or ts == "":
        return None
    try:
        iv = int(float(ts))
    except (TypeError, ValueError):
        return None

    if iv <= 0:
        return None  # epoch-0 / missing sentinel — not a real time of day

    if iv <= 2359:  # synthetic HHMM test timestamp
        hour, minute = iv // 100, iv % 100
        return (hour, minute) if (0 <= hour <= 23 and 0 <= minute <= 59) else None

    try:
        dt = datetime.fromtimestamp(float(ts))
    except (OverflowError, OSError, ValueError):
        return None
    return dt.hour, dt.minute


def _round_up_to_next_5(minute: int) -> tuple[int, int]:
    """
    Round minute UP to the next 5-minute boundary.
    00 -> 05
    01 -> 05
    02 -> 05
    05 -> 05
    58 -> 00 with carry handled by caller
    """
    if minute <= 0:
        return 0, 5

    rounded = ((minute + 4) // 5) * 5
    if rounded >= 60:
        return 1, 0
    return 0, rounded


def detect_habits(days: int = 14, min_occurrences: int = 3):
    """
    Analyze habit events to detect repeated behavior.

    App launches still create time-based automation rules. Other repeated
    command/failure/correction patterns become observations so ELI can adapt
    without pretending every habit should become an executable schedule.
    """
    mem = get_memory()
    events = mem.get_habit_events(event_type=None, days=days)

    clusters = defaultdict(list)
    behavior_counts = Counter()
    behavior_examples = {}

    for e in events:
        # Guard against raw tuples from SQLite (no row_factory)
        if not isinstance(e, dict):
            try:
                e = dict(e)
            except (TypeError, ValueError):
                continue
        ts = e.get("timestamp")
        details = e.get("details") or {}
        if isinstance(details, str):
            import json as _json
            try:
                details = _json.loads(details)
            except Exception:
                details = {}
        if not isinstance(details, dict):
            details = {}
        etype = str(e.get("event_type") or details.get("event_type") or "").strip()
        ts = e.get("timestamp")

        action = str(details.get("action") or details.get("command") or details.get("cmd") or etype or "").strip().upper()
        subject = str(
            details.get("path")
            or details.get("target")
            or details.get("name")
            or details.get("app")
            or details.get("topic")
            or ""
        ).strip()
        ok = details.get("ok")
        outcome = "failed" if ok is False or str(details.get("outcome") or "").lower() == "failed" else "ok" if ok is True else ""
        if action:
            key = (etype or "event", action, subject[:120], outcome)
            behavior_counts[key] += 1
            behavior_examples.setdefault(key, details)

        app = details.get("app")
        cmd = details.get("cmd")

        if etype != "app_launch" or not app:
            continue

        if isinstance(cmd, list):
            command = " ".join(str(x) for x in cmd)
        elif cmd is None:
            command = str(app)
        else:
            command = str(cmd)

        hm = _extract_hour_minute(ts)
        if hm is None:
            # Timestamp-less / degenerate event — don't fabricate a 00:00 habit.
            continue
        hour, minute = hm
        clusters[(str(app), command, int(hour))].append(int(minute))

    existing_rules = mem.get_habit_rules(enabled_only=False)

    for (app, command, hour), minutes in clusters.items():
        if len(minutes) < int(min_occurrences):
            continue

        # Representative minute from the cluster
        avg_minute = int(round(sum(minutes) / len(minutes)))

        carry_hour, minute = _round_up_to_next_5(avg_minute)
        hour = (hour + carry_hour) % 24

        name = f"Open {app} at {hour:02d}:{minute:02d}"

        exists = False
        for rule in existing_rules:
            if not isinstance(rule, dict):
                try:
                    rule = dict(rule)
                except (TypeError, ValueError):
                    continue
            if (
                rule.get("name") == name
                and rule.get("command") == command
                and rule.get("hour") == hour
                and rule.get("minute") == minute
            ):
                exists = True
                break

        if not exists:
            # Create DISABLED (suggested) — ELI proposes habits but never activates
            # one without the user's say-so. The user approves by enabling it in the
            # Habits tab (Jason, 2026-06-06: "confirm with me before adding a habit").
            # positional args[0..3] preserved; enabled is an explicit keyword.
            mem.add_habit_rule(name, command, hour, minute, None, enabled=False)
            log.debug(f"[HABIT] Suggested (disabled) rule created — awaiting approval: {name}")

    _write_behavior_observations(mem, behavior_counts, behavior_examples, min_occurrences)


def _write_behavior_observations(mem, counts: Counter, examples: dict, min_occurrences: int) -> None:
    try:
        existing = mem.get_recent_observations(limit=200) if hasattr(mem, "get_recent_observations") else []
    except Exception:
        existing = []
    existing_text = "\n".join(str((r or {}).get("content") or (r or {}).get("observation") or "") for r in existing if isinstance(r, dict)).lower()

    for (etype, action, subject, outcome), count in counts.most_common(20):
        if count < int(min_occurrences):
            continue
        if not action:
            continue
        digest = hashlib.sha1(f"{etype}|{action}|{subject}|{outcome}".encode("utf-8", "ignore")).hexdigest()[:10]
        if digest in existing_text:
            continue
        subject_part = f" subject={subject!r}" if subject else ""
        outcome_part = f" outcome={outcome}" if outcome else ""
        observation = (
            f"[habit:{digest}] Repeated runtime pattern seen {count}x in the last window: "
            f"event={etype or 'event'} action={action}{subject_part}{outcome_part}. "
            "Use this as routing context before retrying the same behavior."
        )
        try:
            mem.add_observation("habit", observation, source="habit_detector", category="behavior_pattern")
        except Exception:
            pass


def schedule_detection_loop(interval_hours: int = 12):
    """Run habit detection periodically."""
    import threading

    def loop():
        while True:
            time.sleep(interval_hours * 3600)
            detect_habits()

    threading.Thread(target=loop, daemon=True).start()
