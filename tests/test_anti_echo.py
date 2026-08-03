"""ELI must not serve its own previous reply back to the user.

Live failure this guards: ELI answered "still glitchy, still running on the same old
code. How's it going?" on three consecutive turns — once with the speaker flipped —
while ignoring what the user had actually said. Its replies are recalled as context,
so on a short turn the model can latch onto its own last line; token-level
repeat_penalty cannot see across turns.
"""
from __future__ import annotations
from eli.cognition.output_governor import is_echo_of_recent

PREV = ["Sahns. Still glitchy, still running on the same old code. How's it going?"]


def test_verbatim_echo_detected():
    assert is_echo_of_recent("Still glitchy, still running on the same old code. How's it going?", PREV)


def test_reworded_echo_detected():
    assert is_echo_of_recent(
        "I'm standing by, still glitchy, still running on the same old code. How's it going?", PREV)


def test_echo_wrapped_in_new_words_detected():
    # a cosmetic prefix must not smuggle the same sentence through again
    assert is_echo_of_recent(
        "Typo? I caught that. You're still glitchy, still running on the same old code. "
        "How's it going?", PREV)


def test_genuine_reply_is_not_flagged():
    assert not is_echo_of_recent(
        "Nice one — Rick and Morty's a solid breakfast pairing. Which season are you on?", PREV)
    assert not is_echo_of_recent(
        "Good, thanks — how's the morning going so far? Anything you want to dig into?", PREV)


def test_short_acknowledgements_may_repeat():
    # "Yes."/"Done." legitimately recur; only substantial replies are policed
    assert not is_echo_of_recent("Yes.", PREV)
    assert not is_echo_of_recent("Done.", ["Done."])


def test_empty_and_missing_history_are_safe():
    assert not is_echo_of_recent("", PREV)
    assert not is_echo_of_recent("Some perfectly fine reply that is long enough to count.", [])
    assert not is_echo_of_recent("Another fine reply that is long enough to count here.", None)
