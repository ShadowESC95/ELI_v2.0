"""Audit now catches LIVE issues (subsystem health + data integrity + logged
failures), and the habit scheduler actually runs active app-launch habits while
still blocking bare ACTION tokens."""
from __future__ import annotations
import sqlite3
import pytest


def test_runtime_audit_includes_health_probes():
    from eli.execution.executor_enhanced import _runtime_health_probes, _runtime_audit_report
    probes = _runtime_health_probes()
    names = {p["name"] for p in probes}
    assert {"plugin_manager", "memory", "agent_bus", "habit_integrity",
            "recent_failures"} <= names
    for p in probes:
        assert "ok" in p and "detail" in p and p["detail"]
    # wired into the report
    rep = _runtime_audit_report()
    assert "health_probes" in rep and rep["health_probes"]


def test_health_probe_flags_malformed_habits(tmp_path, monkeypatch):
    # a db with an un-schedulable enabled rule must make the probe report BAD
    dbp = tmp_path / "user.sqlite3"
    c = sqlite3.connect(str(dbp))
    c.execute("CREATE TABLE habit_rules(id INTEGER PRIMARY KEY, name TEXT, command TEXT, "
              "hour INT, minute INT, enabled INT)")
    c.execute("INSERT INTO habit_rules(name,command,hour,minute,enabled) "
              "VALUES('spotify','spotify',NULL,NULL,1)")  # corruption
    c.execute("INSERT INTO habit_rules(name,command,hour,minute,enabled) "
              "VALUES('Open firefox at 09:30','firefox',9,30,1)")  # valid
    c.commit(); c.close()

    class _FM: db_path = str(dbp)
    monkeypatch.setattr("eli.memory.get_memory", lambda: _FM())
    from eli.execution.executor_enhanced import _runtime_health_probes
    hp = {p["name"]: p for p in _runtime_health_probes()}
    assert hp["habit_integrity"]["ok"] is False
    assert "un-schedulable" in hp["habit_integrity"]["detail"]


def test_scheduler_runs_app_habit_but_skips_action_token(monkeypatch):
    from eli.planning import habits_scheduler as HS
    calls = []

    class FakeEngine:
        def process(self, cmd, source=None):
            calls.append(cmd)
            return {"ok": True, "content": "done"}

    monkeypatch.setattr("eli.kernel.engine.get_engine", lambda: FakeEngine())
    sched = HS.HabitScheduler.__new__(HS.HabitScheduler)  # bypass __init__/thread

    class FakeMem:
        def record_habit_run(self, rid): pass
    sched.memory = FakeMem()

    sched._execute_rule({"id": 1, "name": "firefox", "command": "firefox"})
    assert calls == ["firefox"], "active app-launch habit must run"
    calls.clear()
    sched._execute_rule({"id": 2, "name": "GET_WEATHER", "command": "GET_WEATHER"})
    assert calls == [], "bare ACTION token must be skipped"
