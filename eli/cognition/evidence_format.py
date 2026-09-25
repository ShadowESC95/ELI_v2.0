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


def row_time(row: Any) -> Optional[float]:
    """When a row's content happened: event_ts, else ts, else timestamp."""
    if not isinstance(row, dict):
        return None
    return next((v for v in (_ts(row.get(k)) for k in ("event_ts", "ts", "timestamp")) if v), None)
