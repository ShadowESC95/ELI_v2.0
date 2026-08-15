"""A greeting is meant to recur — the anti-repeat guard must not "fix" one.

Live at 2.1.83, 23:10. The user typed "Good aftrnoon, Eli". The log shows the model
getting it RIGHT and the guard overruling it:

    [GGUF][RAW_HEAD] 'Even'                                    ← "Evening…", correct at 23:10
    [ANTI-REPEAT] opening matched a recent reply — regenerating
    [ANTI-REPEAT] retry generation issued (… temp=1.2)
    [GGUF][RAW_HEAD] 'Af'                                      ← "Aftrnoon, alex…"

The reply that reached the user echoed their own misspelling, named the wrong time
of day, and then asked them to explain why they had spelled it that way. Nothing was wrong
with ELI's clock — the system prompt carries "CURRENT TIME (authoritative, do not
approximate)", which is why the first attempt said Evening. The guard matched that
correct opening against the previous session's greeting, threw it away, and the
retry was explicitly instructed to produce "different content".

Both pressures are removed on a greeting turn: the enforcement guard AND the prompt
contract that quotes prior replies and forbids repeating them. Disarming only the
checker would have left the instruction pushing the model off the right answer.
"""
import pytest

from eli.kernel.engine import (
    _RepeatDetected,
    _is_greeting_turn,
    _stream_holding_back_repeats,
    _user_asked_for_a_repeat,
)


# The previous session's opener, verbatim from the transcript.
PRIOR_GREETING = "Evening. You're still alive, I see. How's the fallout?"


@pytest.mark.parametrize("asked", [
    "Good aftrnoon, Eli",      # the actual message that exposed this
    "good evening bud",
    "afternoon pal, ho is the head?",
    "morning",
    "Good morning!",
    "hey",
    "hi eli",
    "Hey there Eli",
    "evenin",
    "good nite",
    "yo",
    "howya",
])
def test_greetings_are_recognised_including_typos(asked):
    assert _is_greeting_turn(asked), asked


@pytest.mark.parametrize("asked", [
    "what have you been doing?",
    "his name is Sam",                      # 'his' scores 0.8 against 'hi'
    "how do I fix the parser",
    "how is the head",
    "night mode is broken please fix",      # a time word opening a real request
    "morning, why did the build fail",
    "evening run the tests",
    "so what happened to the vector index",
    "hey can you fix the parser bug in vector store please",
    "nice one",
    "no",
])
def test_ordinary_turns_keep_their_protection(asked):
    assert not _is_greeting_turn(asked), asked


def test_the_guard_still_stands_down_for_an_explicit_repeat_request():
    """The pre-existing exemption must survive alongside the new one."""
    assert _user_asked_for_a_repeat("say that again")
    assert not _is_greeting_turn("say that again")


def test_a_repeated_greeting_would_have_been_caught_before(monkeypatch):
    """Proves the guard really did fire on this material — otherwise the fix
    below could pass without changing anything."""
    chunks = [PRIOR_GREETING[i:i + 7] for i in range(0, len(PRIOR_GREETING), 7)]
    with pytest.raises(_RepeatDetected):
        list(_stream_holding_back_repeats(chunks, [PRIOR_GREETING], allow_retry=True))


def test_a_greeting_turn_disarms_the_guard():
    """stream_chat leaves the recent-reply list empty on a greeting; with nothing
    to compare against, the same text now streams through untouched."""
    recent = [] if _is_greeting_turn("Good aftrnoon, Eli") else [PRIOR_GREETING]
    chunks = [PRIOR_GREETING[i:i + 7] for i in range(0, len(PRIOR_GREETING), 7)]
    out = "".join(_stream_holding_back_repeats(chunks, recent, allow_retry=True))
    assert out == PRIOR_GREETING


def test_a_non_greeting_turn_still_regenerates():
    """The guard must keep working for everything that is not a hello."""
    recent = [] if _is_greeting_turn("what have you been doing?") else [PRIOR_GREETING]
    assert recent, "a normal turn must still carry the comparison set"
    chunks = [PRIOR_GREETING[i:i + 7] for i in range(0, len(PRIOR_GREETING), 7)]
    with pytest.raises(_RepeatDetected):
        list(_stream_holding_back_repeats(chunks, recent, allow_retry=True))
