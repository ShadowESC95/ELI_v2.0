"""_run_chat_reasoning_loop (chain_of_thought, self_consistency, tree_of_thoughts,
constitutional_ai) bypassed the streaming path entirely, so it never got the anti-repeat
contract or the echo-stripping guard the quick-mode path has. A real session showed it
echoing the user's own sentence back verbatim as the opening of its reply. This locks the
fix: the public _run_chat_reasoning_loop now wraps the real loop (renamed
_run_chat_reasoning_loop_inner) with the same proven contract-injection and strip logic.
"""
from unittest.mock import MagicMock

from eli.kernel.engine import CognitiveEngine


def _eng():
    e = CognitiveEngine()
    e.memory = MagicMock()
    return e


def test_an_echoed_opening_is_stripped():
    e = _eng()
    user_input = "Is there any other day? Just woke up an hour ago, checking in on you"
    e.memory.get_recent_conversation.return_value = [
        {"role": "user", "content": user_input},
    ]
    e._run_chat_reasoning_loop_inner = MagicMock(return_value={
        "response": "Is there any other day? Pfft, you're still in the morning, technically.",
        "score": 0.9, "threshold": 0.6, "evidence": {}, "clarified": False,
    })
    result = e._run_chat_reasoning_loop(user_input, "", {"action": "CHAT"}, "chain_of_thought")
    assert "Is there any other day?" not in result["response"]
    assert "Pfft" in result["response"]


def test_a_reply_with_no_overlap_is_untouched():
    e = _eng()
    user_input = "how's the weather"
    e.memory.get_recent_conversation.return_value = [
        {"role": "user", "content": user_input},
    ]
    e._run_chat_reasoning_loop_inner = MagicMock(return_value={
        "response": "No idea — I don't have a sensor for that, ask your window.",
        "score": 0.9, "threshold": 0.6, "evidence": {}, "clarified": False,
    })
    result = e._run_chat_reasoning_loop(user_input, "", {"action": "CHAT"}, "chain_of_thought")
    assert result["response"] == "No idea — I don't have a sensor for that, ask your window."


def test_the_contract_reaches_the_inner_call():
    e = _eng()
    e.memory.get_recent_conversation.return_value = [
        {"role": "assistant", "content": "A prior reply long enough to count as content."},
    ]
    e._run_chat_reasoning_loop_inner = MagicMock(return_value={
        "response": "fine", "score": 0.9, "threshold": 0.6, "evidence": {}, "clarified": False,
    })
    e._run_chat_reasoning_loop("ok", "", {"action": "CHAT"}, "chain_of_thought")
    _, kwargs = e._run_chat_reasoning_loop_inner.call_args
    assert "ALREADY SAID" in kwargs["situation_brief"]


def test_an_entirely_repeated_reply_is_still_served():
    """Stripping to nothing is worse than an honest duplicate."""
    e = _eng()
    user_input = "Is there any other day?"
    e.memory.get_recent_conversation.return_value = [
        {"role": "user", "content": user_input},
    ]
    e._run_chat_reasoning_loop_inner = MagicMock(return_value={
        "response": "Is there any other day?",
        "score": 0.9, "threshold": 0.6, "evidence": {}, "clarified": False,
    })
    result = e._run_chat_reasoning_loop(user_input, "", {"action": "CHAT"}, "chain_of_thought")
    assert result["response"] == "Is there any other day?"


def test_a_memory_lookup_failure_does_not_break_the_response():
    e = _eng()
    e.memory.get_recent_conversation.side_effect = RuntimeError("db down")
    e._run_chat_reasoning_loop_inner = MagicMock(return_value={
        "response": "fine either way", "score": 0.9, "threshold": 0.6,
        "evidence": {}, "clarified": False,
    })
    result = e._run_chat_reasoning_loop("ok", "", {"action": "CHAT"}, "chain_of_thought")
    assert result["response"] == "fine either way"
