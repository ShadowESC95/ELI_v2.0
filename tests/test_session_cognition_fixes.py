"""Session continuity, anti-repeat, and grounding fixes."""
from __future__ import annotations

from types import SimpleNamespace

from eli.runtime.grounding_escalation import escalate


def test_session_travel_chat_skips_hedge():
    out = escalate(
        SimpleNamespace(_synthesize_answer=lambda *a, **k: "x"),
        user_input=(
            "no dude, his family lives in wexford, he lives in galway, "
            "i live in wexford too. i am driving from wexford to galway "
            "to collect him and bring him back down to his family in wexford"
        ),
        intent={"action": "CHAT"},
        bus_result=SimpleNamespace(grounding_confidence=0.26),
        reasoning_mode="quick",
        recent_turns=[],
        trace={},
    )
    assert out is None


def test_engine_collects_multiple_assistant_replies():
    from eli.kernel.engine import CognitiveEngine

    eng = CognitiveEngine.__new__(CognitiveEngine)
    eng.memory = SimpleNamespace(
        get_recent_conversation=lambda **_: [
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "reply one"},
            {"role": "user", "content": "b"},
            {"role": "assistant", "content": "reply two"},
            {"role": "user", "content": "c"},
            {"role": "assistant", "content": "reply three"},
        ]
    )
    eng.user_id = "u1"
    eng.session_id = "s1"
    reps = eng._collect_recent_assistant_replies()
    assert reps == ["reply one", "reply two", "reply three"]
