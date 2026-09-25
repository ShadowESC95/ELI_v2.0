"""
Habit learning – monitors user actions, detects patterns, and manages automation rules.
Uses unified user memory.
"""

import json
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
import hashlib

from eli.memory import get_memory
from eli.planning import routine_stats as _rs



from eli.utils.log import get_logger
log = get_logger(__name__)

# Proactive habit-offer state: ELI proposes a detected habit (a specific app at a specific hour) and
# asks before activating it. The offer awaiting yes/no lives in pending_habit; offered rule ids are
# remembered so the same suggestion isn't pitched twice.
def _artifacts_dir() -> Path:
    try:
        from eli.core.paths import get_paths
        d = Path(get_paths().artifacts_dir)
    except Exception:
        d = Path(__file__).resolve().parents[2] / "artifacts"
    d.mkdir(parents=True, exist_ok=True)
    return d


_PENDING_HABIT_TTL = 1800  # 30 min — a habit offer auto-expires


def _pending_habit_file() -> Path:
    return _artifacts_dir() / "pending_habit.json"


def _offered_file() -> Path:
    return _artifacts_dir() / "offered_habits.json"


def set_pending_habit(rule_id: int, name: str, hour: int, minute: int, command: str = "") -> None:
    _pending_habit_file().write_text(json.dumps({
        "created_at": time.time(), "rule_id": int(rule_id), "name": name,
        "hour": int(hour), "minute": int(minute), "command": command or "",
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def get_pending_habit():
    p = _pending_habit_file()
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    if time.time() - float(d.get("created_at", 0)) > _PENDING_HABIT_TTL:
        clear_pending_habit()
        return None
    return d


def clear_pending_habit() -> None:
    try:
        _pending_habit_file().unlink()
    except FileNotFoundError:
        log.debug("suppressed exception", exc_info=True)


def _offered_ids() -> set:
    p = _offered_file()
    if not p.exists():
        return set()
    try:
        return set(int(x) for x in json.loads(p.read_text(encoding="utf-8")))
    except Exception:
        return set()


def was_offered(rule_id: int) -> bool:
    return int(rule_id) in _offered_ids()


def mark_offered(rule_id: int) -> None:
    ids = _offered_ids()
    ids.add(int(rule_id))
    try:
        _offered_file().write_text(json.dumps(sorted(ids)), encoding="utf-8")
    except Exception:
        log.debug("suppressed exception", exc_info=True)

def log_event(event_type: str, data: dict):
    """Log an event for habit analysis."""
    mem = get_memory()
    mem.log_habit_event(event_type, data)


def _extract_hour_minute(ts):
    """Return (hour, minute), or None when the timestamp is missing/degenerate.

    Supports real unix timestamps and synthetic HHMM-style test timestamps
    (1000, 1001, …). Returns None for None / unparseable / epoch-0 sentinels so
    callers SKIP the event instead of fabricating a bogus 00:00 habit from a
    timestamp-less app-launch row (user-reported, 2026-06-06: habits kept appearing at
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


def _extract_day_key(ts):
    """Return a calendar-day key (date ordinal) for a REAL unix timestamp, or None
    for synthetic/dateless timestamps. Used to count how many *distinct days* a
    behaviour recurred on — a genuine routine repeats across days, not 3 times in
    one afternoon. Synthetic HHMM test timestamps (<=2359) carry no date, so they
    return None and detection falls back to the raw-count gate."""
    try:
        iv = int(float(ts))
    except (TypeError, ValueError):
        return None
    if iv <= 2359:  # synthetic HHMM or missing — no real calendar date
        return None
    try:
        return datetime.fromtimestamp(float(ts)).date().toordinal()
    except (OverflowError, OSError, ValueError):
        return None


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


def detect_habits(days: int = 14, min_occurrences: int = 3, min_days: int = 3):
    """
    Analyze habit events to detect repeated behavior.

    App launches still create time-based automation rules. Other repeated
    command/failure/correction patterns become observations so ELI can adapt
    without pretending every habit should become an executable schedule.

    Smarter, user-tailored gate: a real routine recurs on *distinct days*, not 3
    times in one afternoon. When events carry real timestamps, a suggestion is only
    created when the (app, hour) pattern appears on >= ``min_days`` separate calendar
    days — so ELI proposes genuine routines instead of nonsense from a single-session
    burst. Synthetic/dateless events fall back to the raw >= ``min_occurrences`` count.
    """
    mem = get_memory()
    # Self-heal: drop legacy un-schedulable rows (NULL time + command==name) that
    # otherwise surface as a bogus "run around 00:00" offer (user-reported).
    try:
        if hasattr(mem, "purge_invalid_habit_rules"):
            mem.purge_invalid_habit_rules()
    except Exception:
        log.debug("suppressed exception", exc_info=True)
    events = mem.get_habit_events(event_type=None, days=days)

    obs = defaultdict(list)  # (app, command) -> [(minute of day, calendar day or None)]
    active_days = set()      # days with any event at all: the days a routine could have happened
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
        _any_day = _extract_day_key(ts)
        if _any_day is not None:
            active_days.add(_any_day)

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
        obs[(str(app), command)].append((_rs.minute_of_day(hour, minute), _extract_day_key(ts)))

    existing_rules = mem.get_habit_rules(enabled_only=False)
    summary = {"suggested": 0, "shifts": [], "lapsed": []}

    for (app, command), points in obs.items():
        _dated = [(m, d) for m, d in points if d is not None]
        _fmt = lambda mins: "%02d:%02d" % _rs.to_hour_minute(mins)
        try:
            _shift = _rs.detect_shift(_dated)
            if _shift:
                summary["shifts"].append((app, _shift))
                _note_routine_change(mem, "shift", app, command,
                                     f"You used to open {app} around {_fmt(_shift['old'])} and lately around {_fmt(_shift['new'])}.")
            elif _rs.detect_lapse({d for _, d in _dated}, active_days):
                summary["lapsed"].append(app)
                _note_routine_change(mem, "lapse", app, command,
                                     f"You used to open {app} most days you were active and have not lately.")
        except Exception:
            log.debug("routine change check failed", exc_info=True)

    for app, command, cluster in [(a, c, cl) for (a, c), pts in obs.items() for cl in _rs.cluster_times(pts)]:
        # Recurrence gate: prefer distinct-day evidence (a real routine repeats across days); fall
        # back to the raw count only when events are dateless (synthetic timestamps). Stops a
        # single-session burst ("opened the app 3x this afternoon") being proposed as a daily habit.
        if cluster.distinct_days:
            if cluster.distinct_days < int(min_days):
                continue
        elif len(cluster.minutes) < int(min_occurrences):
            continue

        # The cluster's circular mean, so 08:58 and 09:02 are one routine. A time on the hour goes
        # to the next five minutes, as before.
        _mid = int(round(cluster.centre))
        _mid = _mid + 5 if _mid % 60 == 0 else ((_mid + 4) // 5) * 5
        hour, minute = _rs.to_hour_minute(_mid)

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
            # Create disabled (suggested): ELI proposes habits but never activates one without the
            # user's say-so; approval is enabling it in the Habits tab. Positional args[0..3] are
            # preserved; enabled is an explicit keyword.
            mem.add_habit_rule(name, command, hour, minute, None, enabled=False)
            summary["suggested"] += 1
            log.debug(f"[HABIT] Suggested (disabled) rule created — awaiting approval: {name}")

    _write_behavior_observations(mem, behavior_counts, behavior_examples, min_occurrences)
    return summary


def _note_routine_change(mem, kind: str, app: str, command: str, text: str) -> None:
    """Record that a routine moved or stopped, once. A rule the user enabled is never changed on its own."""
    digest = hashlib.sha1(f"{kind}|{app}|{command}|{text}".encode("utf-8", "ignore")).hexdigest()[:10]
    try:
        recent = mem.get_recent_observations(limit=200) if hasattr(mem, "get_recent_observations") else []
        if any(digest in str((r or {}).get("content") or (r or {}).get("observation") or "") for r in recent if isinstance(r, dict)):
            return
        mem.add_observation("habit", f"[habit-{kind}:{digest}] {text} Suggest reviewing the matching rule.",
                            source="habit_detector", category="routine_change")
    except Exception:
        log.debug("routine change not recorded", exc_info=True)


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
            log.debug("suppressed exception", exc_info=True)


def schedule_detection_loop(interval_hours: int = 12):
    """Run habit detection periodically."""
    import threading

    def loop():
        while True:
            time.sleep(interval_hours * 3600)
            detect_habits()

    threading.Thread(target=loop, daemon=True).start()
