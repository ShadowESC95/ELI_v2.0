"""ELI must not ask the user for the clock it is already given.

Live: "You're awake now? What time is it?" -- asked while CURRENT TIME
(authoritative) sat in its own context. Told to check for itself, it routed to
the TIME action and answered in 0.077s. The capability was never missing.

A prompt instruction cannot fix this: the model is already told not to guess the
time. The OUTPUT has to be checked.
"""
from eli.cognition.output_governor import drop_questions_for_facts_already_held as drop


def test_the_observed_question_is_dropped():
    out = drop("Sorry — I thought you were still watching. You are awake now? "
               "What time is it?")
    assert "what time is it" not in out.lower()
    assert "you are awake now?" in out.lower(), "it removed more than the question"


def test_date_questions_are_dropped_too():
    """Carriers are deliberately long enough to survive the never-empty rail."""
    for q, gone in (
        ("Glad the headache has cleared up at last. What's the date today?", "date today"),
        ("That film really does drag on forever, doesn't it. What day is it?", "what day is it"),
        ("I have lost track of things completely here. Do you know what the time it is?",
         "what the time it is"),
    ):
        out = drop(q)
        assert gone.lower() not in out.lower(), f"not dropped: {q!r} -> {out!r}"
        assert len(out.split()) >= 3, f"reply gutted: {out!r}"


def test_real_questions_about_the_user_survive():
    """Only the clock is ELI's to know -- the user's intent and past are not."""
    for keep in ("What time do you want the alarm set for?",
                 "What time did you get in last night?",
                 "What time works for you tomorrow?"):
        assert drop(keep) == keep, keep


def test_statements_about_the_time_survive():
    keep = "It is 14:41 now, so you have plenty of time."
    assert drop(keep) == keep


def test_it_never_empties_a_reply():
    """A silent turn is a worse failure than an odd one."""
    assert drop("What time is it?") == "What time is it?"
