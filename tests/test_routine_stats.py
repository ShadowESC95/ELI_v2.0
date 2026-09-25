"""Routines are clock times on a circle, and a moved or stopped routine is noticed."""
import time
from datetime import datetime

from eli.planning import routine_stats as rs
from eli.planning.habits import detect_habits


def _m(h, m):
    return h * 60 + m


def test_nearby_times_are_one_routine_across_the_hour_boundary():
    clusters = rs.cluster_times([(_m(8, 58), 1), (_m(9, 2), 2), (_m(9, 4), 3)])
    assert len(clusters) == 1 and rs.circular_distance(clusters[0].centre, _m(9, 0)) < 3


def test_times_either_side_of_midnight_are_one_routine():
    clusters = rs.cluster_times([(_m(23, 55), 1), (_m(0, 5), 2)])
    assert len(clusters) == 1 and rs.circular_distance(clusters[0].centre, 0) < 6


def test_distant_times_are_separate_routines():
    assert len(rs.cluster_times([(_m(8, 0), 1), (_m(8, 5), 2), (_m(19, 0), 3), (_m(19, 10), 4)])) == 2


def test_a_moved_routine_is_a_shift():
    obs = [(_m(9, 0) + i % 3, d) for i, d in enumerate(range(1, 15))] + [(_m(14, 0) + i % 3, d) for i, d in enumerate(range(20, 28))]
    shift = rs.detect_shift(obs)
    assert shift and rs.circular_distance(shift["old"], _m(9, 0)) < 5 and rs.circular_distance(shift["new"], _m(14, 0)) < 5


def test_scattered_use_and_a_steady_routine_are_not_shifts():
    steady = [(_m(9, 0) + i % 4, d) for i, d in enumerate(range(1, 30))]
    assert rs.detect_shift(steady) is None
    scattered = [(_m(h, 0), d) for d, h in enumerate([6, 21, 11, 3, 17, 9, 23, 14, 1, 19, 8, 12], start=1)]
    assert rs.detect_shift(scattered) is None


def test_a_routine_that_stopped_is_a_lapse_only_against_active_days():
    active = list(range(1, 31))
    assert rs.detect_lapse(range(1, 16), active) is True
    assert rs.detect_lapse(range(1, 31), active) is False
    assert rs.detect_lapse(range(1, 16), list(range(1, 16))) is False


class _Mem:
    def __init__(self, events):
        self.events, self.rules, self.notes = events, [], []

    def purge_invalid_habit_rules(self):
        pass

    def get_habit_events(self, event_type=None, days=14):
        return self.events

    def get_habit_rules(self, enabled_only=False):
        return self.rules

    def add_habit_rule(self, name, command, hour, minute, days, enabled=False):
        self.rules.append({"name": name, "command": command, "hour": hour, "minute": minute})

    def get_recent_observations(self, limit=200):
        return [{"content": n} for _c, n in self.notes]

    def add_observation(self, kind, text, **kw):
        self.notes.append((kind, text))


def _events(hm_by_day):
    out = []
    base = datetime(2026, 9, 1).timestamp()
    for day, (h, m) in hm_by_day:
        out.append({"event_type": "app_launch", "timestamp": base + day * 86400 + h * 3600 + m * 60, "details": {"app": "code"}})
    return out


def test_detection_joins_08_58_and_09_02_and_offers_one_rule(monkeypatch):
    mem = _Mem(_events([(1, (8, 58)), (2, (9, 2)), (3, (9, 0)), (4, (9, 3))]))
    monkeypatch.setattr("eli.planning.habits.get_memory", lambda: mem)
    summary = detect_habits(days=60)
    assert summary["suggested"] == 1 and mem.rules[0]["hour"] == 9 and mem.rules[0]["minute"] in (0, 5)


def test_detection_reports_a_moved_routine_once(monkeypatch):
    days = [(d, (9, d % 3)) for d in range(1, 15)] + [(d, (14, d % 3)) for d in range(20, 28)]
    mem = _Mem(_events(days))
    monkeypatch.setattr("eli.planning.habits.get_memory", lambda: mem)
    first = detect_habits(days=90)
    detect_habits(days=90)
    assert first["shifts"] and len([n for _k, n in mem.notes if "habit-shift" in n]) == 1
