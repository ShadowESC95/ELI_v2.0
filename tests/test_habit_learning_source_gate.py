"""ELI's own automation (habit firing, scheduled tasks, ...) must not feed habit_events —
detect_habits() mines that table for recurring USER routines, and a self-triggered run
must not reinforce itself as if it were fresh, independent evidence of a pattern."""
from unittest.mock import MagicMock

import pytest

from eli.kernel.engine import CognitiveEngine


@pytest.fixture
def eng():
    e = CognitiveEngine()
    e.memory = MagicMock()
    return e


def _intent(action="OPEN_APP", **args):
    return {"action": action, "args": args, "confidence": 0.9, "meta": {}}


@pytest.mark.parametrize("source", ["habit", "proactive", "scheduler", "system", "autonomy",
                                    "HABIT", "Scheduler"])
def test_autonomous_sources_do_not_write_habit_events(eng, source):
    eng._learn_from_result(_intent(name="steam"), {"ok": True}, source=source)
    eng.memory.log_habit_event.assert_not_called()


@pytest.mark.parametrize("source", ["user", "USER"])
def test_user_sourced_turns_still_write_habit_events(eng, source):
    eng._learn_from_result(_intent(name="steam"), {"ok": True, "cmd": "steam"}, source=source)
    assert eng.memory.log_habit_event.called
    calls = [c.args[0] for c in eng.memory.log_habit_event.call_args_list]
    assert "command_result" in calls
    assert "app_launch" in calls


def test_default_source_is_user():
    eng = CognitiveEngine()
    eng.memory = MagicMock()
    eng._learn_from_result(_intent(name="steam"), {"ok": True, "cmd": "steam"})
    assert eng.memory.log_habit_event.called


def test_autonomous_source_still_writes_learning_event_and_evidence_ledger(eng):
    eng._learn_from_result(_intent(), {"ok": True}, source="habit")
    assert eng.memory.log_learning_event.called
    # source is tagged honestly, not hidden
    _, kwargs = eng.memory.log_learning_event.call_args
    assert kwargs["metadata"]["source"] == "habit"


def test_is_autonomous_source_matches_settle_recall_outcome_vocabulary():
    for s in ("habit", "proactive", "scheduler", "system", "autonomy"):
        assert CognitiveEngine._is_autonomous_source(s) is True
    for s in ("user", "", None):
        assert CognitiveEngine._is_autonomous_source(s) is False


def test_finalize_turn_threads_source_through_to_learn_from_result(eng, monkeypatch):
    # process()'s normal exit path calls learning_coordinator.finalize_turn(), not
    # _learn_from_result() directly (that's only the except-fallback) — a real gap this
    # session's own personal-adaptation fix missed: finalize_turn() didn't accept or forward
    # `source`, so the primary path always learned as if it were a user turn.
    from eli.cognition.learning_coordinator import finalize_turn

    spy = MagicMock()
    eng._learn_from_result = spy
    eng._publish_last_response_meta = MagicMock()
    eng._store_assistant_turn = MagicMock()

    finalize_turn(
        eng, user_input="close steam", response="done",
        intent=_intent(name="steam"), result={"ok": True, "cmd": "steam"},
        source="habit",
    )
    spy.assert_called_once()
    _, kwargs = spy.call_args
    assert kwargs.get("source") == "habit"


def test_finalize_turn_defaults_source_to_user(eng):
    from eli.cognition.learning_coordinator import finalize_turn

    spy = MagicMock()
    eng._learn_from_result = spy
    eng._publish_last_response_meta = MagicMock()
    eng._store_assistant_turn = MagicMock()

    finalize_turn(eng, user_input="hi", response="hello",
                  intent=_intent(), result={"ok": True})
    _, kwargs = spy.call_args
    assert kwargs.get("source") == "user"
