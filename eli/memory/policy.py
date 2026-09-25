"""Storage policy: who produced a row, how strong it stays, when it is archived. Pure functions.

Origins: user_said (never archived), eli_said, telemetry, news, tool. Strength is a forgetting
curve reinforced by use; the half-life comes from how often this person actually uses ELI.
"""
from __future__ import annotations

import hashlib
import math
import re
from typing import Iterable, Sequence

from eli.core.self_provenance import is_bookkeeping_memory

ORIGIN_USER = "user_said"
ORIGIN_ELI = "eli_said"
ORIGIN_TELEMETRY = "telemetry"
ORIGIN_NEWS = "news"
ORIGIN_TOOL = "tool"

_NEWS = {"news_synthesis", "news", "briefing", "news_reflection", "news_digest"}
_TOOL = {"tool", "executor", "observation"}
_ELI = {"assistant", "eli"}
_USER_TAGS = {"user_confirmed", "user_explicit"}

DEFAULT_HALF_LIFE_DAYS = 30.0
MIN_HALF_LIFE_DAYS = 14.0
MAX_HALF_LIFE_DAYS = 120.0
IMPORTANCE_STRETCH = 3.0
REINFORCEMENT = 0.6
PIN_IMPORTANCE = 0.85
MIN_WEIGHT = 0.05
ARCHIVE_WEIGHT = 0.12

_ORIGIN_FACTOR = {ORIGIN_USER: 1.0, ORIGIN_ELI: 0.5, ORIGIN_TOOL: 0.35, ORIGIN_NEWS: 0.25, ORIGIN_TELEMETRY: 0.15}


def _tags(tags) -> set:
    if isinstance(tags, str):
        tags = tags.split(",")
    return {str(t).strip().lower() for t in (tags or []) if str(t).strip()}


def classify_origin(source: str = "user", kind: str = "memory", tags=None, text: str = "") -> str:
    src, knd, tg = str(source or "user").lower(), str(kind or "memory").lower(), _tags(tags)
    if tg & _USER_TAGS:
        return ORIGIN_USER
    if src in _NEWS or knd in _NEWS or "news_reflection" in tg:
        return ORIGIN_NEWS
    if src in _TOOL or "tool_observation" in tg:
        return ORIGIN_TOOL
    if is_bookkeeping_memory({"kind": knd, "source": src, "tags": ",".join(tg)}):
        return ORIGIN_TELEMETRY
    return ORIGIN_ELI if src in _ELI else ORIGIN_USER


def normalise_text(text: str) -> str:
    return re.sub(r"\W+", " ", str(text or "").lower()).strip()


def text_key(text: str) -> str:
    n = normalise_text(text)
    return hashlib.sha1(n.encode("utf-8")).hexdigest()[:20] if n else ""


def wants_vector_index(origin: str) -> bool:
    return origin != ORIGIN_TELEMETRY


def counts_as_evidence_about_user(origin: str) -> bool:
    return origin == ORIGIN_USER


def adaptive_half_life_days(active_day_gaps: Sequence[float]) -> float:
    """Default scaled by sqrt(median gap between days of use), within limits."""
    gaps = sorted(float(g) for g in active_day_gaps if g is not None and float(g) >= 0)
    if len(gaps) < 5:
        return DEFAULT_HALF_LIFE_DAYS
    mid = len(gaps) // 2
    median = gaps[mid] if len(gaps) % 2 else (gaps[mid - 1] + gaps[mid]) / 2.0
    return max(MIN_HALF_LIFE_DAYS, min(MAX_HALF_LIFE_DAYS, DEFAULT_HALF_LIFE_DAYS * math.sqrt(max(median, 1.0))))


def strength(now: float, last_touch_ts: float, importance: float, origin: str,
             seen_count: int = 1, recall_count: int = 0,
             half_life_days: float = DEFAULT_HALF_LIFE_DAYS, pinned: bool = False) -> float:
    """2 ** (-days since last touch / half_life); half_life grows with importance, origin and use."""
    if pinned or (float(importance or 0.0) >= PIN_IMPORTANCE and origin == ORIGIN_USER):
        return 1.0
    try:
        days = max(0.0, (float(now) - float(last_touch_ts or 0.0)) / 86400.0)
    except (TypeError, ValueError):
        return 1.0
    imp = max(0.0, min(1.0, float(importance if importance is not None else 0.5)))
    uses = max(0, int(seen_count or 1) - 1) + max(0, int(recall_count or 0))
    half = (float(half_life_days) * _ORIGIN_FACTOR.get(origin, 1.0)
            * (1.0 + IMPORTANCE_STRETCH * imp) * (1.0 + REINFORCEMENT * math.log1p(uses)))
    return max(MIN_WEIGHT, min(1.0, 2.0 ** (-days / max(half, 1e-6))))


def should_archive(origin: str, weight: float, recall_count: int, importance: float) -> bool:
    if origin == ORIGIN_USER or int(recall_count or 0) > 0 or float(importance or 0.0) >= PIN_IMPORTANCE:
        return False
    return float(weight or 0.0) <= ARCHIVE_WEIGHT


def merge_group(rows: Iterable[dict]) -> dict:
    """Earliest event time survives; sightings and recalls sum; latest sighting is last_seen."""
    rows = list(rows)
    firsts = [f for f in (float(r.get("event_ts") or r.get("ts") or 0.0) for r in rows) if f > 0]
    return {
        "seen_count": sum(max(1, int(r.get("seen_count") or 1)) for r in rows),
        "importance": max(float(r.get("importance") or 0.0) for r in rows),
        "event_ts": min(firsts) if firsts else 0.0,
        "last_seen": max(float(r.get("last_seen") or r.get("ts") or 0.0) for r in rows),
        "recall_count": sum(int(r.get("recall_count") or 0) for r in rows),
        "last_recalled": max(float(r.get("last_recalled") or 0.0) for r in rows),
    }
