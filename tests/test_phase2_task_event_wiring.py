"""Phase 2 of the identity/provenance plan (2026-10-02): finalize_turn()
(learning_coordinator.py, the non-streaming/action-turn path) never called
capture_task_events() — confirmed by direct read, not assumed: it runs
_publish_last_response_meta, _store_assistant_turn, _learn_from_result, and
nothing else. The CHAT path (_finalize_chat_result -> _maybe_store_memory)
already captures task events unconditionally for every chat turn; action
turns routed through finalize_turn got none at all.

Fixed with one new step inside finalize_turn, gated on result.get("ok",
True) — unlike the chat path, which has no real ok/fail axis to gate on,
an action result does, and a FAILED action ("set a timer" that silently
didn't fire) should not be recorded as a decided/done step.

The plan's original phrasing imagined a single shared helper threaded
through _finalize_chat_result's 6 callers plus finalize_turn. Re-verified:
those 6 callers already funnel through one existing chokepoint
(_maybe_store_memory) that already fires unconditionally — the actual gap
was only here, in the genuinely separate finalize_turn path. Building a new
shared helper for an already-solved problem would have been scope creep.
"""
from unittest.mock import MagicMock

import pytest

from eli.cognition.learning_coordinator import finalize_turn
from eli.planning import goal_store as gs


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(gs, "goal_store_path", lambda: tmp_path / "goals.json")


def _engine():
    eng = MagicMock()
    eng._publish_last_response_meta = MagicMock()
    eng._store_assistant_turn = MagicMock()
    eng._learn_from_result = MagicMock()
    return eng


def test_a_successful_action_turn_captures_its_task_event():
    gs.open_task("Rebuild the tuner")
    finalize_turn(
        _engine(), user_input="We decided to keep the scenarios deterministic and offline",
        response="Done.", intent={"action": "CHAT"}, result={"ok": True},
    )
    assert "keep the scenarios deterministic" in gs.task_brief()


def test_a_failed_action_turn_does_not_record_a_task_event():
    gs.open_task("Rebuild the tuner")
    finalize_turn(
        _engine(), user_input="We decided to keep the scenarios deterministic and offline",
        response="That failed.", intent={"action": "CHAT"}, result={"ok": False},
    )
    assert "keep the scenarios deterministic" not in gs.task_brief()


def test_ok_defaults_true_when_result_omits_it():
    """result.get("ok", True) — an action result with no explicit ok field is
    treated as having succeeded, same default the audit chain already uses."""
    gs.open_task("Rebuild the tuner")
    finalize_turn(
        _engine(), user_input="We decided to keep the scenarios deterministic and offline",
        response="Done.", intent={"action": "CHAT"}, result={},
    )
    assert "keep the scenarios deterministic" in gs.task_brief()


def test_a_broken_capture_never_breaks_the_rest_of_finalize_turn(monkeypatch):
    """Best-effort: a goal_store failure must not take down publish/store/learn."""
    def _boom(*a, **k):
        raise RuntimeError("goal store unavailable")
    monkeypatch.setattr(
        "eli.planning.goal_store.capture_task_events", _boom)

    eng = _engine()
    finalize_turn(
        eng, user_input="We decided to keep the scenarios deterministic and offline",
        response="Done.", intent={"action": "CHAT"}, result={"ok": True},
    )
    eng._publish_last_response_meta.assert_called_once()
    eng._store_assistant_turn.assert_called_once()
    eng._learn_from_result.assert_called_once()
