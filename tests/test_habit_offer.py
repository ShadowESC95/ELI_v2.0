"""Tests for the proactive habit-offer flow: ELI proposes a detected habit
(disabled) and only activates it on the user's yes. Plus the 00:00 timestamp fix.

Deterministic — no model, no daemon; uses a temp artifacts dir + temp DB.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

import eli.planning.habits as H
from eli.planning.habits import _extract_hour_minute
from eli.memory.memory import Memory


@pytest.fixture
def tmp_artifacts(monkeypatch, tmp_path):
    monkeypatch.setattr(H, "_artifacts_dir", lambda: tmp_path)
    H.clear_pending_habit()
    yield tmp_path
    H.clear_pending_habit()


@pytest.fixture
def tmp_memory(monkeypatch):
    db = tempfile.mktemp(suffix=".sqlite3")
    m = Memory(db_path=db)
    import eli.memory as mem_pkg
    monkeypatch.setattr(mem_pkg, "get_memory", lambda: m)
    yield m
    Path(db).unlink(missing_ok=True)


# ── 00:00 fix ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("ts,expected", [
    (None, None), ("", None), (0, None), (0.0, None), ("0", None),
    (1000, (10, 0)), (1305, (13, 5)),
])
def test_extract_hour_minute_skips_degenerate(ts, expected):
    assert _extract_hour_minute(ts) == expected


def test_real_unix_timestamp_parses():
    hm = _extract_hour_minute(1780759925)
    assert hm is not None and 0 <= hm[0] <= 23 and 0 <= hm[1] <= 59


# ── pending-offer state ──────────────────────────────────────────────────────
def test_pending_habit_state_roundtrip(tmp_artifacts):
    assert H.get_pending_habit() is None
    H.set_pending_habit(7, "Open spotify at 09:00", 9, 0, "spotify")
    p = H.get_pending_habit()
    assert p and p["rule_id"] == 7 and p["hour"] == 9
    H.clear_pending_habit()
    assert H.get_pending_habit() is None


def test_offered_tracking(tmp_artifacts):
    assert not H.was_offered(42)
    H.mark_offered(42)
    assert H.was_offered(42)


# ── router intercept ─────────────────────────────────────────────────────────
def test_router_intercepts_yes_no_only_when_pending(tmp_artifacts):
    from eli.execution.router_enhanced import route
    # Nothing pending → 'yes' is ordinary chat, not a habit confirm.
    assert route("yes")["action"] != "CONFIRM_HABIT"
    H.set_pending_habit(1, "Open spotify at 09:00", 9, 0, "spotify")
    assert route("yes")["action"] == "CONFIRM_HABIT"
    assert route("sure, add it")["action"] == "CONFIRM_HABIT"
    assert route("no thanks")["action"] == "DECLINE_HABIT"


# ── confirm / decline executor ───────────────────────────────────────────────
def test_confirm_habit_enables_rule(tmp_artifacts, tmp_memory):
    from eli.execution import executor_enhanced as EX
    rid = tmp_memory.add_habit_rule("Open spotify at 09:00", "spotify", 9, 0, None, enabled=False)
    H.set_pending_habit(rid, "Open spotify at 09:00", 9, 0, "spotify")
    res = EX.execute("CONFIRM_HABIT", {"message": "yes"})
    assert res["ok"]
    rule = {r["id"]: r for r in tmp_memory.get_habit_rules(enabled_only=False)}[rid]
    assert rule["enabled"]
    assert H.get_pending_habit() is None


def test_decline_habit_removes_suggestion(tmp_artifacts, tmp_memory):
    from eli.execution import executor_enhanced as EX
    rid = tmp_memory.add_habit_rule("Open spotify at 09:00", "spotify", 9, 0, None, enabled=False)
    H.set_pending_habit(rid, "Open spotify at 09:00", 9, 0, "spotify")
    res = EX.execute("DECLINE_HABIT", {"message": "no"})
    assert res["ok"]
    assert rid not in {r["id"] for r in tmp_memory.get_habit_rules(enabled_only=False)}
    assert H.get_pending_habit() is None


def test_confirm_with_no_pending_is_graceful(tmp_artifacts, tmp_memory):
    from eli.execution import executor_enhanced as EX
    res = EX.execute("CONFIRM_HABIT", {"message": "yes"})
    assert res["ok"]
    assert "no habit offer" in res["content"].lower()
