"""A plain text reply is not proof a scheduled action ran, and a restart in the same minute must not run it twice."""
import sys
from types import SimpleNamespace

from eli.planning.habits_scheduler import HabitScheduler


def _scheduler(monkeypatch, tmp_path):
    monkeypatch.setattr("eli.planning.habits._artifacts_dir", lambda: tmp_path)
    monkeypatch.setattr("eli.planning.habits_scheduler.get_memory", lambda: SimpleNamespace(), raising=False)
    s = HabitScheduler.__new__(HabitScheduler)
    s._fired_keys = set()
    s.memory = SimpleNamespace(record_habit_run=lambda *a, **k: None)
    return s


def _engine(monkeypatch, result):
    monkeypatch.setitem(sys.modules, "eli.kernel.engine", SimpleNamespace(get_engine=lambda: SimpleNamespace(process=lambda cmd, source="": result)))


def test_text_only_is_unverified(monkeypatch, tmp_path, capsys):
    s = _scheduler(monkeypatch, tmp_path)
    _engine(monkeypatch, "Opened the editor for you.")
    s._execute_rule({"name": "r", "command": "open editor", "id": 1})
    out = capsys.readouterr().out
    assert "Success" not in out and "unverified" in out


def test_a_structured_ok_is_success(monkeypatch, tmp_path, capsys):
    s = _scheduler(monkeypatch, tmp_path)
    _engine(monkeypatch, {"ok": True, "content": "done"})
    s._execute_rule({"name": "r", "command": "open editor", "id": 1})
    assert "Success" in capsys.readouterr().out


def test_run_keys_survive_a_restart(monkeypatch, tmp_path):
    s = _scheduler(monkeypatch, tmp_path)
    s._fired_keys = {(3, "202609251200")}
    s._save_fired()
    assert (3, "202609251200") in s._load_fired()
