"""A high-priority world-awareness suggestion must defer to an active user turn, respect its
own cooldown, and never claim to have "triggered"/auto-executed an action it never ran."""
import queue
from unittest.mock import MagicMock, patch

import pytest

from eli.planning.proactive_daemon import ProactiveDaemon


@pytest.fixture(autouse=True)
def isolated_attention_queue(tmp_path, monkeypatch):
    monkeypatch.setenv("ELI_DATA_DIR", str(tmp_path))


class _FakeDaemon:
    def __init__(self):
        self.suggestion_queue = queue.Queue()
        self.agent_mem = MagicMock()
        self.user_mem = MagicMock()


def _handle(d, action="OPEN_APP", reason="pattern detected", priority=0.85):
    ProactiveDaemon._handle_high_priority_world_suggestion(d, action, reason, priority)


def test_defers_when_the_user_is_mid_turn():
    d = _FakeDaemon()
    with patch("eli.cognition.inference_broker.foreground_recently_active", return_value=True):
        _handle(d)
    assert d.suggestion_queue.empty()
    d.agent_mem.store_memory.assert_not_called()


def test_surfaces_when_not_busy_and_not_suppressed():
    d = _FakeDaemon()
    with patch("eli.cognition.inference_broker.foreground_recently_active", return_value=False):
        _handle(d, action="OPEN_APP", reason="recurring pattern")
    assert not d.suggestion_queue.empty()
    kind, payload = d.suggestion_queue.get_nowait()
    assert kind == "world_action"
    # honest: a suggestion, not a claimed execution
    assert "triggered" not in payload["suggestion"].lower()
    assert "[auto]" not in payload["suggestion"].lower()
    assert payload["action"] == "OPEN_APP"

    assert d.agent_mem.store_memory.called
    note_text = d.agent_mem.store_memory.call_args.args[0]
    assert "triggered" not in note_text.lower()
    tags = d.agent_mem.store_memory.call_args.kwargs["tags"]
    assert "auto" not in tags
    assert "suggested" in tags


def test_a_repeat_within_the_cooldown_window_is_suppressed():
    d1 = _FakeDaemon()
    with patch("eli.cognition.inference_broker.foreground_recently_active", return_value=False):
        _handle(d1, action="OPEN_APP", reason="first time")
    assert not d1.suggestion_queue.empty()

    d2 = _FakeDaemon()
    with patch("eli.cognition.inference_broker.foreground_recently_active", return_value=False):
        _handle(d2, action="OPEN_APP", reason="same action again")
    assert d2.suggestion_queue.empty()
    d2.agent_mem.store_memory.assert_not_called()


def test_a_different_action_is_not_suppressed_by_an_unrelated_cooldown():
    d1 = _FakeDaemon()
    with patch("eli.cognition.inference_broker.foreground_recently_active", return_value=False):
        _handle(d1, action="OPEN_APP", reason="pattern A")

    d2 = _FakeDaemon()
    with patch("eli.cognition.inference_broker.foreground_recently_active", return_value=False):
        _handle(d2, action="CLOSE_APP", reason="pattern B")
    assert not d2.suggestion_queue.empty()


def test_surfaced_suggestions_land_in_the_real_attention_queue():
    d = _FakeDaemon()
    with patch("eli.cognition.inference_broker.foreground_recently_active", return_value=False):
        _handle(d, action="OPEN_APP", reason="visible in operator console now")

    from eli.planning.attention_queue import recent_attention
    items = recent_attention(limit=10)["items"]
    assert any("OPEN_APP" in (it.get("title") or "") for it in items)
