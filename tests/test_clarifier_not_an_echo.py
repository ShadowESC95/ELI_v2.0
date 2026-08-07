"""Locks on the low-confidence clarify path.

Seen live: an answer scored 0.44 against a 0.54 threshold, so the clarifier ran —
and what reached the user as ELI's reply was

    "What's the story bud! open spotify please?"

their own opening message of the session, quoted back at them with a question mark
bolted on. The clarifier accepted any output under 90 words and *appended* '?' when
one was missing, so a command copied out of the conversation context it had been
handed was laundered into a "question".
"""
import pytest

from eli.kernel.engine import CognitiveEngine, _clarifier_is_usable, _clarifier_norm

USER_FIRST_TURN = "What's the story bud! open spotify please"
CONTEXT = f"user: {USER_FIRST_TURN}\nassistant: Opened media: spotify"
CURRENT_INPUT = "What are you getting up to?"


def _usable(generated, context=CONTEXT, user_input=CURRENT_INPUT):
    return _clarifier_is_usable(generated, user_input=user_input, context=context)


def test_the_method_is_still_on_the_engine():
    """A module-level def placed inside the class body ends it silently: the file
    still compiles and the method simply stops existing."""
    assert hasattr(CognitiveEngine, "_clarifying_response")


# ── it must actually be a question ──────────────────────────────────────────
def test_the_live_failure_is_rejected():
    assert not _usable(USER_FIRST_TURN)


@pytest.mark.parametrize("statement", [
    "I will open Spotify now.",
    "Opened media: spotify",
    "Working on tools.",
])
def test_statements_are_not_laundered_into_questions(statement):
    """The old path appended '?' to whatever it got. Punctuation cannot turn a
    command into a question."""
    assert not _usable(statement)


# ── and it must not be a replay of the conversation ─────────────────────────
def test_verbatim_replay_of_a_user_turn_is_rejected():
    """Even when it already ends in '?', quoting the user back is not clarifying."""
    assert not _usable(USER_FIRST_TURN + "?")


def test_restating_the_current_input_is_rejected():
    assert not _usable(CURRENT_INPUT)


# ── genuine clarifiers still pass ───────────────────────────────────────────
@pytest.mark.parametrize("question", [
    "Which project should I look at first?",
    "What target format and audience should I ground this on?",
    "Which runtime module should I inspect to answer that?",
])
def test_real_clarifying_questions_are_accepted(question):
    """The guard must not make ELI mute — rejection falls through to templates,
    but a good question has to survive."""
    assert _usable(question)


def test_normalisation_ignores_case_and_punctuation():
    assert _clarifier_norm("What's the STORY, bud!!") == _clarifier_norm("whats the story bud")


def test_empty_generation_is_rejected():
    assert not _usable("")
    assert not _usable("   ")
