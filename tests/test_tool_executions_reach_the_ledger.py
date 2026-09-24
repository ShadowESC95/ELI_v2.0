"""Every executed action is recorded in the evidence ledger (names of args, not values)."""
import pytest

from eli.execution import executor_enhanced as EX
from eli.runtime import evidence_ledger as led


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    db = tmp_path / "ledger.sqlite3"
    monkeypatch.setattr(led, "_default_db_path", lambda: db)
    monkeypatch.delenv("ELI_LEDGER_TOOL_EVENTS", raising=False)
    return db


def _events(db):
    return [e for e in led.recent_events(limit=50, db_path=db) if e.get("event_type") == "tool_execution"]


def test_an_executed_action_is_recorded(ledger):
    EX._record_tool_execution("WRITE_NOTE", {"text": "secret plan", "title": "t"}, {"ok": True, "response": "Wrote note"})
    (ev,) = _events(ledger)
    assert ev["action"] == "WRITE_NOTE" and ev["outcome"] == "ok"


def test_argument_values_are_never_stored(ledger):
    EX._record_tool_execution("WRITE_NOTE", {"text": "secret plan"}, {"ok": True})
    import json
    assert "secret plan" not in json.dumps(_events(ledger))
    assert _events(ledger)[0]["subject"] == "text"


def test_a_failure_is_recorded_as_failed(ledger):
    EX._record_tool_execution("OPEN_APP", {"app": "x"}, {"ok": False, "response": "not found"})
    assert _events(ledger)[0]["outcome"] == "failed"


def test_chat_and_the_off_switch_record_nothing(ledger, monkeypatch):
    EX._record_tool_execution("CHAT", {}, {"ok": True})
    monkeypatch.setenv("ELI_LEDGER_TOOL_EVENTS", "0")
    EX._record_tool_execution("TIME", {}, {"ok": True})
    assert _events(ledger) == []


def test_execute_itself_records_the_call(ledger):
    EX.execute("TIME", {})
    assert any(e["action"] == "TIME" for e in _events(ledger))
