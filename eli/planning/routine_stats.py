"""Time-of-day statistics for routines: circular clustering and change detection.

Clock times live on a circle, so 23:55 and 00:05 are ten minutes apart and 08:58 and 09:02 are one
routine, not two hour buckets.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

DAY_MIN = 1440.0
CLUSTER_GAP_MIN = 30.0
SHIFT_MIN = 60.0
TIGHT_SPREAD_MIN = 45.0


def circular_distance(a: float, b: float) -> float:
    d = abs(float(a) - float(b)) % DAY_MIN
    return min(d, DAY_MIN - d)


def circular_mean(minutes: Sequence[float]) -> float:
    xs = [math.cos(2 * math.pi * m / DAY_MIN) for m in minutes]
    ys = [math.sin(2 * math.pi * m / DAY_MIN) for m in minutes]
    ang = math.atan2(sum(ys), sum(xs))
    return (ang * DAY_MIN / (2 * math.pi)) % DAY_MIN


def circular_spread(minutes: Sequence[float]) -> float:
    """Mean distance from the circular mean, in minutes."""
    if not minutes:
        return 0.0
    c = circular_mean(minutes)
    return sum(circular_distance(m, c) for m in minutes) / len(minutes)


@dataclass
class Cluster:
    minutes: List[float] = field(default_factory=list)
    days: List[Optional[int]] = field(default_factory=list)

    @property
    def centre(self) -> float:
        return circular_mean(self.minutes)

    @property
    def spread(self) -> float:
        return circular_spread(self.minutes)

    @property
    def distinct_days(self) -> int:
        return len({d for d in self.days if d is not None})

    @property
    def last_day(self) -> Optional[int]:
        seen = [d for d in self.days if d is not None]
        return max(seen) if seen else None


def cluster_times(obs: Iterable[Tuple[float, Optional[int]]], gap: float = CLUSTER_GAP_MIN) -> List[Cluster]:
    """Group (minute_of_day, day) observations into clusters where neighbours are within `gap` minutes on the circle."""
    pts = sorted((float(m) % DAY_MIN, d) for m, d in obs)
    if not pts:
        return []
    groups: List[List[Tuple[float, Optional[int]]]] = [[pts[0]]]
    for p in pts[1:]:
        if p[0] - groups[-1][-1][0] <= gap:
            groups[-1].append(p)
        else:
            groups.append([p])
    if len(groups) > 1 and (groups[0][0][0] + DAY_MIN) - groups[-1][-1][0] <= gap:
        groups[0] = groups.pop() + groups[0]
    return [Cluster([m for m, _ in g], [d for _, d in g]) for g in groups]


def detect_shift(obs: Sequence[Tuple[float, int]], *, recent_days: int = 10, min_recent: int = 3, min_old: int = 3,
                 shift_min: float = SHIFT_MIN) -> Optional[Dict[str, float]]:
    """A routine that moved: the recent observations sit somewhere else than the earlier ones.

    obs are (minute_of_day, day_ordinal). Both windows must be tight, so scattered use is not a shift.
    Returns {"old": minute, "new": minute, "since_day": day} or None.
    """
    dated = sorted(((d, float(m)) for m, d in obs if d is not None))
    if len(dated) < min_recent + min_old:
        return None
    cut = dated[-1][0] - int(recent_days)
    old = [m for d, m in dated if d <= cut]
    new = [m for d, m in dated if d > cut]
    if len(old) < min_old or len(new) < min_recent:
        return None
    if circular_spread(old) > TIGHT_SPREAD_MIN or circular_spread(new) > TIGHT_SPREAD_MIN:
        return None
    if circular_distance(circular_mean(old), circular_mean(new)) < shift_min:
        return None
    since = min(d for d, _ in dated if d > cut)
    return {"old": circular_mean(old), "new": circular_mean(new), "since_day": float(since)}


def detect_lapse(routine_days: Iterable[int], active_days: Iterable[int], *, recent_days: int = 10,
                 min_active_recent: int = 5, old_rate: float = 0.6, recent_rate: float = 0.1) -> bool:
    """A routine that stopped, judged against the days the person was actually active.

    Days with no activity at all prove nothing, so only active days count as chances to have done it.
    """
    active = sorted({int(d) for d in active_days})
    if not active:
        return False
    done = {int(d) for d in routine_days}
    cut = active[-1] - int(recent_days)
    old_active = [d for d in active if d <= cut]
    recent_active = [d for d in active if d > cut]
    if len(recent_active) < min_active_recent or len(old_active) < min_active_recent:
        return False
    return (sum(d in done for d in old_active) / len(old_active) >= old_rate
            and sum(d in done for d in recent_active) / len(recent_active) <= recent_rate)


def minute_of_day(hour: int, minute: int) -> float:
    return float(hour * 60 + minute)


def to_hour_minute(minute: float) -> Tuple[int, int]:
    m = int(round(minute)) % 1440
    return m // 60, m % 60
