"""Dates on evidence lines, from each row's own timestamp."""
from __future__ import annotations

import time
from typing import Any, Optional


def _ts(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def age_label(ts: Any, now: Optional[float] = None) -> str:
    t = _ts(ts)
    if t is None:
        return ""
    now = time.time() if now is None else float(now)
    day = lambda x: time.strftime("%Y-%m-%d", time.localtime(x))
    if day(t) == day(now):
        return "today"
    days = round((time.mktime(time.strptime(day(now), "%Y-%m-%d")) - time.mktime(time.strptime(day(t), "%Y-%m-%d"))) / 86400)
    if days < 0:
        return "in the future"
    if days == 1:
        return "yesterday"
    if days < 14:
        return f"{days} days ago"
    if days < 60:
        return f"{days // 7} weeks ago"
    if days < 730:
        return f"{max(2, round(days / 30.44))} months ago"
    return f"{days // 365} years ago"


def when_label(ts: Any, now: Optional[float] = None) -> str:
    """'2026-08-24 Mon, 32 days ago', or '' when the time is unknown."""
    t = _ts(ts)
    if t is None:
        return ""
    stamp = time.strftime("%Y-%m-%d %a", time.localtime(t))
    age = age_label(t, now)
    return f"{stamp}, {age}" if age else stamp


def turn_stamp(ts: Any, now: Optional[float] = None) -> str:
    """Short time label for a conversation line: 'today 14:34', 'yesterday 18:37',
    'Thu 01 Oct 18:24, 2 days ago'. Empty when the time is unknown.

    History blocks used to show turns from earlier sessions undated, under a
    "this session" header. The model then reported yesterday's Netflix tab as open
    and yesterday's song as playing, and did its own wrong date arithmetic."""
    t = _ts(ts)
    if t is None:
        return ""
    age = age_label(t, now)
    clock = time.strftime("%H:%M", time.localtime(t))
    if age in ("today", "yesterday"):
        return f"{age} {clock}"
    stamp = time.strftime("%a %d %b %H:%M", time.localtime(t))
    return f"{stamp}, {age}" if age else stamp


def row_time(row: Any) -> Optional[float]:
    """When a row's content happened: event_ts, else ts, else timestamp."""
    if not isinstance(row, dict):
        return None
    return next((v for v in (_ts(row.get(k)) for k in ("event_ts", "ts", "timestamp")) if v), None)


def latest_user_message(prompt: str) -> str:
    """The user's own message when recent history has been put in front of it
    ("...\n\nYou: <message>"). Tone and date reading used the whole thing, so a "!!"
    two turns back made a calm question read as "ecstatic"."""
    text = str(prompt or "")
    i = text.rfind("\n\nYou: ")
    return text[i + len("\n\nYou: "):] if i >= 0 else text


def date_facts(text: str, now: Optional[float] = None) -> str:
    """Every calendar date the user wrote, with its weekday and distance from today, worked
    out here rather than by the model ("how many days ago was 09-09-2026" was answered with
    the date alone, then "24 days" by hand). '' when the message names no date."""
    import re
    from datetime import datetime
    try:
        from eli.cognition import query_planner as qp
    except Exception:
        return ""
    low = str(text or "").lower()
    n = datetime.fromtimestamp(time.time() if now is None else float(now))
    today = n.replace(hour=0, minute=0, second=0, microsecond=0)
    seen, parts = set(), []

    def rel(day: datetime) -> str:
        delta = (today - day).days
        return ("today" if delta == 0 else "yesterday" if delta == 1 else "tomorrow" if delta == -1
                else f"{delta} days before today" if delta > 0 else f"{-delta} days after today")

    def say(label: str, day: datetime) -> None:
        key = (label, day.date())
        if key in seen:
            return
        seen.add(key)
        parts.append(f"{label} = {day.strftime('%A %d %B %Y')}, {rel(day)}")

    numeric = qp.numeric_dates(low)
    by_pos: dict = {}
    for pos, y, mo, d in numeric:
        try:
            by_pos.setdefault(pos, []).append(datetime(int(y), mo, d))
        except ValueError:
            pass
    for pos, days in by_pos.items():
        raw = re.match(r"\S+", low[pos:]).group(0).rstrip("?.,!)")
        if len(days) > 1:
            parts.append(f"{raw} reads two ways (ask which if it matters): "
                         + " or ".join(f"{d.strftime('%A %d %B %Y')} ({rel(d)})" for d in days))
            continue
        say(raw, days[0])
    numeric_spans = [(p, p + 10) for p in by_pos]
    for pos, day in qp._explicit_dates(low, n):
        if any(a <= pos < b for a, b in numeric_spans):
            continue
        say(day.strftime("%d %B %Y"), day)
    if not parts:
        return ""
    return ("DATE FACTS (worked out from the calendar; use these, do not recompute): "
            + "; ".join(parts) + f". Today is {today.strftime('%A %d %B %Y')}.")


def time_facts(text: str, now: Optional[float] = None) -> str:
    """Every time of day the user wrote, as a clock time today and how far off it is, worked out
    here rather than by the model. Live, at 09:06: "the original meeting at 10 AM has passed".
    '' when the message names no time."""
    from datetime import datetime
    try:
        from eli.runtime.agenda import _clock_candidates
        found = _clock_candidates(str(text or ""))[:4]
    except Exception:
        return ""
    if not found:
        return ""
    n = datetime.fromtimestamp(time.time() if now is None else float(now))
    parts, seen = [], set()
    for a, b, h, mi, ap in found:
        if ap == "pm" and h < 12:
            h += 12
        elif ap == "am" and h == 12:
            h = 0
        elif ap is None and 1 <= h <= 6:
            h += 12
        at = n.replace(hour=h % 24, minute=mi, second=0, microsecond=0)
        if at in seen:
            continue
        seen.add(at)
        mins = int(round(abs((at - n).total_seconds()) / 60.0))
        gap = (f"{mins // 60} h {mins % 60} min" if mins >= 60 and mins % 60 else f"{mins // 60} h" if mins >= 60
               else f"{mins} min")
        parts.append(f"{str(text)[a:b].strip()} = {at.strftime('%H:%M')} today, "
                     + (f"{gap} from now" if at > n else f"{gap} ago" if mins else "now"))
    return ("TIME FACTS (worked out from the clock; use these, do not recompute): " + "; ".join(parts)
            + f". It is now {n.strftime('%H:%M')}.")


# A conversation ends when nothing is said for this long, or when its turns are this old.
_CONVERSATION_GAP_S = 3 * 3600
_CONVERSATION_MAX_AGE_S = 12 * 3600


def this_conversation(turns: Any, now: Optional[float] = None) -> list:
    """The tail of `turns` (oldest first) that belongs to the conversation going on now.

    The dialogue put in front of the model was "the last N turns", whenever they were said. On
    a Monday morning that was Saturday's argument, ELI's invented diagnoses included, and a
    small model answered a remark about a presentation by continuing it. Earlier days are still
    reachable: a question about them gets the period log, and a topic is found by retrieval."""
    rows = [t for t in (turns or []) if isinstance(t, dict)]
    if not rows:
        return []
    n = time.time() if now is None else float(now)
    out: list = []
    newer = n
    for t in reversed(rows):
        ts = row_time(t)
        if not ts:
            out.append(t)       # undated: nothing to judge it by
            continue
        if n - ts > _CONVERSATION_MAX_AGE_S or newer - ts > _CONVERSATION_GAP_S:
            break
        out.append(t)
        newer = ts
    out.reverse()
    return out
