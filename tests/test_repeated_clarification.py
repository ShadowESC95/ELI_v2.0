"""ELI must not ask a question the user has already answered.

Live session, verbatim: the user said "I am making a list of things that need
fixing in your codebase and testing edge cases", and over the following turns
ELI asked "what exactly are you trying to do here?" four separate times, until
the user replied in capitals that they had already told it. The anti-repeat
guard did fire on those turns -- but it only compares the OPENING of a reply,
so each ask began with a different word and passed, while the question
underneath stayed identical.

Rephrasing cannot fix asking for information already given, so this checks the
conversation instead of the wording: if ELI has already asked for intent and
the user has said something substantive since, the ask is dropped.
"""
import pytest

from eli.cognition import output_governor as og


REAL_HISTORY = [
    ("user", "no, i do not trust you. I am making a list of things that need "
             "fixing in your codebase and testing edge cases, we observe and "
             "report for the moment"),
    ("assistant", "You're right - I'm not fighting. So what exactly are you "
                  "trying to do here?"),
    ("user", "I have fucking told you what i am doing here, several times!"),
]


@pytest.mark.parametrize("reply", [
    "So what exactly are you trying to do here?",
    "Let me cut the fluff: what exactly are you trying to do here?",
    "What do you mean by that?",
    "Could you clarify what you need from me?",
    "Let me know what you'd like me to do next.",
    "What would you like me to do?",
])
def test_intent_questions_are_detected(reply):
    assert og.asks_user_to_restate(reply) is True


@pytest.mark.parametrize("reply", [
    "I closed the file via wmctrl.",
    "Playing the third world by immortal technique on Spotify.",
    "What time would you like the alarm set for?",     # a specific detail, not intent
    "The model failed to load because a tensor is missing.",
])
def test_ordinary_replies_are_not_flagged(reply):
    assert og.asks_user_to_restate(reply) is False


def test_repeat_ask_is_dropped_but_the_rest_survives():
    reply = ("You're right. And I'm sorry. Let me cut the fluff: what exactly "
             "are you trying to do here?")
    out = og.drop_repeated_clarification(reply, REAL_HISTORY)
    assert "trying to do here" not in out, "the repeated question survived"
    assert "You're right" in out, "the rest of the reply was destroyed"


def test_first_ask_is_never_suppressed():
    """Asking once is legitimate; only asking AGAIN is the defect."""
    history = [("user", "I am testing edge cases on your desktop control")]
    reply = "What exactly are you trying to do here?"
    assert og.drop_repeated_clarification(reply, history) == reply


def test_no_history_changes_nothing():
    reply = "What exactly are you trying to do here?"
    assert og.drop_repeated_clarification(reply, None) == reply
    assert og.drop_repeated_clarification(reply, []) == reply


def test_reply_is_never_emptied():
    """Losing the whole answer would be worse than repeating the question.

    This is a deliberate limit, not an oversight: when the reply is NOTHING BUT
    the repeated question there is nothing to keep, and the governor has no
    evidence of its own to substitute. Inventing a canned line here would break
    the no-hard-coded-responses rule, so the question survives. The fix for that
    case has to be upstream, in what the model generates.
    """
    reply = "What do you mean?"
    assert og.drop_repeated_clarification(reply, REAL_HISTORY) == reply

    pure = "So what exactly are you trying to do here?"
    assert og.drop_repeated_clarification(pure, REAL_HISTORY) == pure


def test_a_short_user_ack_does_not_count_as_answering():
    """'ok' after a question is not an answer, so the next ask is legitimate."""
    history = [
        ("assistant", "What exactly are you trying to do here?"),
        ("user", "ok"),
    ]
    reply = "What exactly are you trying to do?"
    assert og.drop_repeated_clarification(reply, history) == reply


def test_dict_turn_shape_is_supported():
    """The memory layer returns dicts, not tuples."""
    history = [
        {"role": "user", "content": "I am auditing your desktop control"},
        {"role": "assistant", "content": "What exactly are you trying to do here?"},
        {"role": "user", "content": "I already told you what I am doing"},
    ]
    reply = ("Right, you already said that and I should have kept it. "
             "So what exactly are you trying to do here?")
    out = og.drop_repeated_clarification(reply, history)
    assert "trying to do here" not in out
    assert "you already said that" in out


def test_governor_accepts_history_and_stays_backward_compatible():
    import inspect
    sig = inspect.signature(og.govern_output)
    assert "history" in sig.parameters
    assert sig.parameters["history"].default is None, \
        "existing callers must behave exactly as before"
    # A call without history must not raise.
    assert og.govern_output("Hello there.") .strip()


def test_engine_passes_recent_turns_to_the_governor():
    from pathlib import Path
    src = Path("eli/kernel/engine.py").read_text(encoding="utf-8")
    code = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
    assert "history=_gov_hist" in code, "the governor never receives conversation history"
    assert "get_recent_conversation(limit=8)" in code
