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


# ── ELI's own self-status talk must never become recalled "knowledge" ──
# The live loop: ELI said "still glitchy…" → stored as a turn → the reflection engine
# summarised it as "Top topics: glitchy" → recalled under "Stored knowledge:" → recited
# again, reinforcing itself across SESSIONS.
import re as _re

_FIRST_PERSON = r"\b(i'?m|i am|i've|i have been|my)\b"
_STATE = (r"\b(glitch\w*|standing by|running on|same old code|still here|buggy|broken|"
          r"fine|okay|ok|good|alright|well|ready|online|operational|functioning|state|"
          r"status|mood|feeling)\b")
_UNMISTAKABLE = r"\b(still glitch\w*|same old code|standing by|running on the same)\b"


def _is_self_status(text: str) -> bool:
    low = text.lower()
    return bool((_re.search(_FIRST_PERSON, low) and _re.search(_STATE, low))
                or _re.search(_UNMISTAKABLE, low))


def test_self_status_talk_is_not_stored_as_knowledge():
    for t in [
        "I'm standing by, still glitchy, still running on the same old code. How's it going?",
        "Sahns. Still glitchy, still running on the same old code. How's it going?",
        "I'm good, ready when you are.",
    ]:
        assert _is_self_status(t), f"would still be stored as knowledge: {t!r}"


def test_real_content_is_still_storable():
    for t in [
        "Your QMSH Model 06 uses a 15-model evaluation baseline for the grant.",
        "The Tesla rifle design went through three iterations with a ZVS driver.",
        "You prefer perpetual licences over subscriptions for ELI.",
    ]:
        assert not _is_self_status(t), f"real content wrongly blocked: {t!r}"
