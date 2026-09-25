"""A greeting that asks ELI to remember must reach memory retrieval."""
import pytest

from eli.cognition.chat_grounding_gate import is_phatic_turn
from eli.kernel.engine import _is_brief_phatic_prompt

MEMORY_REQUESTS = [
    "Hey there, how are things? remember our recent conversations?",
    "Hi Eli, do you remember what movies I watched last week?",
    "good morning, what did we talk about yesterday?",
    "hey there, do you recall what I said earlier?",
]
SMALL_TALK = [
    "hey eli",
    "good morning",
    "how are you doing today",
    "thanks",
]


@pytest.mark.parametrize("text", MEMORY_REQUESTS)
def test_memory_requests_are_not_phatic(text):
    assert _is_brief_phatic_prompt(text) is False
    assert is_phatic_turn(text) is False


@pytest.mark.parametrize("text", SMALL_TALK)
def test_plain_greetings_stay_phatic(text):
    assert _is_brief_phatic_prompt(text) is True
    assert is_phatic_turn(text) is True
