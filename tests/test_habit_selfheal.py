"""Habit rules: reject un-schedulable adds + self-heal legacy corruption that
showed as 'active habits at 00:00' (enabled, NULL time, bare-token command)."""
from __future__ import annotations
import pytest
from eli.memory.memory import Memory


def _mem(tmp_path):
    return Memory(db_path=str(tmp_path / "user.sqlite3"))


def test_add_habit_rule_rejects_none_time(tmp_path):
    m = _mem(tmp_path)
    with pytest.raises(ValueError):
        m.add_habit_rule("x", "open x", None, 5)
    with pytest.raises(ValueError):
        m.add_habit_rule("x", "open x", 9, None)
    # a properly-timed rule still works
    rid = m.add_habit_rule("Open firefox at 09:30", "firefox", 9, 30, enabled=True)
    assert rid and rid > 0


def test_disable_invalid_habit_rules(tmp_path):
    m = _mem(tmp_path)
    # valid scheduled rule (name != command) — must be KEPT
    m.add_habit_rule("Open firefox at 09:30", "firefox", 9, 30, enabled=True)
    # inject legacy corruption directly (bypassing the guard)
    conn = m._get_connection()
    conn.execute("INSERT INTO habit_rules(name,command,hour,minute,days,enabled,timestamp,ts)"
                 " VALUES('firefox','firefox',NULL,NULL,NULL,1,0,0)")
    conn.execute("INSERT INTO habit_rules(name,command,hour,minute,days,enabled,timestamp,ts)"
                 " VALUES('spotify','spotify',NULL,NULL,NULL,1,0,0)")
    conn.commit()
    conn.close()

    n = m.disable_invalid_habit_rules()
    assert n == 2, f"expected 2 disabled, got {n}"
    names = [r.get("name") for r in m.get_habit_rules(enabled_only=True)]
    assert "Open firefox at 09:30" in names      # valid rule kept active
    assert "firefox" not in names and "spotify" not in names  # corruption disabled
    # idempotent — second run disables nothing new
    assert m.disable_invalid_habit_rules() == 0
