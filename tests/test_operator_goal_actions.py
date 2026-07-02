"""operator_goal_actions — create / enable / update goals (writes to the goal store).
Isolated via ELI_ARTIFACTS_DIR. The validation path is pure; the lifecycle hits the store.
"""
from __future__ import annotations

from eli.planning import operator_goal_actions as oga


def test_create_goal_requires_title():
    r = oga.create_goal(title="   ")
    assert r["ok"] is False and "title" in r["error"]


def test_create_enable_update_lifecycle():
    r = oga.create_goal(title="unit-test goal", objective="do a thing")
    assert r["ok"] is True
    goal = r["goal"]
    gid = goal.get("id") or goal.get("goal_id")
    assert gid
    assert isinstance(oga.set_goal_enabled(gid, False), dict)
    assert isinstance(oga.update_goal_fields(gid, objective="updated"), dict)
