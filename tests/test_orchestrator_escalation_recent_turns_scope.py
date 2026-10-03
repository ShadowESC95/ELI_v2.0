"""The orchestrator's grounding escalation read the last 8 conversation turns
with no user filter, so on the shared API engine one user's escalation could
be primed with another user's messages. It now reads the current user's turns
from any of their sessions, the same scope as the orchestrator's episodic
block."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from eli.cognition.orchestrator import AgentOrchestrator


def test_escalation_reads_only_the_current_users_turns():
    memory = MagicMock()
    memory.get_recent_conversation.return_value = [{"role": "user", "content": "hi"}]
    engine = SimpleNamespace(memory=memory, user_id="alice", session_id="s-1",
                             _crisis_steering=None)
    orch = AgentOrchestrator.__new__(AgentOrchestrator)
    orch.engine = engine
    wm = SimpleNamespace(trace={}, bus_result=None)

    with patch("eli.runtime.grounding_escalation.escalate", return_value=None) as esc:
        orch._maybe_grounding_escalate(wm, "what's new", {"action": "CHAT"},
                                       stream=False, reasoning_mode="quick")

    memory.get_recent_conversation.assert_called_once()
    _, kwargs = memory.get_recent_conversation.call_args
    assert kwargs.get("user_id") == "alice"
    assert "session_id" not in kwargs  # any of alice's sessions
    assert esc.call_args.kwargs["recent_turns"] == [{"role": "user", "content": "hi"}]
